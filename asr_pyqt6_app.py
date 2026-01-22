import base64
import gzip
import hashlib
import json
import logging
import math
import os
import queue
import re
import shutil
import socket
import ssl
import struct
import sys
import subprocess
import threading
import time
import uuid
from array import array
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlparse

def _resolve_log_path() -> str:
    path = os.environ.get("JT_LOG_PATH")
    if path:
        return path
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base = os.path.join(base, "just-talk")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config", "JustTalk")
    return os.path.join(base, "logs", "app.log")


def _setup_logging() -> None:
    log_path = _resolve_log_path()
    log_dir = os.path.dirname(log_path)
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        filename=log_path,
        filemode="a",
    )


def _env_flag_enabled(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disable", "disabled"}


def _force_x11_platform() -> None:
    if not sys.platform.startswith("linux"):
        return
    if not _env_flag_enabled("JT_FORCE_X11", True):
        return
    # Force X11/XWayland to avoid Wayland positioning limitations.
    os.environ["QT_QPA_PLATFORM"] = "xcb"


def _bootstrap_runtime() -> None:
    _setup_logging()
    _force_x11_platform()
    if not getattr(sys, "frozen", False):
        return
    base_dir = getattr(sys, "_MEIPASS", "")
    if not base_dir:
        return
    qt_bin = os.path.join(base_dir, "PyQt6", "Qt6", "bin")
    if os.path.isdir(qt_bin):
        os.environ["PATH"] = qt_bin + os.pathsep + os.environ.get("PATH", "")


_bootstrap_runtime()
LOG = logging.getLogger("just-talk")

try:
    from PyQt6 import QtCore, QtGui, QtWidgets, QtQml
    from PyQt6.QtCore import Qt
    from PyQt6 import QtWebChannel, QtWebEngineCore, QtWebEngineWidgets
except Exception:
    LOG.exception("Failed to import PyQt6")
    raise

_HAS_QTMULTIMEDIA = False
_HAS_QTPERMISSION = False
try:
    from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

    _HAS_QTMULTIMEDIA = True
except Exception:
    QAudioFormat = None  # type: ignore
    QAudioSource = None  # type: ignore
    QMediaDevices = None  # type: ignore

# Qt 6.5+ permission API for macOS microphone access
try:
    from PyQt6.QtCore import QMicrophonePermission, QPermission

    _HAS_QTPERMISSION = True
except ImportError as e:
    LOG.warning("QMicrophonePermission not available: %s", e)
    QPermission = None  # type: ignore
    QMicrophonePermission = None  # type: ignore

_HAS_SOUNDDEVICE = False
_sounddevice = None
try:
    import sounddevice as _sounddevice

    _HAS_SOUNDDEVICE = True
except Exception:
    pass


def _qt_audio_input_available() -> bool:
    """Check if Qt multimedia backend can detect audio input devices."""
    if not _HAS_QTMULTIMEDIA or QMediaDevices is None:
        return False
    try:
        return len(QMediaDevices.audioInputs()) > 0
    except Exception:
        return False


def _setup_frozen_qt_env() -> None:
    logger = logging.getLogger("just-talk")
    if not getattr(sys, "frozen", False):
        logger.info("Not frozen, skip frozen Qt env setup")
        return
    base_dir = getattr(sys, "_MEIPASS", "")
    logger.info("Frozen base_dir=%s", base_dir)
    if not base_dir:
        return
    qt_root = os.path.join(base_dir, "PyQt6", "Qt6")
    logger.info("Qt root=%s exists=%s", qt_root, os.path.isdir(qt_root))
    if os.path.isdir(qt_root):
        process_candidates = (
            os.path.join(qt_root, "bin", "QtWebEngineProcess.exe"),
            os.path.join(qt_root, "bin", "Qt6WebEngineProcess.exe"),
        )
        for candidate in process_candidates:
            logger.info("Check QtWebEngineProcess candidate=%s exists=%s", candidate, os.path.exists(candidate))
        for candidate in process_candidates:
            if os.path.exists(candidate):
                os.environ.setdefault("QTWEBENGINEPROCESS_PATH", candidate)
                logger.info(
                    "QTWEBENGINEPROCESS_PATH=%s", os.environ.get("QTWEBENGINEPROCESS_PATH")
                )
                break
        plugin_root = os.path.join(qt_root, "plugins")
        if os.path.isdir(plugin_root):
            os.environ.setdefault("QT_PLUGIN_PATH", plugin_root)
            os.environ.setdefault(
                "QT_QPA_PLATFORM_PLUGIN_PATH", os.path.join(plugin_root, "platforms")
            )
            logger.info("QT_PLUGIN_PATH=%s", os.environ.get("QT_PLUGIN_PATH"))
            logger.info(
                "QT_QPA_PLATFORM_PLUGIN_PATH=%s",
                os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"),
            )
        resources_root = os.path.join(qt_root, "resources")
        if os.path.isdir(resources_root):
            os.environ.setdefault("QTWEBENGINE_RESOURCES_PATH", resources_root)
            logger.info(
                "QTWEBENGINE_RESOURCES_PATH=%s",
                os.environ.get("QTWEBENGINE_RESOURCES_PATH"),
            )
            dictionaries_root = os.path.join(resources_root, "qtwebengine_dictionaries")
            if os.path.isdir(dictionaries_root):
                os.environ.setdefault("QTWEBENGINE_DICTIONARIES_PATH", dictionaries_root)
                logger.info(
                    "QTWEBENGINE_DICTIONARIES_PATH=%s",
                    os.environ.get("QTWEBENGINE_DICTIONARIES_PATH"),
                )
        locales_root = os.path.join(qt_root, "translations", "qtwebengine_locales")
        if os.path.isdir(locales_root):
            os.environ.setdefault("QTWEBENGINE_LOCALES_PATH", locales_root)
            logger.info(
                "QTWEBENGINE_LOCALES_PATH=%s", os.environ.get("QTWEBENGINE_LOCALES_PATH")
            )
    if sys.platform.startswith("win"):
        disable_gpu = os.environ.get("JT_WEBENGINE_DISABLE_GPU", "0") == "1"
        if disable_gpu and "QT_OPENGL" not in os.environ:
            os.environ["QT_OPENGL"] = "software"
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        chromium_log = os.path.join(os.path.dirname(_resolve_log_path()), "webengine.log")
        chromium_log = chromium_log.replace("\\", "/")
        extra_flags = [
            "--enable-logging",
            "--v=1",
            f"--log-file={chromium_log}",
        ]
        if disable_gpu:
            extra_flags += ["--disable-gpu", "--disable-gpu-compositing"]
        if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") == "1":
            extra_flags.append("--no-sandbox")
        current = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
        flags = current.split() if current else []
        if not disable_gpu:
            flags = [f for f in flags if f not in ("--disable-gpu", "--disable-gpu-compositing")]
        for flag in extra_flags:
            if flag not in flags:
                flags.append(flag)
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
        if disable_gpu:
            logger.info("QT_OPENGL=%s", os.environ.get("QT_OPENGL"))
        logger.info("JT_WEBENGINE_DISABLE_GPU=%s", disable_gpu)
        logger.info("QTWEBENGINE_DISABLE_SANDBOX=%s", os.environ.get("QTWEBENGINE_DISABLE_SANDBOX"))
        logger.info("QTWEBENGINE_CHROMIUM_FLAGS=%s", os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"))
        logger.info("QTWEBENGINE chromium log=%s", chromium_log)
        QtCore.QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        if disable_gpu:
            QtCore.QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)


# ---------------- SAUC binary protocol (v1) ----------------
PROTO_VERSION = 0b0001
HEADER_SIZE_4B = 0b0001  # 1 * 4 bytes

SERIALIZATION_NONE = 0b0000
SERIALIZATION_JSON = 0b0001

COMPRESSION_NONE = 0b0000
COMPRESSION_GZIP = 0b0001

MSG_FULL_CLIENT_REQUEST = 0b0001
MSG_AUDIO_ONLY_REQUEST = 0b0010
MSG_FULL_SERVER_RESPONSE = 0b1001
MSG_ERROR_RESPONSE = 0b1111

FLAG_NO_SEQUENCE = 0b0000
FLAG_LAST_NO_SEQUENCE = 0b0010


def _u32be(n: int) -> bytes:
    return struct.pack(">I", n & 0xFFFFFFFF)


def _build_header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    b0 = ((PROTO_VERSION & 0xF) << 4) | (HEADER_SIZE_4B & 0xF)
    b1 = ((message_type & 0xF) << 4) | (flags & 0xF)
    b2 = ((serialization & 0xF) << 4) | (compression & 0xF)
    b3 = 0x00
    return bytes((b0, b1, b2, b3))


def _gzip_if(data: bytes, enable: bool) -> bytes:
    if not enable:
        return data
    return gzip.compress(data)


def _gunzip_if(data: bytes, enable: bool) -> bytes:
    if not enable:
        return data
    return gzip.decompress(data)


def build_full_client_request(payload_json_text: str, use_gzip: bool) -> bytes:
    payload_raw = payload_json_text.encode("utf-8")
    payload = _gzip_if(payload_raw, use_gzip)
    header = _build_header(
        message_type=MSG_FULL_CLIENT_REQUEST,
        flags=FLAG_NO_SEQUENCE,
        serialization=SERIALIZATION_JSON,
        compression=COMPRESSION_GZIP if use_gzip else COMPRESSION_NONE,
    )
    return header + _u32be(len(payload)) + payload


def build_audio_only_request(pcm_bytes: bytes, last: bool, use_gzip: bool) -> bytes:
    payload = _gzip_if(pcm_bytes, use_gzip)
    header = _build_header(
        message_type=MSG_AUDIO_ONLY_REQUEST,
        flags=FLAG_LAST_NO_SEQUENCE if last else FLAG_NO_SEQUENCE,
        serialization=SERIALIZATION_NONE,
        compression=COMPRESSION_GZIP if use_gzip else COMPRESSION_NONE,
    )
    return header + _u32be(len(payload)) + payload


@dataclass(frozen=True)
class ParsedServerMessage:
    kind: str  # "response" | "error" | "unknown"
    message_type: int
    flags: int
    compression: int
    seq: Optional[int] = None
    json_text: Optional[str] = None
    error_code: Optional[int] = None
    error_msg: Optional[str] = None


def parse_server_message(data: bytes) -> ParsedServerMessage:
    if len(data) < 4:
        return ParsedServerMessage(kind="unknown", message_type=-1, flags=0, compression=0)

    b0, b1, b2, _b3 = data[0], data[1], data[2], data[3]
    version = (b0 >> 4) & 0xF
    header_size_4 = b0 & 0xF
    if version != PROTO_VERSION or header_size_4 != HEADER_SIZE_4B:
        return ParsedServerMessage(kind="unknown", message_type=-1, flags=0, compression=0)

    message_type = (b1 >> 4) & 0xF
    flags = b1 & 0xF
    compression = b2 & 0xF
    is_gzip = compression == COMPRESSION_GZIP

    if message_type == MSG_FULL_SERVER_RESPONSE:
        if len(data) < 12:
            return ParsedServerMessage(kind="unknown", message_type=message_type, flags=flags, compression=compression)
        seq = struct.unpack(">i", data[4:8])[0]
        payload_size = struct.unpack(">I", data[8:12])[0]
        payload = data[12 : 12 + payload_size]
        payload = _gunzip_if(payload, is_gzip)
        json_text = payload.decode("utf-8", errors="replace")
        return ParsedServerMessage(
            kind="response",
            message_type=message_type,
            flags=flags,
            compression=compression,
            seq=seq,
            json_text=json_text,
        )

    if message_type == MSG_ERROR_RESPONSE:
        if len(data) < 12:
            return ParsedServerMessage(kind="unknown", message_type=message_type, flags=flags, compression=compression)
        code = struct.unpack(">I", data[4:8])[0]
        msg_size = struct.unpack(">I", data[8:12])[0]
        msg_bytes = data[12 : 12 + msg_size]
        msg = msg_bytes.decode("utf-8", errors="replace")
        return ParsedServerMessage(
            kind="error",
            message_type=message_type,
            flags=flags,
            compression=compression,
            error_code=code,
            error_msg=msg,
        )

    return ParsedServerMessage(kind="unknown", message_type=message_type, flags=flags, compression=compression)


# ---------------- tiny websocket client (stdlib, ws/wss) ----------------
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _WsFrameReader:
    def __init__(self, initial: bytes = b"") -> None:
        self.buf = bytearray(initial)
        self._frag_opcode: Optional[int] = None
        self._frag_parts: List[bytes] = []

    def feed(self, data: bytes) -> None:
        if data:
            self.buf.extend(data)

    def _try_pop_frame_once(self) -> Optional[Tuple[int, bytes]]:
        if len(self.buf) < 2:
            return None
        b1 = self.buf[0]
        b2 = self.buf[1]
        fin = (b1 & 0x80) != 0
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        ln = b2 & 0x7F
        idx = 2

        if ln == 126:
            if len(self.buf) < idx + 2:
                return None
            ln = int.from_bytes(self.buf[idx : idx + 2], "big")
            idx += 2
        elif ln == 127:
            if len(self.buf) < idx + 8:
                return None
            ln = int.from_bytes(self.buf[idx : idx + 8], "big")
            idx += 8

        mask_key = b""
        if masked:
            if len(self.buf) < idx + 4:
                return None
            mask_key = bytes(self.buf[idx : idx + 4])
            idx += 4

        if len(self.buf) < idx + ln:
            return None

        payload = bytes(self.buf[idx : idx + ln])
        del self.buf[: idx + ln]

        if masked and payload:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if opcode == 0x0:  # continuation
            if self._frag_opcode is None:
                raise ConnectionError("unexpected continuation frame")
            self._frag_parts.append(payload)
            if fin:
                op = self._frag_opcode
                out = b"".join(self._frag_parts)
                self._frag_opcode = None
                self._frag_parts = []
                return op, out
            return None

        if not fin:
            self._frag_opcode = opcode
            self._frag_parts = [payload]
            return None

        return opcode, payload

    def pop_all(self) -> List[Tuple[int, bytes]]:
        out: List[Tuple[int, bytes]] = []
        while True:
            item = self._try_pop_frame_once()
            if item is None:
                break
            out.append(item)
        return out


def _ws_accept_key(sec_ws_key: str) -> str:
    sha1 = hashlib.sha1((sec_ws_key + WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(sha1).decode("ascii")


def _ws_build_frame(payload: bytes, opcode: int, mask: bool) -> bytes:
    fin_opcode = 0x80 | (opcode & 0x0F)
    out = bytearray([fin_opcode])

    n = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if n < 126:
        out.append(mask_bit | n)
    elif n < (1 << 16):
        out.append(mask_bit | 126)
        out.extend(n.to_bytes(2, "big"))
    else:
        out.append(mask_bit | 127)
        out.extend(n.to_bytes(8, "big"))

    if mask:
        key = os.urandom(4)
        out.extend(key)
        masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        out.extend(masked)
    else:
        out.extend(payload)

    return bytes(out)


def _ws_connect(url: str, headers: dict) -> Tuple[socket.socket, _WsFrameReader]:
    u = urlparse(url)
    if u.scheme not in ("ws", "wss"):
        raise ValueError(f"unsupported scheme: {u.scheme}")
    host = u.hostname
    if not host:
        raise ValueError("missing host")
    port = u.port or (443 if u.scheme == "wss" else 80)
    path = u.path or "/"
    if u.query:
        path = path + "?" + u.query

    raw = socket.create_connection((host, port), timeout=10)
    sock: socket.socket
    if u.scheme == "wss":
        # Use certifi for CA certificates (needed for PyInstaller on macOS)
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(raw, server_hostname=host)
    else:
        sock = raw

    sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
    req_headers = {
        "Host": host,
        "Upgrade": "websocket",
        "Connection": "Upgrade",
        "Sec-WebSocket-Key": sec_key,
        "Sec-WebSocket-Version": "13",
        **{k: v for k, v in headers.items() if v},
    }
    req = [f"GET {path} HTTP/1.1"]
    req += [f"{k}: {v}" for k, v in req_headers.items()]
    req.append("\r\n")
    sock.sendall(("\r\n".join(req)).encode("utf-8"))

    sock.settimeout(10)
    buf = bytearray()
    marker = b"\r\n\r\n"
    while marker not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("handshake failed: socket closed")
        buf.extend(chunk)
        if len(buf) > 65536:
            raise ConnectionError("handshake failed: header too large")

    idx = buf.index(marker) + len(marker)
    header_bytes = bytes(buf[:idx])
    leftover = bytes(buf[idx:])

    header_text = header_bytes.decode("latin-1", errors="replace")
    lines = header_text.split("\r\n")
    if not lines or " " not in lines[0]:
        raise ConnectionError("bad handshake response")
    _ver, status, *_ = lines[0].split(" ")
    if int(status) != 101:
        raise ConnectionError(f"handshake failed: {lines[0]}")

    resp_headers = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        resp_headers[k.strip().lower()] = v.strip()

    accept = resp_headers.get("sec-websocket-accept")
    if not accept or accept.strip() != _ws_accept_key(sec_key):
        raise ConnectionError("Sec-WebSocket-Accept mismatch")

    sock.settimeout(0.05)
    return sock, _WsFrameReader(leftover)


class WsClientThread(QtCore.QThread):
    connected = QtCore.pyqtSignal()
    disconnected = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)
    textMessageReceived = QtCore.pyqtSignal(str)
    binaryMessageReceived = QtCore.pyqtSignal(bytes)

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._cmd_q: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[_WsFrameReader] = None
        self._connected_emitted = False

    def connect_url(self, url: str, headers: dict) -> None:
        self._cmd_q.put(("connect", url, headers))

    def send_binary(self, data: bytes) -> None:
        self._cmd_q.put(("send_bin", data))

    def close_ws(self) -> None:
        self._cmd_q.put(("close",))

    def stop(self) -> None:
        self._stop.set()
        self._cmd_q.put(("close",))

    def _close_socket(self) -> None:
        try:
            if self._sock is not None:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self._sock.close()
        finally:
            self._sock = None
            self._reader = None

    def run(self) -> None:
        while not self._stop.is_set():
            if self._sock is None:
                try:
                    cmd = self._cmd_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if cmd[0] == "connect":
                    _tag, url, headers = cmd
                    try:
                        sock, reader = _ws_connect(url, headers)
                        self._sock = sock
                        self._reader = reader
                        self._connected_emitted = True
                        self.connected.emit()
                    except Exception as e:
                        self._close_socket()
                        self.error.emit(str(e))
                continue

            # Drain outgoing
            while True:
                try:
                    cmd = self._cmd_q.get_nowait()
                except queue.Empty:
                    break

                if cmd[0] == "send_bin" and self._sock is not None:
                    frame = _ws_build_frame(cmd[1], opcode=0x2, mask=True)
                    try:
                        self._sock.sendall(frame)
                    except Exception as e:
                        self.error.emit(str(e))
                        self._close_socket()
                        if self._connected_emitted:
                            self.disconnected.emit()
                            self._connected_emitted = False
                        break
                elif cmd[0] == "close":
                    try:
                        if self._sock is not None:
                            self._sock.sendall(_ws_build_frame(b"", opcode=0x8, mask=True))
                    except Exception:
                        pass
                    self._close_socket()
                    if self._connected_emitted:
                        self.disconnected.emit()
                        self._connected_emitted = False
                    break
                elif cmd[0] == "connect":
                    try:
                        if self._sock is not None:
                            self._sock.sendall(_ws_build_frame(b"", opcode=0x8, mask=True))
                    except Exception:
                        pass
                    self._close_socket()
                    if self._connected_emitted:
                        self.disconnected.emit()
                        self._connected_emitted = False
                    self._cmd_q.put(cmd)
                    break

            if self._sock is None or self._reader is None:
                continue

            # Read incoming
            try:
                data = self._sock.recv(4096)
                if not data:
                    raise ConnectionError("socket closed")
                self._reader.feed(data)
            except socket.timeout:
                continue
            except Exception as e:
                self.error.emit(str(e))
                self._close_socket()
                if self._connected_emitted:
                    self.disconnected.emit()
                    self._connected_emitted = False
                continue

            for opcode, payload in self._reader.pop_all():
                if opcode == 0x8:  # close
                    self._close_socket()
                    if self._connected_emitted:
                        self.disconnected.emit()
                        self._connected_emitted = False
                    break
                if opcode == 0x9:  # ping -> pong
                    try:
                        if self._sock is not None:
                            self._sock.sendall(_ws_build_frame(payload, opcode=0xA, mask=True))
                    except Exception:
                        pass
                    continue
                if opcode == 0xA:
                    continue
                if opcode == 0x1:
                    self.textMessageReceived.emit(payload.decode("utf-8", errors="replace"))
                elif opcode == 0x2:
                    self.binaryMessageReceived.emit(payload)

        self._close_socket()


# ---------------- audio helpers ----------------
def _pack_int16le(samples: List[int]) -> bytes:
    a = array("h", samples)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


class StreamingResamplerInt16:
    def __init__(self, in_rate: int, out_rate: int) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self.step = self.in_rate / self.out_rate if self.out_rate else 1.0
        self.pos = 0.0
        self.tail: List[int] = []

    def process(self, input_samples: List[int]) -> List[int]:
        if not input_samples:
            return []
        if self.in_rate == self.out_rate:
            return input_samples

        merged = self.tail + input_samples
        out: List[int] = []
        while True:
            i0 = int(self.pos)
            i1 = i0 + 1
            if i1 >= len(merged):
                break
            frac = self.pos - i0
            v = merged[i0] * (1.0 - frac) + merged[i1] * frac
            out.append(int(max(-32768, min(32767, round(v)))))
            self.pos += self.step

        base = int(self.pos)
        keep_from = max(0, base - 1)
        self.tail = merged[keep_from:]
        self.pos -= keep_from
        return out


def mic_bytes_to_pcm16le_16k_mono(
    raw: bytes,
    in_rate: int,
    in_channels: int,
    resampler: Optional[StreamingResamplerInt16],
) -> bytes:
    if not raw:
        return b""
    raw = raw[: (len(raw) // 2) * 2]
    if not raw:
        return b""

    a = array("h")
    a.frombytes(raw)
    if sys.byteorder != "little":
        a.byteswap()
    samples = a.tolist()

    if in_channels > 1:
        mono: List[int] = []
        for i in range(0, len(samples), in_channels):
            frame = samples[i : i + in_channels]
            if not frame:
                continue
            mono.append(int(sum(frame) / len(frame)))
        samples = mono

    if int(in_rate) != 16000:
        if resampler is None:
            resampler = StreamingResamplerInt16(in_rate=int(in_rate), out_rate=16000)
        samples = resampler.process(samples)

    return _pack_int16le(samples)


# ---------------- app ----------------
def claude_stylesheet() -> str:
    return """
    QMainWindow { background: #f0f2f5; }
    QWidget { color: #333333; font-size: 13px; }
    QFrame#appContainer { background: #ffffff; border-radius: 0px; }
    QFrame#sidebar { background: #f5f5f5; border-right: 1px solid #e8e8e8; }
    QLabel#logo { color: #ff9d00; font-size: 18px; font-weight: 700; }
    QPushButton#navItem { text-align: left; padding: 10px 14px; border: none; background: transparent; color: #333333; }
    QPushButton#navItem:hover { background: #ededed; border-radius: 10px; }
    QPushButton#navItem[active="true"] { background: #e6e6e6; border-radius: 0 16px 16px 0; margin-right: 8px; font-weight: 600; }
    QFrame#settingsCard { background: #f9f9f9; border-radius: 12px; border: 1px solid #ececec; }
    QLabel#sectionTitle { color: #777777; font-size: 11px; letter-spacing: 1px; }
    QLabel#mutedLabel { color: #666666; }
    QLabel#statusLabel { color: #666666; }
    QLineEdit, QComboBox { background: #ffffff; border: 1px solid #dcdcdc; border-radius: 8px; padding: 6px 8px; min-height: 22px; }
    QLineEdit:focus, QComboBox:focus { border: 1px solid #ff9d00; }
    QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #fff2d6; border: 1px solid #dcdcdc; }
    QPushButton { background: #ffffff; border: 1px solid #dcdcdc; border-radius: 6px; padding: 6px 10px; }
    QPushButton:hover { background: #f5f5f5; }
    QPushButton#ghostButton { background: #ffffff; border: 1px solid #e0e0e0; color: #666666; }
    QPushButton#clearButton { background: #ffffff; border: 1px solid #e8e8e8; color: #666666; }
    QPushButton#primary { background: #ff9d00; color: #111111; border: 1px solid #ff9d00; border-radius: 10px; padding: 10px 14px; }
    QPushButton#primary:hover { background: #ffae2f; border: 1px solid #ffae2f; }
    QPushButton#primary:pressed { background: #f08f00; border: 1px solid #f08f00; }
    QPushButton#danger { background: #ffe3e1; border: 1px solid #f3b3af; color: #7f1d1d; border-radius: 10px; padding: 10px 14px; }
    QPushButton#danger:hover { background: #ffd4d1; border: 1px solid #f1a6a1; }
    QPushButton:disabled { background: #f3f3f3; color: #9a9a9a; border: 1px solid #e2e2e2; }
    QFrame#statBox { background: #ffffff; border: 1px solid #e8e8e8; border-radius: 8px; }
    QLabel#statLabel { color: #555555; font-size: 13px; }
    QLabel#historyTitle { font-size: 20px; font-weight: 600; color: #333333; }
    QLabel#dateLabel { color: #999999; font-size: 11px; }
    QScrollArea { border: none; }
    QScrollArea QWidget { background: transparent; }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 6px 2px 6px 2px; }
    QScrollBar::handle:vertical { background: #d1d5db; border-radius: 5px; min-height: 26px; }
    QScrollBar::handle:vertical:hover { background: #b7bcc4; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QFrame#historyItem { background: #ffffff; border-bottom: 1px solid #e8e8e8; border-radius: 0px; }
    QFrame#historyItem[alt="true"] { background: #f6f6f6; }
    QFrame#historyItem[partial="true"] { background: #faf6ed; }
    QLabel#historyTime { color: #999999; font-size: 11px; min-width: 70px; padding-left: 8px; }
    QPlainTextEdit#historyItemText { background: transparent; border: none; padding: 6px 8px; color: #333333; }
    QPlainTextEdit#historyItemText[partial="true"] { color: #999999; }
    QPlainTextEdit#historyItemText:focus { background: #fff7e6; border-radius: 0px; }
    QFrame#divider { background: #e8e8e8; max-height: 1px; }
    """


class StatusDot(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._base_color = QtGui.QColor("#6b7280")  # idle gray
        self._pulse = False
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_state(self, color_hex: str, pulse: bool) -> None:
        self._base_color = QtGui.QColor(color_hex)
        self._pulse = pulse
        self._phase = 0.0
        if pulse:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase += 0.08
        if self._phase > (math.pi * 2):
            self._phase -= (math.pi * 2)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()

        alpha = 255
        if self._pulse:
            alpha = int(255 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._phase))))

        c = QtGui.QColor(self._base_color)
        c.setAlpha(alpha)
        p.setBrush(QtGui.QBrush(c))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 0)))
        p.drawEllipse(rect)


