"""
X11 底层粘贴模块 - 使用 XTest 扩展

方案 B: PRIMARY + Shift+Insert
- 设置 PRIMARY selection owner
- 使用 XTest 发送 Shift+Insert
- 后台线程响应 SelectionRequest
"""

import threading
import time
from typing import Optional

try:
    from Xlib import display, X, XK, Xatom
    from Xlib.ext import xtest
    from Xlib.protocol import event
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False


class X11Paste:
    """X11 底层粘贴实现 - 方案 B: PRIMARY + Shift+Insert"""

    def __init__(self):
        if not XLIB_AVAILABLE:
            raise RuntimeError("python-xlib not available")

        # 注意：不再保持长期的 display 连接，每次操作使用独立连接
        # 这样可以避免线程安全问题
        self._owner_window = None
        self._selection_text: bytes = b""
        self._handler_thread: Optional[threading.Thread] = None
        self._stop_handler = False
        self._handler_display: Optional[display.Display] = None

    def _get_atoms(self, disp: display.Display):
        """获取所需的 atoms"""
        return {
            'PRIMARY': disp.intern_atom("PRIMARY"),
            'UTF8_STRING': disp.intern_atom("UTF8_STRING"),
            'TARGETS': disp.intern_atom("TARGETS"),
        }

    def _get_keycodes(self, disp: display.Display):
        """获取所需的 keycodes"""
        return {
            'shift': disp.keysym_to_keycode(XK.XK_Shift_L),
            'insert': disp.keysym_to_keycode(XK.XK_Insert),
        }

    def _set_primary(self, text: str, disp: display.Display) -> bool:
        """设置 PRIMARY selection"""
        atoms = self._get_atoms(disp)
        root = disp.screen().root

        # 创建 owner 窗口
        self._owner_window = root.create_window(
            0, 0, 1, 1, 0, X.CopyFromParent, X.InputOnly
        )
        self._owner_window.set_selection_owner(atoms['PRIMARY'], X.CurrentTime)
        disp.sync()

        self._selection_text = text.encode('utf-8')
        return True

    def _respond_selection(self, ev, disp: display.Display):
        """响应 SelectionRequest"""
        atoms = self._get_atoms(disp)
        target = ev.target
        prop = ev.property if ev.property else ev.target
        requestor = ev.requestor

        if target == atoms['TARGETS']:
            # 返回支持的目标类型
            requestor.change_property(
                prop, Xatom.ATOM, 32,
                [atoms['UTF8_STRING'], Xatom.STRING]
            )
        elif target in (atoms['UTF8_STRING'], Xatom.STRING):
            # 返回文本数据
            requestor.change_property(prop, target, 8, self._selection_text)
        else:
            prop = X.NONE

        # 发送 SelectionNotify
        notify = event.SelectionNotify(
            time=ev.time,
            requestor=requestor,
            selection=ev.selection,
            target=target,
            property=prop
        )
        requestor.send_event(notify)
        disp.flush()

    def _handle_selection_requests(self, timeout: float = 2.0):
        """处理 SelectionRequest 事件 - 使用独立的 Display 连接"""
        try:
            # 创建独立的 Display 连接用于后台线程
            self._handler_display = display.Display()
            disp = self._handler_display
            atoms = self._get_atoms(disp)

            # 重新获取 owner window 的引用（通过 window ID）
            if self._owner_window is None:
                return
            owner_id = self._owner_window.id
            owner = disp.create_resource_object('window', owner_id)

            start = time.time()
            handled = 0
            while not self._stop_handler and time.time() - start < timeout:
                if disp.pending_events():
                    ev = disp.next_event()
                    if ev.type == X.SelectionRequest:
                        self._respond_selection_with_disp(ev, disp, atoms)
                        handled += 1
                        if handled >= 5:  # 处理足够多的请求后退出
                            break
                else:
                    time.sleep(0.01)
        except Exception:
            pass
        finally:
            # 清理后台线程的 Display 连接
            if self._handler_display:
                try:
                    self._handler_display.close()
                except Exception:
                    pass
                self._handler_display = None

    def _respond_selection_with_disp(self, ev, disp: display.Display, atoms: dict):
        """响应 SelectionRequest（使用提供的 display 和 atoms）"""
        target = ev.target
        prop = ev.property if ev.property else ev.target
        requestor = ev.requestor

        try:
            if target == atoms['TARGETS']:
                # 返回支持的目标类型
                requestor.change_property(
                    prop, Xatom.ATOM, 32,
                    [atoms['UTF8_STRING'], Xatom.STRING]
                )
            elif target in (atoms['UTF8_STRING'], Xatom.STRING):
                # 返回文本数据
                requestor.change_property(prop, target, 8, self._selection_text)
            else:
                prop = X.NONE

            # 发送 SelectionNotify
            notify = event.SelectionNotify(
                time=ev.time,
                requestor=requestor,
                selection=ev.selection,
                target=target,
                property=prop
            )
            requestor.send_event(notify)
            disp.flush()
        except Exception:
            pass

    def _xtest_key_combo(self, disp: display.Display, modifier_keycode: int, key_keycode: int):
        """使用 XTest 发送组合键"""
        xtest.fake_input(disp, X.KeyPress, modifier_keycode)
        disp.sync()
        time.sleep(0.01)
        xtest.fake_input(disp, X.KeyPress, key_keycode)
        disp.sync()
        time.sleep(0.01)
        xtest.fake_input(disp, X.KeyRelease, key_keycode)
        disp.sync()
        time.sleep(0.01)
        xtest.fake_input(disp, X.KeyRelease, modifier_keycode)
        disp.sync()

    def paste(self, text: str) -> bool:
        """
        粘贴文本到当前焦点窗口

        使用 PRIMARY selection + Shift+Insert

        Args:
            text: 要粘贴的文本

        Returns:
            成功返回 True，失败返回 False
        """
        if not XLIB_AVAILABLE:
            return False

        # 每次粘贴使用独立的 display 连接，避免线程安全问题
        main_disp: Optional[display.Display] = None
        try:
            # 先清理之前的资源
            self._cleanup_previous()

            # 创建主线程的 display 连接
            main_disp = display.Display()
            keycodes = self._get_keycodes(main_disp)

            # 设置 PRIMARY selection
            self._set_primary(text, main_disp)

            # 启动后台线程处理 selection 请求（使用独立连接）
            self._stop_handler = False
            self._handler_thread = threading.Thread(
                target=self._handle_selection_requests,
                args=(2.0,),
                daemon=True
            )
            self._handler_thread.start()

            # 等待一下确保后台线程准备好
            time.sleep(0.05)

            # 发送 Shift+Insert
            self._xtest_key_combo(main_disp, keycodes['shift'], keycodes['insert'])

            # 等待粘贴完成
            time.sleep(0.1)

            return True

        except Exception:
            return False
        finally:
            # 主线程的 display 可以立即关闭，因为按键已经发送完成
            # owner_window 需要保留，因为后台线程还需要响应 SelectionRequest
            if main_disp:
                try:
                    main_disp.close()
                except Exception:
                    pass

    def _cleanup_previous(self):
        """清理之前的粘贴操作资源"""
        self._stop_handler = True
        if self._handler_thread and self._handler_thread.is_alive():
            self._handler_thread.join(timeout=0.1)
        if self._owner_window:
            try:
                self._owner_window.destroy()
            except Exception:
                pass
            self._owner_window = None

    def cleanup(self):
        """清理资源"""
        self._stop_handler = True
        if self._handler_thread and self._handler_thread.is_alive():
            self._handler_thread.join(timeout=0.5)
        if self._handler_display:
            try:
                self._handler_display.close()
            except Exception:
                pass
            self._handler_display = None
        if self._owner_window:
            try:
                self._owner_window.destroy()
            except Exception:
                pass
            self._owner_window = None


# 单例实例
_x11_paste: Optional[X11Paste] = None


def x11_paste(text: str) -> bool:
    """
    使用 X11 底层 API 粘贴文本（PRIMARY + Shift+Insert）

    Args:
        text: 要粘贴的文本

    Returns:
        成功返回 True，失败返回 False
    """
    global _x11_paste

    if not XLIB_AVAILABLE:
        return False

    try:
        if _x11_paste is None:
            _x11_paste = X11Paste()
        return _x11_paste.paste(text)
    except Exception:
        # 重置实例以便下次重试
        if _x11_paste:
            _x11_paste.cleanup()
            _x11_paste = None
        return False


def is_available() -> bool:
    """检查 X11 粘贴是否可用"""
    return XLIB_AVAILABLE
