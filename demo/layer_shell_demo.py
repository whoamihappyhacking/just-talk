import os
import signal
import sys
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


class LayerShellDemo(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._layer_shell_surface: Optional[object] = None
        self._bottom_margin = 80
        self._debug = bool(os.environ.get("JT_LAYER_SHELL_DEBUG"))
        self._setup_window()
        self.setFixedSize(240, 56)

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        flags |= Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _is_wayland_session(self) -> bool:
        session = (QtWidgets.QApplication.instance().platformName() or "").lower()
        return "wayland" in session

    def _ensure_window_handle(self) -> Optional[QtGui.QWindow]:
        window = self.windowHandle()
        if window is None:
            self.winId()
            window = self.windowHandle()
        return window

    def _log(self, message: str) -> None:
        if self._debug:
            print(message, flush=True)

    def _ensure_layer_shell(self) -> bool:
        if not self._is_wayland_session():
            self._log("Layer shell disabled: not a Wayland session")
            return False
        if self._layer_shell_surface is not None:
            return True
        try:
            from PyQt6.QtWaylandClient import QWaylandLayerShellSurface
        except Exception:
            self._log("Layer shell unavailable: PyQt6.QtWaylandClient not found")
            print("Layer shell unavailable: PyQt6.QtWaylandClient not found")
            return False

        window = self._ensure_window_handle()
        if window is None:
            return False

        surface = None
        try:
            surface = QWaylandLayerShellSurface(window)
        except Exception:
            surface = None

        if surface is None:
            for creator_name in ("create", "get"):
                creator = getattr(QWaylandLayerShellSurface, creator_name, None)
                if creator is None:
                    continue
                try:
                    surface = creator(window)
                except Exception:
                    surface = None
                if surface is not None:
                    break

        if surface is None:
            self._log("Layer shell unavailable: failed to create surface")
            print("Layer shell unavailable: failed to create surface")
            return False

        self._layer_shell_surface = surface
        self._configure_layer_shell_surface()
        return True

    def _configure_layer_shell_surface(self) -> None:
        surface = self._layer_shell_surface
        if surface is None:
            return

        layer_enum = getattr(surface, "Layer", None)
        if layer_enum is not None:
            for name in ("Overlay", "OverlayLayer", "Top", "TopLayer"):
                layer_value = getattr(layer_enum, name, None)
                if layer_value is not None:
                    try:
                        surface.setLayer(layer_value)
                    except Exception:
                        pass
                    break

        anchor_enum = getattr(surface, "Anchor", None)
        if anchor_enum is None:
            anchor_enum = getattr(surface, "Anchors", None)
        if anchor_enum is not None:
            anchors = anchor_enum.Left | anchor_enum.Bottom
            for method_name in ("setAnchors", "setAnchor"):
                method = getattr(surface, method_name, None)
                if method is None:
                    continue
                try:
                    method(anchors)
                    self._log(f"Layer shell anchors set via {method_name}")
                    break
                except Exception:
                    pass

        keyboard_enum = getattr(surface, "KeyboardInteractivity", None)
        if keyboard_enum is not None:
            for name in ("None", "NoKeyboard", "OnDemand"):
                keyboard_value = getattr(keyboard_enum, name, None)
                if keyboard_value is not None:
                    try:
                        surface.setKeyboardInteractivity(keyboard_value)
                    except Exception:
                        pass
                    break

        if hasattr(surface, "setExclusiveZone"):
            try:
                surface.setExclusiveZone(0)
            except Exception:
                pass

    def _apply_margins(self, surface: object, margins: QtCore.QMargins) -> None:
        for method_name in ("setMargins", "setMargin"):
            method = getattr(surface, method_name, None)
            if method is None:
                continue
            try:
                method(margins)
                return
            except Exception:
                try:
                    method(margins.left(), margins.top(), margins.right(), margins.bottom())
                    return
                except Exception:
                    pass

    def _update_layer_shell_geometry(self) -> None:
        surface = self._layer_shell_surface
        if surface is None:
            return
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return

        screen_geometry = screen.availableGeometry()
        total_w = self.width()
        margin_left = max(0, (screen_geometry.width() - total_w) // 2)
        bottom_margin = max(0, self._bottom_margin)

        self._apply_margins(surface, QtCore.QMargins(margin_left, 0, 0, bottom_margin))

        for method_name in ("setSize", "setDesiredSize"):
            method = getattr(surface, method_name, None)
            if method is None:
                continue
            try:
                method(self.size())
                break
            except Exception:
                try:
                    method(self.width(), self.height())
                    break
                except Exception:
                    continue

    def _move_fallback(self) -> None:
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        screen_geometry = screen.availableGeometry()
        x = screen_geometry.x() + (screen_geometry.width() - self.width()) // 2
        y = screen_geometry.y() + screen_geometry.height() - self.height() - self._bottom_margin
        self.move(x, y)

    def show_at_bottom_center(self) -> None:
        if self._ensure_layer_shell():
            self._update_layer_shell_geometry()
        else:
            self._move_fallback()
        self.show()
        self.raise_()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self._ensure_layer_shell():
            self._update_layer_shell_geometry()
        else:
            self._move_fallback()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(self.rect())
        corner_radius = rect.height() / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 230))
        painter.drawRoundedRect(rect, corner_radius, corner_radius)

        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "Layer Shell Demo")


def main() -> int:
    if sys.platform.startswith("linux"):
        force_x11 = os.environ.get("JT_FORCE_X11")
        if force_x11 is None or force_x11.strip().lower() not in {"0", "false", "no", "off", "disable", "disabled"}:
            os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sig_timer = QtCore.QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(200)
    demo = LayerShellDemo()
    demo.show_at_bottom_center()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