class MicIndicator(QtWidgets.QWidget):
    """
    A small "mic badge" with a pulsing ring when connecting/recording.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._color = QtGui.QColor("#9ca3af")
        self._pulse = False
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_state(self, color_hex: str, pulse: bool) -> None:
        self._color = QtGui.QColor(color_hex)
        self._pulse = pulse
        self._phase = 0.0
        if pulse:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase += 0.08
        if self._phase > (math.pi * 2):
            self._phase -= (math.pi * 2)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        center = rect.center()
        base = QtGui.QColor(self._color)

        ring_alpha = 0
        if self._pulse:
            ring_alpha = int(160 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._phase))))

        ring = QtGui.QColor(base)
        ring.setAlpha(ring_alpha)

        # outer ring
        p.setPen(QtGui.QPen(ring, 2))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(2, 2, -2, -2))

        # inner dot
        fill = QtGui.QColor(base)
        fill.setAlpha(255)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 0)))
        p.setBrush(QtGui.QBrush(fill))
        p.drawEllipse(QtCore.QRectF(center.x() - 4, center.y() - 4, 8, 8))

        # mic glyph (simple)
        mic = QtGui.QColor("#111827")
        mic.setAlpha(185)
        p.setPen(QtGui.QPen(mic, 1.4, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        # body
        p.drawLine(int(center.x()), int(center.y() - 4), int(center.x()), int(center.y() + 3))
        # head arc
        p.drawArc(int(center.x() - 3), int(center.y() - 7), 6, 6, 0 * 16, 180 * 16)
        # stand
        p.drawLine(int(center.x() - 3), int(center.y() + 4), int(center.x() + 3), int(center.y() + 4))


class ToggleSwitch(QtWidgets.QAbstractButton):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtGui.QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedSize(40, 20)
        self._offset = 1.0 if self.isChecked() else 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(40, 20)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _set_offset(self, value: float) -> None:
        self._offset = max(0.0, min(1.0, float(value)))
        self.update()

    def _get_offset(self) -> float:
        return self._offset

    offset = QtCore.pyqtProperty(float, fget=_get_offset, fset=_set_offset)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        radius = rect.height() / 2

        if self.isEnabled():
            bg = QtGui.QColor("#ff9d00" if self._offset >= 0.5 else "#cccccc")
        else:
            bg = QtGui.QColor("#e0e0e0")

        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QBrush(bg))
        p.drawRoundedRect(rect, radius, radius)

        knob_d = rect.height() - 4
        knob_x = 2 + (rect.width() - knob_d - 4) * self._offset
        knob_rect = QtCore.QRectF(knob_x, 2, knob_d, knob_d)
        p.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        p.drawEllipse(knob_rect)


class HistoryItemWidget(QtWidgets.QFrame):
    def __init__(self, timestamp: str, text: str, partial: bool = False, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyItem")
        self._compact = False

        self._layout = QtWidgets.QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(0)
        self._layout.setVerticalSpacing(0)

        self.time_label = QtWidgets.QLabel()
        self.time_label.setObjectName("historyTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.set_timestamp(timestamp)

        self.text_edit = QtWidgets.QPlainTextEdit()
        self.text_edit.setObjectName("historyItemText")
        self.text_edit.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        self.text_edit.setPlainText(text)
        self.text_edit.document().setDocumentMargin(0)
        self.text_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum
        )
        self.text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setTabChangesFocus(True)
        self.text_edit.textChanged.connect(self._sync_height)
        self._sync_height()

        self._apply_layout()
        self.set_partial(partial)

        for target in (self, self.time_label, self.text_edit):
            target.installEventFilter(self)

    def set_partial(self, partial: bool) -> None:
        self.setProperty("partial", partial)
        self.text_edit.setProperty("partial", partial)
        self.text_edit.style().unpolish(self.text_edit)
        self.text_edit.style().polish(self.text_edit)
        self.text_edit.update()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_compact(self, compact: bool) -> None:
        if self._compact == compact:
            return
        self._compact = compact
        self._apply_layout()

    def set_timestamp(self, timestamp: str) -> None:
        text = timestamp or ""
        parts = text.split(" ", 1)
        if len(parts) == 2:
            date_part, time_part = parts
            self.time_label.setText(time_part)
            self.time_label.setToolTip(text)
        else:
            self.time_label.setText(text)
            self.time_label.setToolTip("")

    def set_text(self, text: str) -> None:
        self.text_edit.setPlainText(text)
        self._sync_height()

    def text(self) -> str:
        return self.text_edit.toPlainText()

    def _sync_height(self) -> None:
        doc_height = int(self.text_edit.document().size().height())
        height = max(32, min(140, doc_height + 8))
        self.text_edit.setFixedHeight(height)

    def _apply_layout(self) -> None:
        self._layout.removeWidget(self.time_label)
        self._layout.removeWidget(self.text_edit)

        if self._compact:
            self.time_label.setFixedWidth(0)
            self.time_label.setMinimumWidth(0)
            self.time_label.setMaximumWidth(16777215)
            self._layout.addWidget(self.time_label, 0, 0, 1, 2, Qt.AlignmentFlag.AlignVCenter)
            self._layout.addWidget(self.text_edit, 1, 0, 1, 2)
            self._layout.setColumnStretch(0, 1)
            self._layout.setColumnStretch(1, 1)
        else:
            self.time_label.setFixedWidth(72)
            self._layout.addWidget(self.time_label, 0, 0, Qt.AlignmentFlag.AlignVCenter)
            self._layout.addWidget(self.text_edit, 0, 1)
            self._layout.setColumnStretch(1, 1)

    def set_alt(self, alt: bool) -> None:
        self.setProperty("alt", alt)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class HistoryModel(QtCore.QAbstractListModel):
    TimestampRole = QtCore.Qt.ItemDataRole.UserRole + 1
    TextRole = QtCore.Qt.ItemDataRole.UserRole + 2
    PartialRole = QtCore.Qt.ItemDataRole.UserRole + 3

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._items: List[dict] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> Optional[object]:
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        item = self._items[row]
        if role == self.TimestampRole:
            return item.get("timestamp", "")
        if role == self.TextRole:
            return item.get("text", "")
        if role == self.PartialRole:
            return item.get("partial", False)
        return None

    def roleNames(self) -> dict:  # noqa: N802
        return {
            self.TimestampRole: b"timestamp",
            self.TextRole: b"text",
            self.PartialRole: b"partial",
        }

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        return (
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEditable
        )

    def setData(  # noqa: N802
        self, index: QtCore.QModelIndex, value: object, role: int = QtCore.Qt.ItemDataRole.EditRole
    ) -> bool:
        if not index.isValid():
            return False
        row = index.row()
        if row < 0 or row >= len(self._items):
            return False
        if role in (self.TextRole, QtCore.Qt.ItemDataRole.EditRole):
            new_text = str(value)
            if self._items[row].get("text", "") != new_text:
                self._items[row]["text"] = new_text
                self.dataChanged.emit(index, index, [self.TextRole])
            return True
        return False

    def add_item(self, timestamp: str, text: str, partial: bool) -> int:
        row = 0
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._items.insert(row, {"timestamp": timestamp, "text": text, "partial": partial})
        self.endInsertRows()
        return row

    def update_item(
        self,
        row: int,
        text: Optional[str] = None,
        partial: Optional[bool] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        roles: List[int] = []
        if text is not None and item.get("text") != text:
            item["text"] = text
            roles.append(self.TextRole)
        if partial is not None and item.get("partial") != partial:
            item["partial"] = partial
            roles.append(self.PartialRole)
        if timestamp is not None and item.get("timestamp") != timestamp:
            item["timestamp"] = timestamp
            roles.append(self.TimestampRole)
        if roles:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, roles)

    def remove_row(self, row: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        self._items.pop(row)
        self.endRemoveRows()

    def clear(self) -> None:
        if not self._items:
            return
        self.beginResetModel()
        self._items = []
        self.endResetModel()

    def item_at(self, row: int) -> Optional[dict]:
        if row < 0 or row >= len(self._items):
            return None
        return dict(self._items[row])

    def as_list(self) -> List[dict]:
        return [dict(item) for item in self._items]


class AsrController(QtCore.QObject):
    statusTextChanged = QtCore.pyqtSignal()
    modeChanged = QtCore.pyqtSignal()
    appIdChanged = QtCore.pyqtSignal()
    accessTokenChanged = QtCore.pyqtSignal()
    useGzipChanged = QtCore.pyqtSignal()
    startMinimizedChanged = QtCore.pyqtSignal()
    autoSubmitChanged = QtCore.pyqtSignal()
    autoSubmitModeChanged = QtCore.pyqtSignal()
    autoSubmitPasteKeysChanged = QtCore.pyqtSignal()
    autoSubmitStatusChanged = QtCore.pyqtSignal()
    enablePuncChanged = QtCore.pyqtSignal()
    enableDdcChanged = QtCore.pyqtSignal()
    hotwordsChanged = QtCore.pyqtSignal()
    hotkeysEnabledChanged = QtCore.pyqtSignal()
    mouseModeEnabledChanged = QtCore.pyqtSignal()
    primaryHotkeyTextChanged = QtCore.pyqtSignal()
    primaryHotkeyModeChanged = QtCore.pyqtSignal()
    primaryHotkeyEnabledChanged = QtCore.pyqtSignal()
    freehandHotkeyTextChanged = QtCore.pyqtSignal()
    freehandHotkeyModeChanged = QtCore.pyqtSignal()
    freehandHotkeyEnabledChanged = QtCore.pyqtSignal()
    mouseHotkeyModeChanged = QtCore.pyqtSignal()
    tutorialHoldTextChanged = QtCore.pyqtSignal()
    tutorialToggleTextChanged = QtCore.pyqtSignal()
    tutorialMouseTextChanged = QtCore.pyqtSignal()
    isConnectedChanged = QtCore.pyqtSignal()
    isConnectingChanged = QtCore.pyqtSignal()
    isSendingChanged = QtCore.pyqtSignal()
    statsChanged = QtCore.pyqtSignal()
    hotkeyCaptured = QtCore.pyqtSignal(str, str)
    historyReset = QtCore.pyqtSignal(str)  # JSON string
    historyRowInserted = QtCore.pyqtSignal(int, str)  # JSON string
    historyRowUpdated = QtCore.pyqtSignal(int, str)  # JSON string
    historyRowRemoved = QtCore.pyqtSignal(int)

    RESOURCE_ID_DEFAULT = "volc.seedasr.sauc.duration"
    CHUNK_MS_DEFAULT = 200
    DEFAULT_APP_ID = "9106283284"
    DEFAULT_ACCESS_TOKEN = "jGEzfiNFgDgnAGpAp-Kc8skAcBswUjXZ"
    DEFAULT_RECORDING_LIMIT_S = 60
    SETTINGS_ORG = "JustTalk"
    SETTINGS_APP = "AsrApp"

    def __init__(self) -> None:
        super().__init__()
        self.ws = WsClientThread(self)
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.error.connect(self._on_ws_error)
        self.ws.binaryMessageReceived.connect(self._on_ws_binary)
        self.ws.start()

        self._connected = False
        self._connecting = False
        self._sending = False
        self._use_gzip = False
        self._connect_id = ""
        self._pending_close_after_last = False
        self._pending_close_timer = QtCore.QTimer(self)
        self._pending_close_timer.setSingleShot(True)
        self._pending_close_timer.timeout.connect(self._force_close)
        self._default_limit_timer = QtCore.QTimer(self)
        self._default_limit_timer.setSingleShot(True)
        self._default_limit_timer.timeout.connect(self._on_default_limit_timeout)

        self._audio_source: Optional["QAudioSource"] = None
        self._audio_io: Optional[QtCore.QIODevice] = None
        self._mic_buffer = bytearray()
        self._mic_in_rate = 16000
        self._mic_in_channels = 1
        self._mic_resampler: Optional[StreamingResamplerInt16] = None
        self._audio_sent = False  # 追踪是否已发送音频数据
        # sounddevice backend (used on Linux when Qt backend unavailable)
        self._sd_stream = None
        self._use_sounddevice = False

        self._committed_text = ""
        self._last_committed_end_time = -1
        self._last_full_text = ""
        self._user_cancelled = False
        self._session_partial = ""
        self._current_row: Optional[int] = None
        self._history_model = HistoryModel(self)

        self._mode = "nostream"
        self._app_id = self.DEFAULT_APP_ID
        self._access_token = self.DEFAULT_ACCESS_TOKEN
        self._start_minimized = False
        self._auto_submit = False
        self._auto_submit_mode = "type"
        self._auto_submit_status = ""
        self._auto_submit_stream_last = ""
        self._auto_submit_stream_sent_text = ""
        self._auto_submit_stream_pending = ""
        self._auto_submit_stream_timer = QtCore.QTimer(self)
        self._auto_submit_stream_timer.setSingleShot(True)
        self._auto_submit_stream_timer.setInterval(0)
        self._auto_submit_stream_timer.timeout.connect(self._flush_auto_submit_stream)
        self._auto_submit_queue: "queue.Queue[Tuple[List[str], str]]" = queue.Queue()
        self._auto_submit_worker: Optional[threading.Thread] = None
        self._auto_submit_worker_lock = threading.Lock()
        self._auto_submit_paste_keys = "ctrl+v"
        self._enable_punc = True
        self._enable_ddc = False
        self._hotwords = ""
        self._status_text = "未连接"
        self._hotkeys_enabled = True
        self._mouse_mode_enabled = True
        self._primary_hotkey_text = ""
        self._primary_hotkey_mode = "hold"
        self._primary_hotkey_enabled = True
        self._freehand_hotkey_text = ""
        self._freehand_hotkey_mode = "toggle"
        self._freehand_hotkey_enabled = True
        self._mouse_hotkey_mode = "hold"
        self._tutorial_hold_text = ""
        self._tutorial_toggle_text = ""
        self._tutorial_mouse_text = ""
        self._is_linux = sys.platform.startswith("linux")
        self._is_windows = sys.platform.startswith("win")
        self._is_mac = sys.platform == "darwin"
        if self._is_mac:
            self._auto_submit_paste_keys = "cmd+v"
        self._xdotool_path = shutil.which("xdotool") if self._is_linux else None
        self._wtype_path = shutil.which("wtype") if self._is_linux else None
        self._session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
        self._is_wayland = self._session_type == "wayland"

        self._session_started_at: Optional[float] = None
        self._session_elapsed_s = 0.0
        self._stats_total_seconds = 0.0
        self._stats_total_chars = 0
        self._stats_minutes = 0
        self._stats_chars = 0
        self._stats_speed = 0
        self._stats_last_speed = 0
        self._stats_duration_text = "0分00秒"
        self._stats_timer = QtCore.QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._update_stats)
        self._capture_target: Optional[str] = None
        self._indicator_mode: str = "hold"
        self._session_mode: Optional[str] = None
        self._hotkeys_suspend_count = 0
        self._escape_listener: Optional[object] = None

        try:
            from recording_indicator import RecordingIndicatorManager

            self.recording_indicator = RecordingIndicatorManager(self)
            self.recording_indicator.cancel_requested.connect(self._on_indicator_cancel)
            self.recording_indicator.confirm_requested.connect(self._on_indicator_confirm)
        except ImportError:
            self.recording_indicator = None

        try:
            from hotkey.manager import HotkeyManager
            from hotkey.persistence import ConfigManager

            self.hotkey_manager = HotkeyManager(self)
            self.hotkey_manager.start_recording_requested.connect(self._on_hotkey_start_recording)
            self.hotkey_manager.stop_recording_requested.connect(self.stop_recognition)
            self.hotkey_manager.snippet_triggered.connect(self._on_snippet_triggered)
            self.hotkey_manager.error_occurred.connect(self._on_hotkey_error)

            config = ConfigManager.load_config()
            self.hotkey_manager.update_config(config)
            self.hotkey_manager.start_listening()
            self._hotkeys_enabled = True
            mouse_cfg = config.mouse_hotkeys.get("middle_button")
            self._mouse_mode_enabled = bool(mouse_cfg and mouse_cfg.enabled)
            self._sync_hotkey_config(config)
        except ImportError:
            self.hotkey_manager = None
            self._hotkeys_enabled = False
            self._mouse_mode_enabled = False
            self._sync_hotkey_config(None)

        self._load_connection_config()
        self._load_personalization_config()
        self._refresh_auto_submit_status()
        self._load_stats()
        self._update_status_text()
        self._update_stats()

    @QtCore.pyqtProperty(str, notify=statusTextChanged)
    def statusText(self) -> str:  # noqa: N802
        return self._status_text

    @QtCore.pyqtProperty(str, notify=modeChanged)
    def mode(self) -> str:  # noqa: N802
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if self._connected or self._sending:
            self.modeChanged.emit()
            return
        if value and value != self._mode:
            self._mode = value
            self.modeChanged.emit()
            self._update_tutorial_texts()
            self._save_connection_config()

    @QtCore.pyqtProperty(str, notify=appIdChanged)
    def appId(self) -> str:  # noqa: N802
        return self._app_id

    @appId.setter
    def appId(self, value: str) -> None:
        if value != self._app_id:
            self._app_id = value
            self.appIdChanged.emit()
            self._save_connection_config()

    @QtCore.pyqtProperty(str, notify=accessTokenChanged)
    def accessToken(self) -> str:  # noqa: N802
        return self._access_token

    @accessToken.setter
    def accessToken(self, value: str) -> None:
        if value != self._access_token:
            self._access_token = value
            self.accessTokenChanged.emit()
            self._save_connection_config()

    @QtCore.pyqtProperty(bool, notify=useGzipChanged)
    def useGzip(self) -> bool:  # noqa: N802
        return self._use_gzip

    @useGzip.setter
    def useGzip(self, value: bool) -> None:
        if value != self._use_gzip:
            self._use_gzip = value
            self.useGzipChanged.emit()
            self._save_connection_config()

    @QtCore.pyqtProperty(bool, notify=autoSubmitChanged)
    def autoSubmit(self) -> bool:  # noqa: N802
        return self._auto_submit

    @autoSubmit.setter
    def autoSubmit(self, value: bool) -> None:
        value = bool(value)
        if value != self._auto_submit:
            self._auto_submit = value
            self.autoSubmitChanged.emit()
            self._save_personalization_config()
            self._refresh_auto_submit_status()

    @QtCore.pyqtProperty(str, notify=autoSubmitModeChanged)
    def autoSubmitMode(self) -> str:  # noqa: N802
        return self._auto_submit_mode

    @autoSubmitMode.setter
    def autoSubmitMode(self, value: str) -> None:
        value = (value or "").strip().lower()
        if value == "auto":
            value = "type"
        if value not in ("type", "paste"):
            return
        if value != self._auto_submit_mode:
            self._auto_submit_mode = value
            self.autoSubmitModeChanged.emit()
            self._save_personalization_config()
            self._refresh_auto_submit_status()

    @QtCore.pyqtProperty(str, notify=autoSubmitPasteKeysChanged)
    def autoSubmitPasteKeys(self) -> str:  # noqa: N802
        return self._auto_submit_paste_keys

    @autoSubmitPasteKeys.setter
    def autoSubmitPasteKeys(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            value = self._default_paste_keys()
        if value != self._auto_submit_paste_keys:
            self._auto_submit_paste_keys = value
            self.autoSubmitPasteKeysChanged.emit()
            self._save_personalization_config()

    @QtCore.pyqtProperty(str, notify=autoSubmitStatusChanged)
    def autoSubmitStatus(self) -> str:  # noqa: N802
        return self._auto_submit_status

    @QtCore.pyqtProperty(bool, notify=startMinimizedChanged)
    def startMinimized(self) -> bool:  # noqa: N802
        return self._start_minimized

    @startMinimized.setter
    def startMinimized(self, value: bool) -> None:
        value = bool(value)
        if value != self._start_minimized:
            self._start_minimized = value
            self.startMinimizedChanged.emit()
            self._save_personalization_config()

    @QtCore.pyqtProperty(bool, notify=enablePuncChanged)
    def enablePunc(self) -> bool:  # noqa: N802
        return self._enable_punc

    @enablePunc.setter
    def enablePunc(self, value: bool) -> None:
        value = bool(value)
        if value != self._enable_punc:
            self._enable_punc = value
            self.enablePuncChanged.emit()
            self._save_personalization_config()

    @QtCore.pyqtProperty(bool, notify=enableDdcChanged)
    def enableDdc(self) -> bool:  # noqa: N802
        return self._enable_ddc

    @enableDdc.setter
    def enableDdc(self, value: bool) -> None:
        value = bool(value)
        if value != self._enable_ddc:
            self._enable_ddc = value
            self.enableDdcChanged.emit()
            self._save_personalization_config()

    @QtCore.pyqtProperty(str, notify=hotwordsChanged)
    def hotwords(self) -> str:  # noqa: N802
        return self._hotwords

    @hotwords.setter
    def hotwords(self, value: str) -> None:
        value = value or ""
        if value != self._hotwords:
            self._hotwords = value
            self.hotwordsChanged.emit()
            self._save_personalization_config()

    @QtCore.pyqtProperty(bool, notify=hotkeysEnabledChanged)
    def hotkeysEnabled(self) -> bool:  # noqa: N802
        return self._hotkeys_enabled

    @hotkeysEnabled.setter
    def hotkeysEnabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._hotkeys_enabled:
            return
        self._hotkeys_enabled = value
        self.hotkeysEnabledChanged.emit()
        if self.hotkey_manager:
            self.hotkey_manager.set_enabled(value)
        self._update_tutorial_texts()

    @QtCore.pyqtProperty(bool, notify=mouseModeEnabledChanged)
    def mouseModeEnabled(self) -> bool:  # noqa: N802
        return self._mouse_mode_enabled

    @mouseModeEnabled.setter
    def mouseModeEnabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._mouse_mode_enabled:
            return
        self._mouse_mode_enabled = value
        self.mouseModeEnabledChanged.emit()
        self._apply_mouse_mode(value)
        self._update_tutorial_texts()

    @QtCore.pyqtProperty(str, notify=primaryHotkeyTextChanged)
    def primaryHotkeyText(self) -> str:  # noqa: N802
        return self._primary_hotkey_text

    @primaryHotkeyText.setter
    def primaryHotkeyText(self, value: str) -> None:
        keys = self._parse_keys_text(value)
        self._update_keyboard_hotkey("primary", keys=keys)

    @QtCore.pyqtProperty(str, notify=primaryHotkeyModeChanged)
    def primaryHotkeyMode(self) -> str:  # noqa: N802
        return "hold"  # 主热键固定为按住模式

    @QtCore.pyqtProperty(bool, notify=primaryHotkeyEnabledChanged)
    def primaryHotkeyEnabled(self) -> bool:  # noqa: N802
        return self._primary_hotkey_enabled

    @primaryHotkeyEnabled.setter
    def primaryHotkeyEnabled(self, value: bool) -> None:
        self._update_keyboard_hotkey("primary", enabled=bool(value))

    @QtCore.pyqtProperty(str, notify=freehandHotkeyTextChanged)
    def freehandHotkeyText(self) -> str:  # noqa: N802
        return self._freehand_hotkey_text

    @freehandHotkeyText.setter
    def freehandHotkeyText(self, value: str) -> None:
        keys = self._parse_keys_text(value)
        self._update_keyboard_hotkey("freehand", keys=keys)

    @QtCore.pyqtProperty(str, notify=freehandHotkeyModeChanged)
    def freehandHotkeyMode(self) -> str:  # noqa: N802
        return "toggle"  # 自由说固定为切换模式

    @QtCore.pyqtProperty(bool, notify=freehandHotkeyEnabledChanged)
    def freehandHotkeyEnabled(self) -> bool:  # noqa: N802
        return self._freehand_hotkey_enabled

    @freehandHotkeyEnabled.setter
    def freehandHotkeyEnabled(self, value: bool) -> None:
        self._update_keyboard_hotkey("freehand", enabled=bool(value))

    @QtCore.pyqtProperty(str, notify=mouseHotkeyModeChanged)
    def mouseHotkeyMode(self) -> str:  # noqa: N802
        return self._mouse_hotkey_mode

    @mouseHotkeyMode.setter
    def mouseHotkeyMode(self, value: str) -> None:
        if value in ("hold", "toggle"):
            self._update_mouse_hotkey(mode=value)

    @QtCore.pyqtProperty(str, notify=tutorialHoldTextChanged)
    def tutorialHoldText(self) -> str:  # noqa: N802
        return self._tutorial_hold_text

    @QtCore.pyqtProperty(str, notify=tutorialToggleTextChanged)
    def tutorialToggleText(self) -> str:  # noqa: N802
        return self._tutorial_toggle_text

    @QtCore.pyqtProperty(str, notify=tutorialMouseTextChanged)
    def tutorialMouseText(self) -> str:  # noqa: N802
        return self._tutorial_mouse_text

    @QtCore.pyqtProperty(bool, notify=isConnectedChanged)
    def isConnected(self) -> bool:  # noqa: N802
        return self._connected

    @QtCore.pyqtProperty(bool, notify=isConnectingChanged)
    def isConnecting(self) -> bool:  # noqa: N802
        return self._connecting

    @QtCore.pyqtProperty(bool, notify=isSendingChanged)
    def isSending(self) -> bool:  # noqa: N802
        return self._sending

    @QtCore.pyqtProperty(int, notify=statsChanged)
    def statsMinutes(self) -> int:  # noqa: N802
        return self._stats_minutes

    @QtCore.pyqtProperty(int, notify=statsChanged)
    def statsChars(self) -> int:  # noqa: N802
        return self._stats_chars

    @QtCore.pyqtProperty(int, notify=statsChanged)
    def statsSpeed(self) -> int:  # noqa: N802
        return self._stats_speed

    @QtCore.pyqtProperty(str, notify=statsChanged)
    def statsDurationText(self) -> str:  # noqa: N802
        return self._stats_duration_text

    @QtCore.pyqtProperty(QtCore.QAbstractListModel, constant=True)
    def historyModel(self) -> HistoryModel:  # noqa: N802
        return self._history_model

    @QtCore.pyqtSlot(result=str)
    def historySnapshot(self) -> str:  # noqa: N802
        """返回历史记录的 JSON 字符串"""
        return json.dumps(self._history_model.as_list())

    @QtCore.pyqtSlot(int, str)
    def updateHistoryText(self, row: int, text: str) -> None:
        self._history_model.update_item(row, text=text)
        self._emit_history_row(row)

    @QtCore.pyqtSlot(str)
    def startHotkeyCapture(self, target: str) -> None:
        if target not in ("primary", "freehand"):
            return
        if self._capture_target:
            self._capture_target = None
            self._resume_hotkeys()
        self._capture_target = target
        self._suspend_hotkeys()

    @QtCore.pyqtSlot()
    def cancelHotkeyCapture(self) -> None:
        if not self._capture_target:
            return
        self._capture_target = None
        self._resume_hotkeys()

    @QtCore.pyqtSlot()
    def toggleRecognition(self) -> None:
        if self._connecting or self._sending:
            self.stop_recognition()
        else:
            # 使用主热键的模式
            self.start_recognition(indicator_mode=None)

    @QtCore.pyqtSlot()
    def start_recognition(self, indicator_mode: Optional[str] = None) -> None:
        if self._sending or self._connecting:
            return

        if not _HAS_QTMULTIMEDIA:
            QtWidgets.QMessageBox.critical(None, "错误", "未检测到 QtMultimedia，无法使用麦克风。")
            return

        if indicator_mode in ("hold", "toggle"):
            self._indicator_mode = indicator_mode
        else:
            self._indicator_mode = self._primary_hotkey_mode
        self._session_mode = self._indicator_mode

        if not self._connected:
            # 先显示连接中指示器(三个点)
            if self.recording_indicator:
                self.recording_indicator.show_connecting()

            headers = {
                "X-Api-App-Key": self._app_id.strip(),
                "X-Api-Access-Key": self._access_token.strip(),
                "X-Api-Resource-Id": self.RESOURCE_ID_DEFAULT,
                "X-Api-Connect-Id": self._connect_id,
            }
            missing = [k for k, v in headers.items() if not v and k not in ("X-Api-Connect-Id",)]
            if missing:
                QtWidgets.QMessageBox.warning(None, "提示", "缺少鉴权字段：\n" + "\n".join(missing))
                if self.recording_indicator:
                    self.recording_indicator.hide()
                return

            self._begin_new_session()
            self._connect_id = str(uuid.uuid4())
            url = self._mode_to_url()
            headers["X-Api-Connect-Id"] = self._connect_id

            self._connecting = True
            self.isConnectingChanged.emit()
            self._update_status_text()
            self.ws.connect_url(url, headers)
            return

        self._begin_new_session()
        self._show_indicator_mode(self._indicator_mode)
        self._start_mic()

    @QtCore.pyqtSlot()
    def stop_recognition(self) -> None:
        self._reset_hotkey_state()

        # 检查是否应该取消录音（没有发送任何音频数据）
        should_cancel = not self._audio_sent

        if self._connecting and not self._connected:
            self._connecting = False
            self.isConnectingChanged.emit()
            self._finalize_session(cancelled=True)
            self._force_close()
            self._update_status_text()
            if self.recording_indicator:
                self.recording_indicator.hide()
            return

        if self._sending:
            if should_cancel:
                # 没有发送音频数据，直接取消
                if self._current_row is not None:
                    self._history_model.remove_row(self._current_row)
                    self._emit_history_removed(self._current_row)
                    self._current_row = None
                self._force_close()
            else:
                # 有音频数据，正常处理
                self._pending_close_after_last = True
                self._stop_mic_send_last()
                self._pending_close_timer.start(1500)
                if self.recording_indicator:
                    self.recording_indicator.show_processing()
        else:
            self._force_close()
        self._update_status_text()

    @QtCore.pyqtSlot()
    def clearHistory(self) -> None:
        self._history_model.clear()
        self._emit_history_reset()
        self._reset_session()
        self._update_stats()

    @QtCore.pyqtSlot()
    def showHotkeySettings(self) -> None:
        if not self.hotkey_manager:
            QtWidgets.QMessageBox.information(None, "提示", "快捷键模块未加载。请确保已安装pynput: pip install pynput")
            return
        QtWidgets.QMessageBox.information(None, "提示", "快捷键请在页面中直接设置。")

    @QtCore.pyqtSlot(str)
    def copyText(self, text: str) -> None:
        content = (text or "").strip()
        if not content:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(content)

    @QtCore.pyqtSlot()
    def shutdown(self) -> None:
        if hasattr(self, "hotkey_manager") and self.hotkey_manager:
            try:
                self.hotkey_manager.stop_listening()
            except Exception:
                pass

        if hasattr(self, "recording_indicator") and self.recording_indicator:
            try:
                self.recording_indicator.cleanup()
            except Exception:
                pass

        try:
            if self._sending:
                self._stop_mic_no_last()
        except Exception:
            pass
        try:
            self.ws.stop()
            self.ws.wait(1500)
        except Exception:
            pass

    def _apply_mouse_mode(self, enabled: bool) -> None:
        if not self.hotkey_manager:
            return
        try:
            from hotkey.config import MouseButtonConfig
            from hotkey.persistence import ConfigManager
        except Exception:
            return

        config = self.hotkey_manager.get_config()
        mouse_cfg = config.mouse_hotkeys.get("middle_button")
        if mouse_cfg is None:
            mouse_cfg = MouseButtonConfig(enabled=enabled, mode=self._mouse_hotkey_mode)
            config.mouse_hotkeys["middle_button"] = mouse_cfg
        else:
            mouse_cfg.enabled = enabled
            mouse_cfg.mode = self._mouse_hotkey_mode
        self.hotkey_manager.update_config(config)
        ConfigManager.save_config(config)
        self._sync_hotkey_config(config)

    def _update_tutorial_texts(self) -> None:
        hold_keys = self._format_keys_display(self._parse_keys_text(self._primary_hotkey_text))
        toggle_keys = self._format_keys_display(self._parse_keys_text(self._freehand_hotkey_text))

        hold_mode = self._primary_hotkey_mode
        toggle_mode = self._freehand_hotkey_mode

        if hold_keys:
            if hold_mode == "hold":
                hold_text = f"按住 {hold_keys} 说话，松开提交"
            else:
                hold_text = f"按 {hold_keys} 开/关说话"
        else:
            hold_text = "按着说：未设置"

        if toggle_keys:
            if toggle_mode == "toggle":
                toggle_text = f"按 {toggle_keys} 开/关自由说"
            else:
                toggle_text = f"按住 {toggle_keys} 自由说"
        else:
            toggle_text = "自由说：未设置"

        if self._mouse_mode_enabled:
            if self._mouse_hotkey_mode == "toggle":
                mouse_text = "智能鼠标模式：点击鼠标中键开始/结束录音"
            else:
                mouse_text = "智能鼠标模式：按住鼠标中键开始录音"
        else:
            mouse_text = "智能鼠标模式：已关闭"

        self._set_if_changed("_tutorial_hold_text", f"按着说：{hold_text}", self.tutorialHoldTextChanged)
        self._set_if_changed("_tutorial_toggle_text", f"自由说：{toggle_text}", self.tutorialToggleTextChanged)
        self._set_if_changed("_tutorial_mouse_text", mouse_text, self.tutorialMouseTextChanged)

    def _update_keyboard_hotkey(
        self,
        hotkey_id: str,
        keys: Optional[List[str]] = None,
        mode: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if not self.hotkey_manager:
            return
        try:
            from hotkey.config import HotkeyConfig
            from hotkey.persistence import ConfigManager
        except Exception:
            return

        config = self.hotkey_manager.get_config()
        hk = config.keyboard_hotkeys.get(hotkey_id)
        if hk is None:
            if hotkey_id == "freehand":
                hk = HotkeyConfig(enabled=True, keys=["alt", "super"], mode="toggle")
            else:
                hk = HotkeyConfig(enabled=True, keys=["ctrl", "super"], mode="hold")
            config.keyboard_hotkeys[hotkey_id] = hk

        if keys is not None:
            hk.keys = keys or hk.keys
        if mode is not None:
            hk.mode = mode
        if enabled is not None:
            hk.enabled = enabled

        self.hotkey_manager.update_config(config)
        ConfigManager.save_config(config)
        self._sync_hotkey_config(config)

    def _update_mouse_hotkey(self, mode: Optional[str] = None) -> None:
        if not self.hotkey_manager:
            return
        try:
            from hotkey.persistence import ConfigManager
        except Exception:
            return
        config = self.hotkey_manager.get_config()
        mouse_cfg = config.mouse_hotkeys.get("middle_button")
        if mouse_cfg is None:
            return
        if mode is not None:
            mouse_cfg.mode = mode
        self.hotkey_manager.update_config(config)
        ConfigManager.save_config(config)
        self._sync_hotkey_config(config)

    def _sync_hotkey_config(self, config) -> None:
        primary = getattr(config, "keyboard_hotkeys", {}).get("primary") if config else None
        freehand = getattr(config, "keyboard_hotkeys", {}).get("freehand") if config else None
        mouse = getattr(config, "mouse_hotkeys", {}).get("middle_button") if config else None

        self._set_if_changed(
            "_primary_hotkey_enabled", bool(primary.enabled) if primary else False, self.primaryHotkeyEnabledChanged
        )
        self._set_if_changed(
            "_primary_hotkey_mode", primary.mode if primary else "hold", self.primaryHotkeyModeChanged
        )
        self._set_if_changed(
            "_primary_hotkey_text",
            self._format_keys_edit(primary.keys) if primary else "",
            self.primaryHotkeyTextChanged,
        )

        self._set_if_changed(
            "_freehand_hotkey_enabled", bool(freehand.enabled) if freehand else False, self.freehandHotkeyEnabledChanged
        )
        self._set_if_changed(
            "_freehand_hotkey_mode", freehand.mode if freehand else "toggle", self.freehandHotkeyModeChanged
        )
        self._set_if_changed(
            "_freehand_hotkey_text",
            self._format_keys_edit(freehand.keys) if freehand else "",
            self.freehandHotkeyTextChanged,
        )

        self._set_if_changed(
            "_mouse_hotkey_mode", mouse.mode if mouse else "hold", self.mouseHotkeyModeChanged
        )

        self._set_if_changed(
            "_mouse_mode_enabled", bool(mouse and mouse.enabled), self.mouseModeEnabledChanged
        )
        self._update_tutorial_texts()

    def _format_keys_edit(self, keys: List[str]) -> str:
        return " + ".join(self._format_key_label(k) for k in keys if k)

    def _format_keys_display(self, keys: List[str]) -> str:
        return " + ".join(self._format_key_label(k) for k in keys if k)

    def _format_key_label(self, key: str) -> str:
        key = (key or "").lower().strip()
        if not key:
            return ""

        prefix = ""
        if key.startswith("right_"):
            prefix = "右 "
            key = key[6:]
        elif key.startswith("left_"):
            prefix = "左 "
            key = key[5:]

        if key in ("ctrl", "control"):
            label = "Ctrl"
        elif key in ("alt", "option"):
            label = "Alt"
        elif key in ("shift",):
            label = "Shift"
        elif key in ("super", "win", "cmd", "command"):
            if self._is_windows:
                label = "Win"
            elif self._is_mac:
                label = "Cmd"
            else:
                label = "Super"
        else:
            label = key.replace("_", " ").title()

        return f"{prefix}{label}"

    def _parse_keys_text(self, text: str) -> List[str]:
        if not text:
            return []
        normalized = text
        normalized = normalized.replace("右 ", "right_").replace("左 ", "left_")
        normalized = re.sub(r"\\bright\\s+", "right_", normalized, flags=re.I)
        normalized = re.sub(r"\\bleft\\s+", "left_", normalized, flags=re.I)
        normalized = normalized.replace("+", " ").replace(",", " ")
        parts = [p.strip().lower() for p in normalized.split() if p.strip()]

        out: List[str] = []
        for part in parts:
            part = part.replace("-", "_")
            if part.startswith("left_"):
                part = part[5:]
            if part in ("ctrl", "control", "ctl"):
                part = "ctrl"
            elif part in ("alt", "option"):
                part = "alt"
            elif part in ("win", "windows", "super", "cmd", "command"):
                part = "super"
            elif part in ("shift",):
                part = "shift"
            elif part.startswith("right_"):
                base = part[6:]
                if base in ("win", "windows", "super", "cmd", "command"):
                    part = "right_super"
                elif base in ("ctrl", "control", "ctl"):
                    part = "right_ctrl"
                elif base in ("alt", "option"):
                    part = "right_alt"
                elif base in ("shift",):
                    part = "right_shift"
            if part and part not in out:
                out.append(part)
        return out

    def _set_if_changed(self, attr: str, value: object, signal: QtCore.pyqtSignal) -> None:
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            signal.emit()

    def _reset_hotkey_state(self) -> None:
        if self.hotkey_manager:
            self.hotkey_manager.reset_state()

    def _suspend_hotkeys(self) -> None:
        if not self.hotkey_manager:
            return
        self._hotkeys_suspend_count += 1
        if self._hotkeys_suspend_count != 1:
            return
        self.hotkey_manager.set_suspended(True)

    def _resume_hotkeys(self) -> None:
        if not self.hotkey_manager:
            return
        if self._hotkeys_suspend_count == 0:
            return
        self._hotkeys_suspend_count -= 1
        if self._hotkeys_suspend_count != 0:
            return
        self.hotkey_manager.set_suspended(False)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if self._capture_target and event.type() == QtCore.QEvent.Type.KeyRelease:
            key_event: QtGui.QKeyEvent = event  # type: ignore[assignment]
            combo = self._event_to_combo(key_event)
            if combo:
                keys = self._parse_keys_text(combo)
                if self._capture_target == "primary":
                    self._update_keyboard_hotkey("primary", keys=keys)
                elif self._capture_target == "freehand":
                    self._update_keyboard_hotkey("freehand", keys=keys)
                self.hotkeyCaptured.emit(self._capture_target, self._format_keys_edit(keys))
            self._capture_target = None
            self._resume_hotkeys()
            return True
        return super().eventFilter(obj, event)

    def _event_to_combo(self, event: QtGui.QKeyEvent) -> str:
        parts: List[str] = []
        mods = event.modifiers() | self._modifier_from_key(event.key())

        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            if self._is_windows:
                parts.append("Win")
            elif self._is_mac:
                parts.append("Cmd")
            else:
                parts.append("Super")

        key = event.key()
        key_name = self._key_name_from_event(key, event.text(), include_mod_key=True)
        if key_name and key_name not in parts:
            parts.append(key_name)
        return " + ".join(parts)

    def _modifier_from_key(self, key: int) -> Qt.KeyboardModifier:
        if key in (Qt.Key.Key_Control,):
            return Qt.KeyboardModifier.ControlModifier
        if key in (Qt.Key.Key_Shift,):
            return Qt.KeyboardModifier.ShiftModifier
        if key in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
            return Qt.KeyboardModifier.AltModifier
        if key in (Qt.Key.Key_Meta, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R):
            return Qt.KeyboardModifier.MetaModifier
        return Qt.KeyboardModifier.NoModifier

    def _key_name_from_event(self, key: int, text: str, include_mod_key: bool = False) -> str:
        if key in (
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_AltGr,
            Qt.Key.Key_Super_L,
            Qt.Key.Key_Super_R,
        ):
            if not include_mod_key:
                return ""
            if key == Qt.Key.Key_Control:
                return "Ctrl"
            if key in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
                return "Alt"
            if key == Qt.Key.Key_Shift:
                return "Shift"
            return "Super" if not self._is_windows else "Win" if self._is_windows else "Cmd" if self._is_mac else "Super"
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).upper()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            return f"F{key - Qt.Key.Key_F1 + 1}"
        mapping = {
            Qt.Key.Key_Space: "Space",
            Qt.Key.Key_Return: "Enter",
            Qt.Key.Key_Enter: "Enter",
            Qt.Key.Key_Tab: "Tab",
            Qt.Key.Key_Backspace: "Backspace",
            Qt.Key.Key_Escape: "Esc",
            Qt.Key.Key_CapsLock: "CapsLock",
        }
        if key in mapping:
            return mapping[key]
        if text:
            t = text.strip()
            if t:
                return t.upper() if len(t) == 1 else t
        return f"Key_{key}"

    def _update_status_text(self) -> None:
        if self._connecting:
            text = "连接中…"
        elif self._sending:
            text = "识别中（麦克风）"
        elif self._connected:
            text = "已连接"
        else:
            text = "未连接"
        if text != self._status_text:
            self._status_text = text
            self.statusTextChanged.emit()

    def _current_session_elapsed(self) -> float:
        elapsed = self._session_elapsed_s
        if self._session_started_at is not None:
            elapsed += time.monotonic() - self._session_started_at
        return elapsed

    def _load_stats(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        try:
            self._stats_total_seconds = float(settings.value("Stats/total_seconds", 0.0))
        except (TypeError, ValueError):
            self._stats_total_seconds = 0.0
        try:
            self._stats_total_chars = int(settings.value("Stats/total_chars", 0))
        except (TypeError, ValueError):
            self._stats_total_chars = 0

    def _save_stats(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        settings.setValue("Stats/total_seconds", self._stats_total_seconds)
        settings.setValue("Stats/total_chars", self._stats_total_chars)
        settings.sync()

    def _load_connection_config(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        app_id = settings.value("Connection/app_id", self._app_id)
        access_token = settings.value("Connection/access_token", self._access_token)
        use_gzip = settings.value("Connection/use_gzip", self._use_gzip)
        saved_mode = settings.value("Connection/mode", self._mode)
        if app_id is not None:
            self._app_id = str(app_id)
        if access_token is not None:
            self._access_token = str(access_token)
        if isinstance(use_gzip, str):
            self._use_gzip = use_gzip.strip().lower() in ("1", "true", "yes", "on")
        else:
            self._use_gzip = bool(use_gzip)
        if saved_mode is not None:
            mode = str(saved_mode).strip().lower()
            if mode in ("nostream", "bidi", "bidi_async"):
                self._mode = mode

    def _save_connection_config(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        settings.setValue("Connection/app_id", self._app_id)
        settings.setValue("Connection/access_token", self._access_token)
        settings.setValue("Connection/use_gzip", self._use_gzip)
        settings.setValue("Connection/mode", self._mode)
        settings.sync()

    def _load_personalization_config(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        start_minimized = settings.value("Personalization/start_minimized", self._start_minimized)
        auto_submit = settings.value("Personalization/auto_submit", self._auto_submit)
        auto_submit_mode = settings.value("Personalization/auto_submit_mode", self._auto_submit_mode)
        auto_submit_paste_keys = settings.value(
            "Personalization/auto_submit_paste_keys",
            self._auto_submit_paste_keys,
        )
        enable_punc = settings.value("Personalization/enable_punc", self._enable_punc)
        enable_ddc = settings.value("Personalization/enable_ddc", self._enable_ddc)
        hotwords = settings.value("Personalization/hotwords", self._hotwords)

        def coerce_bool(value: object) -> bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)

        self._start_minimized = coerce_bool(start_minimized)
        self._auto_submit = coerce_bool(auto_submit)
        if auto_submit_mode is not None:
            mode = str(auto_submit_mode).strip().lower()
            if mode == "auto":
                mode = "type"
            if mode in ("type", "paste"):
                self._auto_submit_mode = mode
        if auto_submit_paste_keys is not None:
            value = str(auto_submit_paste_keys).strip()
            if value:
                self._auto_submit_paste_keys = value
        self._enable_punc = coerce_bool(enable_punc)
        self._enable_ddc = coerce_bool(enable_ddc)
        if hotwords is not None:
            self._hotwords = str(hotwords)

    def _save_personalization_config(self) -> None:
        settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        settings.setValue("Personalization/start_minimized", self._start_minimized)
        settings.setValue("Personalization/auto_submit", self._auto_submit)
        settings.setValue("Personalization/auto_submit_mode", self._auto_submit_mode)
        settings.setValue("Personalization/auto_submit_paste_keys", self._auto_submit_paste_keys)
        settings.setValue("Personalization/enable_punc", self._enable_punc)
        settings.setValue("Personalization/enable_ddc", self._enable_ddc)
        settings.setValue("Personalization/hotwords", self._hotwords)
        settings.sync()

    def _using_default_credentials(self) -> bool:
        return (
            self._app_id.strip() == self.DEFAULT_APP_ID
            and self._access_token.strip() == self.DEFAULT_ACCESS_TOKEN
        )

    def _start_default_limit_timer(self) -> None:
        if self._using_default_credentials():
            self._default_limit_timer.start(self.DEFAULT_RECORDING_LIMIT_S * 1000)

    def _stop_default_limit_timer(self) -> None:
        if self._default_limit_timer.isActive():
            self._default_limit_timer.stop()

    def _on_default_limit_timeout(self) -> None:
        if not self._sending or not self._using_default_credentials():
            return
        self.stop_recognition()
        QtWidgets.QMessageBox.information(
            None,
            "提示",
            "默认内置配置仅支持录制 1 分钟。\n请到火山引擎控制台申请豆包语音转换的 Key，并在连接配置中填写 App ID 和 Access Token。",
        )

    def _update_stats(self) -> None:
        elapsed = self._current_session_elapsed()
        total_elapsed = self._stats_total_seconds + elapsed

        total_seconds = int(total_elapsed)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        duration_text = f"{minutes:02d}:{seconds:02d}"

        text = self._current_session_text(include_partial=True)
        char_count = sum(1 for c in text if not c.isspace())
        total_chars = self._stats_total_chars + char_count
        if elapsed > 0:
            speed = int(char_count / (elapsed / 60.0))
        else:
            speed = self._stats_last_speed

        if (
            minutes != self._stats_minutes
            or total_chars != self._stats_chars
            or speed != self._stats_speed
            or duration_text != self._stats_duration_text
        ):
            self._stats_minutes = minutes
            self._stats_chars = total_chars
            self._stats_speed = speed
            self._stats_duration_text = duration_text
            self.statsChanged.emit()

    def _emit_history_reset(self) -> None:
        items = self._history_model.as_list()
        self.historyReset.emit(json.dumps(items))

    def _emit_history_row(self, row: int) -> None:
        payload = self._history_model.item_at(row)
        print(f"[HISTORY] Update row={row}, payload={payload}")  # DEBUG
        if payload is None:
            return
        self.historyRowUpdated.emit(row, json.dumps(payload))

    def _emit_history_insert(self, row: int) -> None:
        payload = self._history_model.item_at(row)
        print(f"[HISTORY] Insert row={row}, payload={payload}")  # DEBUG
        if payload is None:
            return
        self.historyRowInserted.emit(row, json.dumps(payload))

    def _emit_history_removed(self, row: int) -> None:
        self.historyRowRemoved.emit(row)

    def _now_label(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _begin_new_session(self) -> None:
        self._reset_session()
        if self._indicator_mode in ("hold", "toggle"):
            self._session_mode = self._indicator_mode
        else:
            self._session_mode = self._primary_hotkey_mode
        self._stats_last_speed = 0
        self._audio_sent = False  # 重置音频发送标志
        self._current_row = self._history_model.add_item(self._now_label(), "", True)
        self._stats_timer.start()
        self._update_stats()
        if self._current_row is not None:
            self._emit_history_insert(self._current_row)
        self._start_escape_listener()

    def _reset_session(self) -> None:
        self._stop_default_limit_timer()
        self._stop_escape_listener()
        self._session_mode = None
        self._auto_submit_stream_last = ""
        self._auto_submit_stream_sent_text = ""
        self._auto_submit_stream_pending = ""
        if self._auto_submit_stream_timer.isActive():
            self._auto_submit_stream_timer.stop()
        self._committed_text = ""
        self._session_partial = ""
        self._last_committed_end_time = -1
        self._last_full_text = ""
        self._user_cancelled = False
        self._current_row = None
        self._session_started_at = None
        self._session_elapsed_s = 0.0
        if self._stats_timer.isActive():
            self._stats_timer.stop()

    def _finalize_session(self, cancelled: bool = False) -> None:
        self._session_partial = ""
        if self._current_row is None:
            return
        content = self._current_session_text(include_partial=False)
        session_elapsed = self._current_session_elapsed()
        session_chars = sum(1 for c in content if not c.isspace())
        if not cancelled and session_chars > 0 and session_elapsed > 0:
            self._stats_last_speed = int(session_chars / (session_elapsed / 60.0))
        else:
            self._stats_last_speed = 0
        if not cancelled and session_chars > 0:
            if session_elapsed > 0:
                self._stats_total_seconds += session_elapsed
            self._stats_total_chars += session_chars
            self._save_stats()
        if not content:
            row = self._current_row
            self._history_model.remove_row(row)
            self._emit_history_removed(row)
        else:
            self._history_model.update_item(self._current_row, text=content, partial=False)
            self._emit_history_row(self._current_row)
            if not cancelled:
                clipboard = QtWidgets.QApplication.clipboard()
                clipboard.setText(content)
                if (
                    self._auto_submit
                    and self._session_mode == "toggle"
                    and not self._user_cancelled
                    and content
                ):
                    LOG.info(
                        "AUTO_SUBMIT candidate mode=toggle session_mode=%s text_len=%d cancelled=%s",
                        self._session_mode,
                        len(content),
                        self._user_cancelled,
                    )
                    self._auto_submit_text(content, immediate=False)
        self._current_row = None
        self._stats_timer.stop()
        self._committed_text = ""
        self._session_partial = ""
        self._session_elapsed_s = 0.0
        self._session_started_at = None
        self._stop_escape_listener()
        self._update_stats()
        self._hide_indicator()
        self._hide_indicator()

    def _current_session_text(self, include_partial: bool) -> str:
        text = self._committed_text.strip()
        if include_partial and self._session_partial.strip():
            if text:
                text = text + "\n" + self._session_partial.strip()
            else:
                text = self._session_partial.strip()
        return text.strip()

    def _current_stream_text(self) -> str:
        committed = self._committed_text.replace("\n", "").strip()
        partial = self._session_partial.strip()
        if self._mode == "bidi_async":
            return partial or committed
        if partial and committed and partial.startswith(committed):
            return partial
        if committed and partial:
            return committed + partial
        return committed or partial

    def _update_current_item(self) -> None:
        if self._current_row is None:
            return
        text = self._current_session_text(include_partial=True)
        partial_flag = self._sending or self._pending_close_after_last or bool(self._session_partial)
        self._history_model.update_item(self._current_row, text=text, partial=partial_flag)
        self._emit_history_row(self._current_row)

    def _append_committed(self, text: str, skip_auto_submit: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        if self._committed_text:
            self._committed_text = self._committed_text.rstrip() + "\n" + text
        else:
            self._committed_text = text
        self._update_current_item()
        if not skip_auto_submit:
            if self._auto_submit and self._session_mode == "hold" and self._mode == "bidi_async":
                self._auto_submit_stream_update()
            else:
                if self._auto_submit:
                    LOG.info(
                        "AUTO_SUBMIT candidate mode=hold session_mode=%s text_len=%d",
                        self._session_mode,
                        len(text),
                    )
                if self._auto_submit and self._session_mode == "hold":
                    self._auto_submit_text(text, immediate=True)
        self._update_stats()

    def _set_partial(self, text: str) -> None:
        self._session_partial = text.strip()
        self._update_current_item()
        if self._auto_submit and self._session_mode == "hold" and self._mode == "bidi_async":
            self._auto_submit_stream_update()
        self._update_stats()

    def _auto_submit_stream_update(self) -> None:
        raw_text = self._current_stream_text()
        if not raw_text:
            return
        text = raw_text.replace("\n", "")
        if not text:
            return
        if text == self._auto_submit_stream_last:
            return
        sent = self._auto_submit_stream_sent_text
        overlap = 0
        if sent:
            max_len = min(len(sent), len(text))
            for k in range(max_len, 0, -1):
                if text.startswith(sent[-k:]):
                    overlap = k
                    break
        LOG.info(
            "AUTO_SUBMIT stream_update len=%d sent_len=%d overlap=%d last_len=%d",
            len(text),
            len(sent),
            overlap,
            len(self._auto_submit_stream_last),
        )
        delta = text[overlap:]
        if delta:
            LOG.info("AUTO_SUBMIT stream_delta len=%d", len(delta))
            self._queue_auto_submit_stream(delta)
            self._auto_submit_stream_sent_text = sent + delta
        self._auto_submit_stream_last = text

    def _queue_auto_submit_stream(self, text: str) -> None:
        if not text:
            return
        self._auto_submit_stream_pending += text
        if not self._auto_submit_stream_timer.isActive():
            self._auto_submit_stream_timer.start()

    def _flush_auto_submit_stream(self) -> None:
        pending = self._auto_submit_stream_pending
        if not pending:
            return
        self._auto_submit_stream_pending = ""
        self._auto_submit_text(pending, immediate=True)

    def _auto_submit_final_text(self, final_text: str) -> None:
        return

    def _mode_to_url(self) -> str:
        if self._mode == "bidi":
            return "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
        if self._mode == "bidi_async":
            return "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
        return "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

    def _default_request_json_text(self) -> str:
        is_nostream = self._mode == "nostream"
        request = {
            "user": {"uid": "demo_uid"},
            "audio": {
                "format": "pcm",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                **({"language": "zh-CN"} if is_nostream else {}),
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": self._enable_punc,
                "enable_ddc": self._enable_ddc,
                "enable_word": False,
                "res_type": "full",
                "nbest": 1,
                "use_vad": True,
            },
        }
        hotwords_context = self._build_hotwords_context()
        if hotwords_context:
            request["request"].setdefault("corpus", {})["context"] = hotwords_context
        if self._using_default_credentials():
            request["request"]["vad_config"] = {"max_single_segment_time": 60000}
        return json.dumps(request, ensure_ascii=False)

    def _build_hotwords_context(self) -> str:
        raw = (self._hotwords or "").strip()
        if not raw:
            return ""
        parts = []
        for item in raw.replace(",", "\n").splitlines():
            word = item.strip()
            if word:
                parts.append({"word": word})
        if not parts:
            return ""
        payload = {"hotwords": parts}
        return json.dumps(payload, ensure_ascii=False)

    def _send_default_request(self) -> None:
        payload = self._default_request_json_text()
        frame = build_full_client_request(payload, use_gzip=self._use_gzip)
        self.ws.send_binary(frame)
        self._log("SEND", f"request ({len(frame)} bytes)")

    def _chunk_bytes(self) -> int:
        samples = int(round(16000 * (self.CHUNK_MS_DEFAULT / 1000.0)))
        return max(2, samples * 2)

    def _on_mic_permission_result(self, permission: "QPermission") -> None:
        """macOS 麦克风权限请求回调"""
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        status = app.checkPermission(permission)
        if status == QtCore.Qt.PermissionStatus.Granted:
            self._log("MIC", "Microphone permission granted")
            self._start_mic()  # 重新尝试启动麦克风
        else:
            self._log("MIC", f"Microphone permission not granted: {status}")
            QtWidgets.QMessageBox.warning(
                None,
                "麦克风权限",
                "麦克风权限未授予，无法进行语音识别。",
            )

    def _start_mic(self) -> None:
        if self._sending or not self._connected:
            return

        # macOS: 检查麦克风权限 (Qt 6.5+)
        if sys.platform == "darwin":
            self._log("MIC", f"macOS detected, _HAS_QTPERMISSION={_HAS_QTPERMISSION}")
            if _HAS_QTPERMISSION:
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    permission = QMicrophonePermission()
                    status = app.checkPermission(permission)
                    self._log("MIC", f"Microphone permission status: {status}")
                    if status == QtCore.Qt.PermissionStatus.Undetermined:
                        # 请求权限，权限授予后重新调用 _start_mic
                        self._log("MIC", "Requesting microphone permission on macOS")
                        app.requestPermission(permission, self._on_mic_permission_result)
                        return
                    elif status == QtCore.Qt.PermissionStatus.Denied:
                        self._log("MIC", "Microphone permission denied on macOS")
                        QtWidgets.QMessageBox.critical(
                            None,
                            "麦克风权限被拒绝",
                            "请在「系统设置 → 隐私与安全性 → 麦克风」中允许本应用访问麦克风。",
                        )
                        return
                    # status == Granted, continue
            else:
                self._log("MIC", "QMicrophonePermission not available, skipping permission check")

        self._show_indicator_mode(self._indicator_mode or self._primary_hotkey_mode)

        # Decide which audio backend to use
        use_qt = _qt_audio_input_available()
        use_sd = _HAS_SOUNDDEVICE and not use_qt

        if not use_qt and not use_sd:
            self._log("MIC", "No audio backend available")
            msg = "未检测到可用的音频输入后端。\n\n请检查系统是否有可用的麦克风设备。"
            QtWidgets.QMessageBox.critical(None, "错误", msg)
            return

        if use_sd:
            self._start_mic_sounddevice()
        else:
            self._start_mic_qt()

    def _start_mic_qt(self) -> None:
        """Start microphone using Qt multimedia backend."""
        audio_inputs = QMediaDevices.audioInputs()
        device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            device = audio_inputs[0]
            self._log("MIC", f"Using fallback device: {device.description()}")

        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()

        if fmt.sampleFormat() != QAudioFormat.SampleFormat.Int16:
            QtWidgets.QMessageBox.critical(
                None, "错误",
                f"麦克风格式不支持（需要 Int16）。当前 sampleFormat={fmt.sampleFormat()}",
            )
            return

        self._mic_in_rate = int(fmt.sampleRate())
        self._mic_in_channels = int(fmt.channelCount())
        self._mic_resampler = StreamingResamplerInt16(in_rate=self._mic_in_rate, out_rate=16000)
        self._mic_buffer.clear()
        self._use_sounddevice = False

        self._log("MIC", f"Creating QAudioSource: device={device.description()}, rate={fmt.sampleRate()}, channels={fmt.channelCount()}, format={fmt.sampleFormat()}")
        src = QAudioSource(device, fmt, self)
        self._log("MIC", f"QAudioSource created, state={src.state()}, error={src.error()}")
        io = src.start()
        self._log("MIC", f"QAudioSource started, io={io}, state={src.state()}, error={src.error()}")
        if io is None:
            self._log("MIC", "ERROR: QAudioSource.start() returned None!")
            QtWidgets.QMessageBox.critical(
                None,
                "错误",
                "无法启动音频录制。QAudioSource.start() 返回 None。",
            )
            return
        io.readyRead.connect(self._on_mic_ready)  # type: ignore[attr-defined]
        self._audio_source = src
        self._audio_io = io
        self._finalize_mic_start()

    def _start_mic_sounddevice(self) -> None:
        """Start microphone using sounddevice backend (Linux fallback)."""
        if _sounddevice is None:
            return
        self._log("MIC", "Using sounddevice backend")
        self._mic_in_rate = 16000
        self._mic_in_channels = 1
        self._mic_resampler = StreamingResamplerInt16(in_rate=16000, out_rate=16000)
        self._mic_buffer.clear()
        self._use_sounddevice = True

        def audio_callback(indata, frames, time_info, status):
            if status:
                self._log("MIC", f"sounddevice status: {status}")
            raw = indata.tobytes()
            QtCore.QMetaObject.invokeMethod(
                self, "_on_sd_audio_data",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bytes, raw),
            )

        try:
            self._sd_stream = _sounddevice.InputStream(
                samplerate=16000, channels=1, dtype="int16",
                blocksize=int(16000 * self.CHUNK_MS_DEFAULT / 1000),
                callback=audio_callback,
            )
            self._sd_stream.start()
            self._finalize_mic_start()
        except Exception as e:
            self._log("MIC", f"sounddevice error: {e}")
            QtWidgets.QMessageBox.critical(None, "错误", f"无法启动麦克风: {e}")

    def _finalize_mic_start(self) -> None:
        """Common finalization after mic start."""
        self._sending = True
        self.isSendingChanged.emit()
        self._update_status_text()
        self._start_default_limit_timer()
        if self._session_started_at is None:
            self._session_started_at = time.monotonic()
        if not self._stats_timer.isActive():
            self._stats_timer.start()
        self._update_stats()

    def _stop_mic_no_last(self) -> None:
        self._stop_default_limit_timer()
        # Stop Qt audio source
        try:
            if self._audio_source is not None:
                self._audio_source.stop()
        except Exception:
            pass
        self._audio_source = None
        self._audio_io = None
        # Stop sounddevice stream
        try:
            if self._sd_stream is not None:
                self._sd_stream.stop()
                self._sd_stream.close()
        except Exception:
            pass
        self._sd_stream = None
        self._use_sounddevice = False
        self._mic_buffer.clear()
        if self._sending:
            self._sending = False
            self.isSendingChanged.emit()
            self._update_status_text()
        if self._session_started_at is not None:
            self._session_elapsed_s += time.monotonic() - self._session_started_at
            self._session_started_at = None
        if self._stats_timer.isActive():
            self._stats_timer.stop()
        self._update_stats()

    def _auto_submit_text(self, text: str, immediate: bool) -> None:
        if not text or not self._auto_submit:
            return
        if self._user_cancelled:
            return
        text = text.strip()
        if not text:
            return
        try:
            LOG.info(
                "AUTO_SUBMIT start mode=%s immediate=%s session_mode=%s len=%d",
                self._auto_submit_mode,
                immediate,
                self._session_mode,
                len(text),
            )
            mode = self._auto_submit_mode
            if mode == "type":
                if not self._send_keystrokes_text(text):
                    self._log("AUTO_SUBMIT", "direct typing failed")
                return
            if mode == "paste":
                self._send_paste(text)
                return
            if self._should_try_direct_typing():
                if self._send_keystrokes_text(text):
                    return
            self._send_paste(text)
        except Exception as exc:
            self._log("AUTO_SUBMIT", f"failed: {exc}")

    def _should_try_direct_typing(self) -> bool:
        if not self._is_windows:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]

            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not ctypes.windll.user32.GetGUIThreadInfo(0, ctypes.byref(info)):
                return False
            return bool(info.hwndFocus) and bool(info.hwndCaret)
        except Exception:
            return False

    def _send_keystrokes_text(self, text: str) -> bool:
        if self._is_linux:
            if self._is_wayland and self._wtype_path:
                if self._wtype_type(text):
                    return True
            if self._xdotool_path and self._xdotool_type(
                text,
                clear_modifiers=self._session_mode == "hold",
            ):
                return True
            if self._wtype_path and self._wtype_type(text):
                return True
        # Windows: try native SendInput API first
        if self._is_windows:
            if self._windows_type_text(text):
                self._mark_auto_submit_backend("win32:sendinput_type")
                return True
        try:
            from pynput.keyboard import Controller

            controller = Controller()
            controller.type(text)
            self._mark_auto_submit_backend("pynput:type")
            return True
        except Exception:
            return False

    def _send_paste(self, text: str) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        key_combo = self._normalize_key_combo(self._auto_submit_paste_keys)
        if not key_combo:
            key_combo = self._default_paste_keys()
        if self._is_linux:
            if self._is_wayland and self._wtype_path:
                if self._wtype_key(key_combo):
                    return
            # X11: 尝试使用底层 XTest 扩展 (PRIMARY + Shift+Insert)
            if not self._is_wayland:
                try:
                    from x11_paste import x11_paste, is_available
                    if is_available() and x11_paste(text):
                        self._mark_auto_submit_backend("x11_xtest:shift_insert")
                        return
                except Exception:
                    pass
            if self._xdotool_path and self._xdotool_key(key_combo):
                return
            if self._wtype_path and self._wtype_key(key_combo):
                return
        # Windows: try native Windows API first (WM_PASTE, then SendInput)
        if self._is_windows:
            method = self._windows_send_paste()
            if method:
                self._mark_auto_submit_backend(f"win32:{method}")
                return
        try:
            if not self._send_key_combo_pynput(key_combo):
                fallback = self._default_paste_keys()
                self._send_key_combo_pynput(fallback)
            self._mark_auto_submit_backend("pynput:paste")
        except Exception:
            pass

    def _windows_send_paste(self) -> Optional[str]:
        """Send paste using Windows API. Returns method name on success, None on failure.

        First tries WM_PASTE message (more reliable for text controls),
        then falls back to SendInput Ctrl+V.
        """
        if not self._is_windows:
            return None

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Try WM_PASTE first
        try:
            WM_PASTE = 0x0302

            # Get focus window
            hwnd = user32.GetFocus()
            if not hwnd:
                # No focus in current thread, try to get from foreground window
                fg_hwnd = user32.GetForegroundWindow()
                if fg_hwnd:
                    # Attach to the foreground window's thread to get its focus
                    thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None)
                    current_thread = kernel32.GetCurrentThreadId()
                    if user32.AttachThreadInput(current_thread, thread_id, True):
                        hwnd = user32.GetFocus()
                        user32.AttachThreadInput(current_thread, thread_id, False)

            if hwnd:
                # SendMessageW returns 0 for WM_PASTE but that's not an error
                user32.SendMessageW(hwnd, WM_PASTE, 0, 0)
                # Small delay to ensure the target application processes the paste
                import time
                time.sleep(0.05)
                self._log("WIN32", "WM_PASTE sent successfully")
                return "wm_paste"
        except Exception as e:
            self._log("WIN32", f"WM_PASTE failed: {e}")

        # Fall back to SendInput Ctrl+V
        try:
            # Virtual key codes
            VK_CONTROL = 0x11
            VK_V = 0x56

            # Input type
            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [("ki", KEYBDINPUT)]

                _anonymous_ = ("_input",)
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            def make_key_input(vk: int, up: bool = False) -> INPUT:
                inp = INPUT(type=INPUT_KEYBOARD)
                inp.ki.wVk = vk
                inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
                return inp

            # Ctrl down, V down, V up, Ctrl up
            inputs = [
                make_key_input(VK_CONTROL, False),
                make_key_input(VK_V, False),
                make_key_input(VK_V, True),
                make_key_input(VK_CONTROL, True),
            ]
            arr = (INPUT * len(inputs))(*inputs)
            result = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
            if result == len(inputs):
                return "sendinput"
        except Exception as e:
            self._log("WIN32", f"SendInput failed: {e}")

        return None

    def _windows_type_text(self, text: str) -> bool:
        """Type text using Windows SendInput API with Unicode characters."""
        if not self._is_windows:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            INPUT_KEYBOARD = 1
            KEYEVENTF_UNICODE = 0x0004
            KEYEVENTF_KEYUP = 0x0002

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [("ki", KEYBDINPUT)]

                _anonymous_ = ("_input",)
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            inputs = []
            for char in text:
                code = ord(char)
                # Key down
                inp_down = INPUT(type=INPUT_KEYBOARD)
                inp_down.ki.wScan = code
                inp_down.ki.dwFlags = KEYEVENTF_UNICODE
                inputs.append(inp_down)
                # Key up
                inp_up = INPUT(type=INPUT_KEYBOARD)
                inp_up.ki.wScan = code
                inp_up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                inputs.append(inp_up)

            if not inputs:
                return True

            arr = (INPUT * len(inputs))(*inputs)
            result = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
            return result == len(inputs)
        except Exception as e:
            self._log("WIN32", f"SendInput type failed: {e}")
            return False

    def _default_paste_keys(self) -> str:
        return "cmd+v" if self._is_mac else "ctrl+v"

    def _normalize_key_combo(self, combo: str) -> str:
        if not combo:
            return ""
        parts = [p.strip().lower() for p in re.split(r"[+\\s]+", combo) if p.strip()]
        return "+".join(parts)

    def _parse_key_combo(self, combo: str) -> Tuple[List[str], Optional[str]]:
        parts = [p.strip().lower() for p in re.split(r"[+\\s]+", combo) if p.strip()]
        modifiers = []
        key = None
        for part in parts:
            if part in ("ctrl", "control", "ctl"):
                modifiers.append("ctrl")
            elif part in ("shift",):
                modifiers.append("shift")
            elif part in ("alt", "option"):
                modifiers.append("alt")
            elif part in ("super", "cmd", "command", "win", "windows", "meta"):
                modifiers.append("super")
            else:
                key = part
        return modifiers, key

    def _send_key_combo_pynput(self, combo: str) -> bool:
        modifiers, key = self._parse_key_combo(combo)
        if not key:
            return False
        try:
            from pynput.keyboard import Controller, Key

            key_map = {
                "enter": Key.enter,
                "return": Key.enter,
                "tab": Key.tab,
                "space": Key.space,
                "backspace": Key.backspace,
                "delete": Key.delete,
                "esc": Key.esc,
            }
            mod_map = {
                "ctrl": Key.ctrl,
                "shift": Key.shift,
                "alt": Key.alt,
                "super": Key.cmd,
            }
            controller = Controller()
            pressed_mods = []
            for mod in modifiers:
                key_obj = mod_map.get(mod)
                if key_obj:
                    controller.press(key_obj)
                    pressed_mods.append(key_obj)
            key_obj = key_map.get(key, key if len(key) == 1 else None)
            if not key_obj:
                for mod in reversed(pressed_mods):
                    controller.release(mod)
                return False
            controller.press(key_obj)
            controller.release(key_obj)
            for mod in reversed(pressed_mods):
                controller.release(mod)
            return True
        except Exception:
            return False

    def _auto_submit_type_delay_ms(self, text: str) -> int:
        char_count = sum(1 for c in text if not c.isspace())
        if char_count <= 0:
            return 60
        delay = int(600 / char_count)
        if delay < 20:
            delay = 20
        if delay > 80:
            delay = 80
        return delay

    def _xdotool_type(self, text: str, clear_modifiers: bool = False) -> bool:
        if not self._xdotool_path:
            return False
        preview = text
        if len(preview) > 120:
            preview = preview[:120] + "..."
        delay_ms = self._auto_submit_type_delay_ms(text)
        try:
            if clear_modifiers:
                LOG.info(
                    "AUTO_SUBMIT xdotool type --clearmodifiers --delay %d %r (len=%d)",
                    delay_ms,
                    preview,
                    len(text),
                )
            else:
                LOG.info("AUTO_SUBMIT xdotool type --delay %d %r (len=%d)", delay_ms, preview, len(text))
            args = [self._xdotool_path, "type"]
            if clear_modifiers:
                args.append("--clearmodifiers")
            args += ["--delay", str(delay_ms), text]
            if not self._enqueue_auto_submit_cmd(args, "xdotool:type"):
                return False
            self._mark_auto_submit_backend("xdotool:type")
            return True
        except Exception:
            return False

    def _xdotool_key(self, key_combo: str) -> bool:
        if not self._xdotool_path:
            return False
        try:
            LOG.info("AUTO_SUBMIT xdotool key %s", key_combo)
            if not self._enqueue_auto_submit_cmd(
                [self._xdotool_path, "key", "--clearmodifiers", key_combo],
                "xdotool:paste",
            ):
                return False
            self._mark_auto_submit_backend("xdotool:paste")
            return True
        except Exception:
            return False

    def _wtype_type(self, text: str) -> bool:
        if not self._wtype_path:
            return False
        try:
            args = [self._wtype_path]
            if text.startswith("-"):
                args.append("--")
            args.append(text)
            if not self._enqueue_auto_submit_cmd(args, "wtype:type"):
                return False
            self._mark_auto_submit_backend("wtype:type")
            return True
        except Exception:
            return False

    def _wtype_key(self, key_combo: str) -> bool:
        if not self._wtype_path:
            return False
        try:
            normalized = self._normalize_key_combo(key_combo)
            modifiers, key = self._parse_key_combo(normalized)
            if not key:
                return False
            key_map = {"enter": "Return", "return": "Return", "tab": "Tab", "space": "space"}
            mod_map = {"ctrl": "ctrl", "shift": "shift", "alt": "alt", "super": "logo"}
            args = [self._wtype_path]
            for mod in modifiers:
                mapped = mod_map.get(mod)
                if mapped:
                    args += ["-M", mapped]
            args.append(key_map.get(key, key))
            for mod in reversed(modifiers):
                mapped = mod_map.get(mod)
                if mapped:
                    args += ["-m", mapped]
            if not self._enqueue_auto_submit_cmd(args, "wtype:paste"):
                return False
            self._mark_auto_submit_backend("wtype:paste")
            return True
        except Exception:
            return False

    def _enqueue_auto_submit_cmd(self, args: List[str], label: str) -> bool:
        try:
            self._ensure_auto_submit_worker()
            self._auto_submit_queue.put((args, label))
            return True
        except Exception:
            return False

    def _ensure_auto_submit_worker(self) -> None:
        worker = self._auto_submit_worker
        if worker and worker.is_alive():
            return
        with self._auto_submit_worker_lock:
            worker = self._auto_submit_worker
            if worker and worker.is_alive():
                return
            self._auto_submit_worker = threading.Thread(
                target=self._auto_submit_worker_loop,
                name="auto_submit_worker",
                daemon=True,
            )
            self._auto_submit_worker.start()

    def _auto_submit_worker_loop(self) -> None:
        while True:
            args, label = self._auto_submit_queue.get()
            try:
                subprocess.run(
                    args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                LOG.info("AUTO_SUBMIT %s failed: %s", label, exc)
            finally:
                self._auto_submit_queue.task_done()

    def _refresh_auto_submit_status(self, last_used: Optional[str] = None) -> None:
        available = []
        if self._xdotool_path:
            available.append("xdotool")
        if self._wtype_path:
            available.append("wtype")
        try:
            import pynput  # noqa: F401

            available.append("pynput")
        except Exception:
            pass
        available_text = "、".join(available) if available else "无"
        if last_used:
            status = f"当前上屏后端：{last_used}"
        else:
            order = "Wayland: wtype > xdotool > pynput" if self._is_wayland else "X11: xdotool > wtype > pynput"
            status = f"上屏后端：{self._auto_submit_mode}（{order}），可用：{available_text}"
        if status != self._auto_submit_status:
            self._auto_submit_status = status
            self.autoSubmitStatusChanged.emit()

    def _mark_auto_submit_backend(self, backend: str) -> None:
        self._refresh_auto_submit_status(last_used=backend)

    def _stop_mic_send_last(self) -> None:
        remainder = bytes(self._mic_buffer) if self._mic_buffer else b""
        self._stop_mic_no_last()
        if not self._connected:
            return
        frame = build_audio_only_request(remainder, last=True, use_gzip=self._use_gzip)
        self.ws.send_binary(frame)
        self._log("SEND", f"audio-only LAST({len(remainder)}B)")

    def _on_mic_ready(self) -> None:
        if not self._sending or not self._connected:
            return
        if self._audio_io is None:
            return
        raw = bytes(self._audio_io.readAll())
        if not raw:
            return
        # Debug: log first few calls
        if not hasattr(self, '_mic_ready_count'):
            self._mic_ready_count = 0
        self._mic_ready_count += 1
        if self._mic_ready_count <= 3:
            self._log("MIC", f"_on_mic_ready called #{self._mic_ready_count}, raw bytes={len(raw)}")
        pcm16k = mic_bytes_to_pcm16le_16k_mono(
            raw,
            in_rate=self._mic_in_rate,
            in_channels=self._mic_in_channels,
            resampler=self._mic_resampler,
        )
        if not pcm16k:
            return
        self._mic_buffer.extend(pcm16k)
        chunk_bytes = self._chunk_bytes()
        while len(self._mic_buffer) >= chunk_bytes:
            chunk = bytes(self._mic_buffer[:chunk_bytes])
            del self._mic_buffer[:chunk_bytes]
            frame = build_audio_only_request(chunk, last=False, use_gzip=self._use_gzip)
            self.ws.send_binary(frame)
            self._audio_sent = True  # 标记已发送音频数据

    @QtCore.pyqtSlot(bytes)
    def _on_sd_audio_data(self, raw: bytes) -> None:
        """Handle audio data from sounddevice backend."""
        if not self._sending or not self._connected:
            return
        if not raw:
            return
        self._mic_buffer.extend(raw)
        chunk_bytes = self._chunk_bytes()
        while len(self._mic_buffer) >= chunk_bytes:
            chunk = bytes(self._mic_buffer[:chunk_bytes])
            del self._mic_buffer[:chunk_bytes]
            frame = build_audio_only_request(chunk, last=False, use_gzip=self._use_gzip)
            self.ws.send_binary(frame)
            self._audio_sent = True

    def _on_connected(self) -> None:
        self._connected = True
        self._connecting = False
        self.isConnectedChanged.emit()
        self.isConnectingChanged.emit()
        self._update_status_text()
        self._send_default_request()
        # 连接成功后,切换到录音模式指示器
        self._show_indicator_mode(self._indicator_mode)
        self._start_mic()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._connecting = False
        self._sending = False
        self._stop_default_limit_timer()
        self.isConnectedChanged.emit()
        self.isConnectingChanged.emit()
        self.isSendingChanged.emit()
        self._pending_close_timer.stop()
        self._update_status_text()
        self._finalize_session(cancelled=False)
        self._hide_indicator()

    def _on_ws_error(self, msg: str) -> None:
        QtWidgets.QMessageBox.critical(None, "连接错误", msg)
        self._force_close()

    def _on_hotkey_error(self, error_msg: str) -> None:
        QtWidgets.QMessageBox.warning(None, "快捷键错误", error_msg)

    def _on_snippet_triggered(self, snippet_id: str, text: str) -> None:
        """处理文本片段快捷键触发"""
        self._log("SNIPPET", f"Triggered snippet '{snippet_id}': {text[:50]}...")
        # 复制文本到剪贴板并粘贴
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            # 延迟一小段时间确保剪贴板内容已设置
            QtCore.QTimer.singleShot(50, self._paste_snippet)

    def _paste_snippet(self) -> None:
        """粘贴文本片段"""
        self._send_paste_key()

    def _on_hotkey_start_recording(self, mode: str) -> None:
        # 热键触发时保存模式用于后续连接成功后显示
        self._indicator_mode = mode if mode in ("hold", "toggle") else self._primary_hotkey_mode
        self.start_recognition(self._indicator_mode)

    def _on_indicator_cancel(self) -> None:
        self._user_cancelled = True
        self.stop_recognition()

    def _on_indicator_confirm(self) -> None:
        self.stop_recognition()

    def _on_ws_binary(self, data: bytes) -> None:
        parsed = parse_server_message(data)
        if parsed.kind == "error":
            QtWidgets.QMessageBox.critical(None, "服务端错误", f"{parsed.error_code}\n{parsed.error_msg}")
            if self._pending_close_after_last:
                self._force_close()
            return
        if parsed.kind != "response":
            return

        partial = ""
        try:
            obj = json.loads(parsed.json_text or "")
        except Exception:
            obj = None

        final_text: Optional[str] = None
        if isinstance(obj, dict):
            result = obj.get("result")
            if isinstance(result, dict):
                utterances = result.get("utterances")
                if isinstance(utterances, list):
                    for u in utterances:
                        if not isinstance(u, dict):
                            continue
                        if not u.get("definite"):
                            continue
                        end_time = u.get("end_time")
                        if not isinstance(end_time, int):
                            continue
                        if end_time <= self._last_committed_end_time:
                            continue
                        txt = u.get("text")
                        if isinstance(txt, str) and txt.strip():
                            self._append_committed(txt.strip())
                            self._last_committed_end_time = end_time
                    for u in reversed(utterances):
                        if isinstance(u, dict) and not u.get("definite"):
                            txt = u.get("text")
                            if isinstance(txt, str) and txt.strip():
                                partial = txt.strip()
                            break
                else:
                    txt = result.get("text")
                    if isinstance(txt, str) and txt.strip():
                        full = txt.strip()
                        if self._mode == "bidi_async":
                            partial = full
                            final_text = full
                        elif self._last_full_text and full.startswith(self._last_full_text):
                            suffix = full[len(self._last_full_text) :].strip()
                            if suffix:
                                self._append_committed(suffix)
                        elif full != self._last_full_text:
                            self._append_committed(full)
                        self._last_full_text = full

        self._set_partial(partial)
        if final_text and parsed.flags == 0b0011:
            self._session_partial = ""
            self._append_committed(final_text, skip_auto_submit=True)
            self._auto_submit_final_text(final_text)

        if self._pending_close_after_last and parsed.flags == 0b0011:
            session_text = self._current_session_text(include_partial=False)
            if not self._user_cancelled and session_text:
                clipboard = QtWidgets.QApplication.clipboard()
                clipboard.setText(session_text)
                self._log("INFO", f"已复制到剪贴板: {session_text}")
            self._force_close()

    def _log(self, tag: str, msg: str) -> None:
        print(f"[{tag}] {msg}")

    def _force_close(self) -> None:
        self._connecting = False
        self._connected = False
        self._pending_close_after_last = False
        try:
            self.ws.close_ws()
        except Exception:
            pass
        self._stop_mic_no_last()
        self._update_status_text()
        self._hide_indicator()

    def _hide_indicator(self) -> None:
        if hasattr(self, "recording_indicator") and self.recording_indicator:
            try:
                self.recording_indicator.hide()
            except Exception:
                pass

    def _show_indicator_mode(self, mode: str) -> None:
        if not hasattr(self, "recording_indicator") or not self.recording_indicator:
            return
        try:
            if mode == "toggle":
                self.recording_indicator.show_toggle_mode()
            else:
                self.recording_indicator.show_hold_mode()
        except Exception:
            pass

    def _start_escape_listener(self) -> None:
        if not self._session_mode or self._session_mode != "toggle":
            return
        if self._escape_listener is not None:
            return
        try:
            from pynput import keyboard

            def on_press(key):  # noqa: ANN001
                try:
                    if key == keyboard.Key.esc:
                        QtCore.QTimer.singleShot(0, self._on_escape_cancel)
                except Exception:
                    pass

            listener = keyboard.Listener(on_press=on_press)
            listener.start()
            self._escape_listener = listener
        except Exception:
            self._escape_listener = None

    def _stop_escape_listener(self) -> None:
        listener = self._escape_listener
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass
        self._escape_listener = None

    def _on_escape_cancel(self) -> None:
        if self._session_mode != "toggle":
            return
        self._user_cancelled = True
        self.stop_recognition()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if hasattr(self, "hotkey_manager") and self.hotkey_manager:
            try:
                self.hotkey_manager.stop_listening()
            except Exception:
                pass

        if hasattr(self, "recording_indicator") and self.recording_indicator:
            try:
                self.recording_indicator.cleanup()
            except Exception:
                pass

        try:
            if self._sending:
                self._stop_mic_no_last()
        except Exception:
            pass
        try:
            self.ws.stop()
            self.ws.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)


class TrayWebView(QtWebEngineWidgets.QWebEngineView):
    def __init__(self) -> None:
        super().__init__()
        self.setPage(LoggingWebPage(self))
        self._tray_enabled = False
        self._quit_requested = False

    def enable_tray(self, enabled: bool) -> None:
        self._tray_enabled = enabled

    def request_quit(self) -> None:
        self._quit_requested = True
        self.close()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._tray_enabled and not self._quit_requested:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)


class LoggingWebPage(QtWebEngineCore.QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # noqa: N802
        try:
            if hasattr(level, "value"):
                level_value = int(level.value)
            else:
                level_value = int(level)
        except Exception:
            level_value = getattr(level, "name", str(level))
        LOG.info(
            "JS console level=%s %s:%s %s",
            level_value,
            source_id,
            line_number,
            message,
        )
        try:
            super().javaScriptConsoleMessage(level, message, line_number, source_id)
        except Exception:
            LOG.exception("JS console handler failed")


def _load_app_icon() -> QtGui.QIcon:
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    for icon_name in ("icon.ico", "icon.png"):
        icon_path = os.path.join(base_dir, icon_name)
        if os.path.exists(icon_path):
            icon = QtGui.QIcon(icon_path)
            if not icon.isNull():
                return icon
    return QtGui.QIcon()


def _build_tray_icon() -> QtGui.QIcon:
    icon = _load_app_icon()
    if not icon.isNull():
        return icon
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    icon_path = os.path.join(base_dir, "icon.png")
    if os.path.exists(icon_path):
        icon = QtGui.QIcon(icon_path)
        if not icon.isNull():
            return icon
    icon = QtGui.QIcon.fromTheme("microphone")
    if not icon.isNull():
        return icon
    size = 64
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setBrush(QtGui.QColor("#2ecc71"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff")))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "JT")
    painter.end()
    return QtGui.QIcon(pixmap)


def main() -> int:
    _setup_frozen_qt_env()
    # 启用 QtWebEngine 远程调试
    os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", "9223")

    app = QtWidgets.QApplication(sys.argv)
    app_icon = _load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    controller = AsrController()
    app.aboutToQuit.connect(controller.shutdown)

    # 使用 WebView 前端
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    web_dir = os.path.join(base_dir, "web")
    index_path = os.path.join(web_dir, "index.html")

    if not os.path.exists(index_path):
        QtWidgets.QMessageBox.critical(None, "错误", f"找不到前端资源: {index_path}")
        controller.shutdown()
        return 1

    view = TrayWebView()
    if not app_icon.isNull():
        view.setWindowIcon(app_icon)
    LOG.info("Web index path: %s", index_path)
    view.page().loadStarted.connect(lambda: LOG.info("Web load started"))
    view.page().loadFinished.connect(
        lambda ok: LOG.info("Web load finished ok=%s url=%s", ok, view.url().toString())
    )
    view.page().renderProcessTerminated.connect(
        lambda status, code: LOG.error(
            "Web render terminated status=%s code=%s", status, code
        )
    )

    # 开发者工具已启用 (通过环境变量 QTWEBENGINE_REMOTE_DEBUGGING)
    # 访问 http://localhost:9223 可以看到所有 WebEngine 实例
    # 点击对应的页面即可进入调试界面

    channel = QtWebChannel.QWebChannel()
    channel.registerObject("controller", controller)
    view.page().setWebChannel(channel)
    view.setWindowTitle("说了么")
    view.resize(1280, 860)
    view.load(QtCore.QUrl.fromLocalFile(index_path))
    app.installEventFilter(controller)
    tray_icon = None
    if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)
        tray_icon = QtWidgets.QSystemTrayIcon(_build_tray_icon(), app)
        tray_icon.setToolTip("说了么")

        tray_menu = QtWidgets.QMenu()
        show_action = QtGui.QAction("显示窗口", tray_menu)
        hotkeys_action = QtGui.QAction("启用全局快捷键", tray_menu)
        hotkeys_action.setCheckable(True)
        hotkeys_action.setChecked(controller.hotkeysEnabled)
        quit_action = QtGui.QAction("退出", tray_menu)

        def update_show_action() -> None:
            if view.isVisible() and not view.isMinimized():
                show_action.setText("隐藏窗口")
            else:
                show_action.setText("显示窗口")

        def show_main_window() -> None:
            view.showNormal()
            view.raise_()
            view.activateWindow()
            update_show_action()

        def toggle_main_window() -> None:
            if view.isVisible() and not view.isMinimized():
                view.hide()
            else:
                show_main_window()
            update_show_action()

        def quit_from_tray() -> None:
            view.request_quit()
            app.quit()

        def sync_hotkeys_action() -> None:
            if hotkeys_action.isChecked() != controller.hotkeysEnabled:
                hotkeys_action.setChecked(controller.hotkeysEnabled)

        def on_tray_activated(reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
            if reason in (
                QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
                QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
            ):
                toggle_main_window()

        show_action.triggered.connect(toggle_main_window)
        hotkeys_action.toggled.connect(lambda checked: setattr(controller, "hotkeysEnabled", checked))
        quit_action.triggered.connect(quit_from_tray)
        controller.hotkeysEnabledChanged.connect(sync_hotkeys_action)
        tray_menu.addAction(show_action)
        tray_menu.addAction(hotkeys_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        tray_icon.setContextMenu(tray_menu)
        tray_icon.activated.connect(on_tray_activated)
        tray_icon.show()
        view.enable_tray(True)
        update_show_action()
    if controller.startMinimized:
        if tray_icon is not None:
            view.hide()
        else:
            view.showMinimized()
    else:
        view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
