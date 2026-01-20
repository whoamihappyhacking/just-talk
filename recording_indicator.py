"""录音指示器 - 参考闪电说的设计风格"""

import math
import random
import sys
from typing import List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


class AudioWaveformWidget(QtWidgets.QWidget):
    """音频波形组件 - 竖条状波浪（类似gemini效果）"""

    def __init__(self, bar_count: int = 11, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._bar_count = bar_count
        # 根据条数计算宽度：3px条宽 + 3px间距
        width = bar_count * 3 + (bar_count - 1) * 3
        self.setFixedSize(width, 20)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._bars: List[dict] = []
        self._initialize_bars()

        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self._last_elapsed_ms = self._clock.elapsed()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)  # ~30fps，更接近CSS动画的顺滑
        self._timer.timeout.connect(self._update_bars)
        self._timer.start()

    def _initialize_bars(self) -> None:
        """初始化波形条 - 中间高两边低"""
        for i in range(self._bar_count):
            # 计算距离中心的距离
            dist_from_center = abs(i - (self._bar_count - 1) / 2)
            # 最大高度：中间20px，两边递减
            max_height = max(4, 20 - dist_from_center * 3)

            # 随机动画参数
            duration = 0.4 + random.random() * 0.5
            phase = random.random() * 2 * math.pi

            self._bars.append({
                'max_height': max_height,
                'min_height': 4,
                'duration': duration,
                'phase': phase,
                'current_height': 4
            })

    def _update_bars(self) -> None:
        """更新波形条高度 - 正弦波动"""
        now_ms = self._clock.elapsed()
        dt_s = max(0.0, (now_ms - self._last_elapsed_ms) / 1000.0)
        self._last_elapsed_ms = now_ms

        for bar in self._bars:
            # 更新相位
            bar['phase'] += (2 * math.pi) * (dt_s / bar['duration'])
            if bar['phase'] > 2 * math.pi:
                bar['phase'] -= 2 * math.pi

            # 计算当前高度（正弦波在min和max之间）
            sine_value = (math.sin(bar['phase']) + 1) / 2  # 0-1
            bar['current_height'] = bar['min_height'] + (bar['max_height'] - bar['min_height']) * sine_value

        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        """绘制竖条波形"""
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        height = self.height()
        bar_width = 3
        spacing = 3

        # 绘制每个条
        for i, bar in enumerate(self._bars):
            x = i * (bar_width + spacing)
            bar_h = bar['current_height']
            y = (height - bar_h) / 2

            # 白色圆角矩形
            rect = QtCore.QRectF(x, y, bar_width, bar_h)
            painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 2, 2)


class LoadingDotsWidget(QtWidgets.QWidget):
    """加载动画 - 三个点（gemini风格）"""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._duration_s = 1.5
        self._delays_s = [0.0, 0.2, 0.4]
        self._dot_diameter = 6
        self._gap = 6
        width = self._dot_diameter * 3 + self._gap * 2
        self.setFixedSize(width, 10)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._clock = QtCore.QElapsedTimer()
        self._clock.start()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)  # 更顺滑
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def _pulse_value(self, elapsed_s: float, delay_s: float) -> float:
        t = elapsed_s - delay_s
        if t < 0:
            return 0.0
        progress = (t % self._duration_s) / self._duration_s  # 0..1
        return 0.5 - 0.5 * math.cos(2 * math.pi * progress)  # 0..1..0（平滑）

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        """绘制三个点"""
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        elapsed_s = self._clock.elapsed() / 1000.0
        center_y = self.height() / 2
        radius = self._dot_diameter / 2

        x = radius
        for delay_s in self._delays_s:
            pulse = self._pulse_value(elapsed_s, delay_s)
            opacity = 0.3 + 0.7 * pulse
            scale = 1.0 + 0.2 * pulse

            color = QtGui.QColor(255, 255, 255)
            color.setAlphaF(opacity)

            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)

            scaled_radius = radius * scale
            painter.drawEllipse(QtCore.QRectF(x - scaled_radius, center_y - scaled_radius, 2 * scaled_radius, 2 * scaled_radius))
            x += self._dot_diameter + self._gap


class RoundIconButton(QtWidgets.QPushButton):
    """圆形图标按钮（匹配示例HTML的 32px 圆按钮与按下缩放）"""

    def __init__(self, text: str, bg_color: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(text, parent)
        self._bg = QtGui.QColor(bg_color)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        font = self.font()
        font.setPixelSize(16)
        font.setBold(True)
        self.setFont(font)
        self.setFlat(True)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        scale = 0.9 if self.isDown() else 1.0
        rect = QtCore.QRectF(self.rect())
        center = rect.center()

        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(self._bg))
        painter.drawEllipse(rect)

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self.text())


class CapsuleWidget(QtWidgets.QWidget):
    """黑色胶囊容器（匹配示例HTML的圆角与透明背景）"""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0)))

        # 圆角半径 = 高度的一半，形成完美的胶囊形状
        rect = QtCore.QRectF(self.rect())
        corner_radius = rect.height() / 2
        painter.drawRoundedRect(rect, corner_radius, corner_radius)


class RecordingIndicator(QtWidgets.QWidget):
    """录音指示器窗口 - 参考闪电说设计"""

    cancel_clicked = QtCore.pyqtSignal()
    confirm_clicked = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "hold"  # hold, toggle, processing, connecting
        self._shadow_blur = 15
        self._shadow_offset_y = 4
        self._shadow_pad = self._shadow_blur + abs(self._shadow_offset_y)
        self._pending_position: Optional[QtCore.QPoint] = None
        self._layer_shell_surface: Optional[object] = None
        self._setup_window()
        self._build_ui()
        self._setup_x11_properties()

    def _setup_window(self) -> None:
        """设置窗口基本属性"""
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        # Tool + DoNotAcceptFocus 让指示器不抢焦点、不占任务栏（跨平台）
        flags |= Qt.WindowType.Tool
        flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        # X11 绕过窗口管理器仅在 X11 下可用，Wayland 下会导致窗口不显示
        if sys.platform.startswith("linux"):
            session = (QtWidgets.QApplication.instance().platformName() or "").lower()
            if "xcb" in session or "x11" in session:
                flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)

        # 应用里有全局浅色 QSS（QWidget background: ...），会把指示器内部刷成白色；
        # 这里强制把指示器子树背景设为透明，让胶囊自绘的黑底生效。
        self.setObjectName("recordingIndicatorRoot")
        self.setStyleSheet(
            """
            #recordingIndicatorRoot,
            #recordingIndicatorRoot QWidget { background: transparent; }
            """
        )

    def _setup_x11_properties(self) -> None:
        """设置X11窗口属性"""
        if sys.platform.startswith("linux"):
            try:
                win_id = int(self.winId())

                try:
                    from Xlib import display

                    d = display.Display()
                    window = d.create_resource_object("window", win_id)

                    atom = d.intern_atom("_NET_WM_WINDOW_TYPE")
                    window_type = d.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")
                    window.change_property(atom, d.intern_atom("ATOM"), 32, [window_type])

                    state_atom = d.intern_atom("_NET_WM_STATE")
                    state_above = d.intern_atom("_NET_WM_STATE_ABOVE")
                    state_skip_taskbar = d.intern_atom("_NET_WM_STATE_SKIP_TASKBAR")
                    state_skip_pager = d.intern_atom("_NET_WM_STATE_SKIP_PAGER")
                    window.change_property(
                        state_atom,
                        d.intern_atom("ATOM"),
                        32,
                        [state_above, state_skip_taskbar, state_skip_pager],
                    )

                    try:
                        wm_hints = window.get_wm_hints()
                        if wm_hints:
                            wm_hints.flags |= 1
                            wm_hints.input = 0
                            window.set_wm_hints(wm_hints)
                    except Exception:
                        pass

                    d.sync()
                    d.close()
                except ImportError:
                    pass
            except Exception as e:
                print(f"Warning: Failed to set X11 properties: {e}")

    def _build_ui(self) -> None:
        """构建UI（gemini风格）"""
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(self._shadow_pad, self._shadow_pad, self._shadow_pad, self._shadow_pad)
        outer.setSpacing(0)

        # 胶囊 + 阴影（匹配示例HTML box-shadow）
        self._capsule = CapsuleWidget()
        shadow = QtWidgets.QGraphicsDropShadowEffect(self._capsule)
        shadow.setBlurRadius(self._shadow_blur)
        shadow.setOffset(0, self._shadow_offset_y)
        shadow.setColor(QtGui.QColor(0, 0, 0, int(255 * 0.3)))
        self._capsule.setGraphicsEffect(shadow)
        outer.addWidget(self._capsule, 0, Qt.AlignmentFlag.AlignCenter)

        capsule_layout = QtWidgets.QStackedLayout(self._capsule)
        capsule_layout.setContentsMargins(0, 0, 0, 0)
        capsule_layout.setSpacing(0)

        self._page_hold = QtWidgets.QWidget()
        self._page_toggle = QtWidgets.QWidget()
        self._page_processing = QtWidgets.QWidget()
        self._page_connecting = QtWidgets.QWidget()
        capsule_layout.addWidget(self._page_hold)
        capsule_layout.addWidget(self._page_toggle)
        capsule_layout.addWidget(self._page_processing)
        capsule_layout.addWidget(self._page_connecting)
        self._capsule_stack = capsule_layout

        # 波浪动画（hold模式 11条，toggle模式 15条）
        self.waveform_hold = AudioWaveformWidget(bar_count=11)
        self.waveform_toggle = AudioWaveformWidget(bar_count=15)
        self.loading_dots = LoadingDotsWidget()

        # Hold（录音中）：仅波形，水平/垂直居中，无内边距
        hold_layout = QtWidgets.QHBoxLayout(self._page_hold)
        hold_layout.setContentsMargins(0, 0, 0, 0)
        hold_layout.setSpacing(0)
        hold_layout.addStretch(1)
        hold_layout.addWidget(self.waveform_hold, 0, Qt.AlignmentFlag.AlignCenter)
        hold_layout.addStretch(1)

        # Processing（处理中）：仅三点，居中
        processing_layout = QtWidgets.QHBoxLayout(self._page_processing)
        processing_layout.setContentsMargins(0, 0, 0, 0)
        processing_layout.setSpacing(0)
        processing_layout.addStretch(1)
        processing_layout.addWidget(self.loading_dots, 0, Qt.AlignmentFlag.AlignCenter)
        processing_layout.addStretch(1)

        # Connecting（连接中）：三点加载动画（和processing一样的外观）
        self.connecting_dots = LoadingDotsWidget()
        connecting_layout = QtWidgets.QHBoxLayout(self._page_connecting)
        connecting_layout.setContentsMargins(0, 0, 0, 0)
        connecting_layout.setSpacing(0)
        connecting_layout.addStretch(1)
        connecting_layout.addWidget(self.connecting_dots, 0, Qt.AlignmentFlag.AlignCenter)
        connecting_layout.addStretch(1)

        # Toggle（自由录音）：左右按钮 + 中间波形，左右各 10px padding，space-between
        self.cancel_btn = RoundIconButton("✕", "#eb4d3d")
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self.confirm_btn = RoundIconButton("✓", "#2ecc71")
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)

        toggle_layout = QtWidgets.QHBoxLayout(self._page_toggle)
        toggle_layout.setContentsMargins(10, 0, 10, 0)
        toggle_layout.setSpacing(0)
        toggle_layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        toggle_layout.addStretch(1)
        toggle_layout.addWidget(self.waveform_toggle, 0, Qt.AlignmentFlag.AlignCenter)
        toggle_layout.addStretch(1)
        toggle_layout.addWidget(self.confirm_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._update_ui()

    def _update_ui(self) -> None:
        """根据模式更新UI（gemini风格尺寸）"""
        if self._mode == "hold":
            self._capsule_stack.setCurrentWidget(self._page_hold)
            capsule_w, capsule_h = 120, 50

        elif self._mode == "processing":
            self._capsule_stack.setCurrentWidget(self._page_processing)
            capsule_w, capsule_h = 120, 50

        elif self._mode == "connecting":
            self._capsule_stack.setCurrentWidget(self._page_connecting)
            capsule_w, capsule_h = 120, 50

        else:  # toggle
            self._capsule_stack.setCurrentWidget(self._page_toggle)
            capsule_w, capsule_h = 220, 50

        self._capsule.setFixedSize(capsule_w, capsule_h)
        self.setFixedSize(capsule_w + self._shadow_pad * 2, capsule_h + self._shadow_pad * 2)
        self._update_layer_shell_geometry()

    def set_mode(self, mode: str) -> None:
        """设置模式: 'hold', 'toggle', 'processing', 'connecting'"""
        self._mode = mode
        self._update_ui()

    def _is_wayland_session(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        session = (QtWidgets.QApplication.instance().platformName() or "").lower()
        return "wayland" in session

    def _ensure_wayland_layer_shell(self) -> bool:
        if not self._is_wayland_session():
            return False
        if self._layer_shell_surface is not None:
            return True
        try:
            from PyQt6.QtWaylandClient import QWaylandLayerShellSurface
        except Exception:
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
            return False

        self._layer_shell_surface = surface
        self._configure_layer_shell_surface()
        return True

    def _ensure_window_handle(self) -> Optional[QtGui.QWindow]:
        window = self.windowHandle()
        if window is None:
            # Force native window creation so layer-shell can attach before first show.
            self.winId()
            window = self.windowHandle()
        return window

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
            try:
                anchors = anchor_enum.Left | anchor_enum.Right | anchor_enum.Bottom
                surface.setAnchor(anchors)
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

    def _update_layer_shell_geometry(self) -> None:
        if self._layer_shell_surface is None:
            return
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return

        screen_geometry = screen.availableGeometry()
        total_w = self.width()
        margin_x = max(0, (screen_geometry.width() - total_w) // 2)
        bottom_margin = max(0, 80 - self._shadow_pad)

        if hasattr(self._layer_shell_surface, "setMargins"):
            try:
                self._layer_shell_surface.setMargins(QtCore.QMargins(margin_x, 0, margin_x, bottom_margin))
            except Exception:
                pass

        for method_name in ("setSize", "setDesiredSize"):
            method = getattr(self._layer_shell_surface, method_name, None)
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

    def show_at_bottom_center(self) -> None:
        """显示在屏幕底部中间"""
        if self._is_wayland_session():
            self._ensure_wayland_layer_shell()
            if self._layer_shell_surface is not None:
                self._update_layer_shell_geometry()
            else:
                self._position_with_move()
            self.show()
            self.raise_()
        else:
            self._position_with_move()
            self.show()
            self.raise_()
        QtCore.QTimer.singleShot(0, self._setup_x11_properties)

    def _position_with_move(self) -> None:
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        screen_geometry = screen.availableGeometry()
        capsule_w = self._capsule.width()
        capsule_h = self._capsule.height()
        x = screen_geometry.x() + (screen_geometry.width() - capsule_w) // 2 - self._shadow_pad
        y = screen_geometry.y() + screen_geometry.height() - capsule_h - 80 - self._shadow_pad
        self._pending_position = QtCore.QPoint(x, y)
        self._apply_position(self._pending_position)

    def _apply_position(self, pos: QtCore.QPoint) -> None:
        """在窗口可用时应用位置（Wayland 可能需要显示后再设置）"""
        self.move(pos)
        window_handle = self.windowHandle()
        if window_handle is not None:
            window_handle.setPosition(pos)

    def _apply_pending_position(self) -> None:
        if self._pending_position is None:
            return
        self._apply_position(self._pending_position)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        """窗口显示事件"""
        super().showEvent(event)
        if self._ensure_wayland_layer_shell():
            self._update_layer_shell_geometry()
        else:
            QtCore.QTimer.singleShot(0, self._apply_pending_position)
        QtCore.QTimer.singleShot(10, self._setup_x11_properties)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class RecordingIndicatorManager(QtCore.QObject):
    """录音指示器管理器"""

    cancel_requested = QtCore.pyqtSignal()
    confirm_requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._indicator: Optional[RecordingIndicator] = None

    def show_hold_mode(self) -> None:
        """显示按住模式指示器"""
        if self._indicator is None:
            self._indicator = RecordingIndicator()
            self._indicator.cancel_clicked.connect(self.cancel_requested.emit)
            self._indicator.confirm_clicked.connect(self.confirm_requested.emit)

        self._indicator.set_mode("hold")
        self._indicator.show_at_bottom_center()

    def show_toggle_mode(self) -> None:
        """显示切换模式指示器"""
        if self._indicator is None:
            self._indicator = RecordingIndicator()
            self._indicator.cancel_clicked.connect(self.cancel_requested.emit)
            self._indicator.confirm_clicked.connect(self.confirm_requested.emit)

        self._indicator.set_mode("toggle")
        self._indicator.show_at_bottom_center()

    def show_processing(self) -> None:
        """显示处理中状态"""
        if self._indicator is None:
            self._indicator = RecordingIndicator()
            self._indicator.cancel_clicked.connect(self.cancel_requested.emit)
            self._indicator.confirm_clicked.connect(self.confirm_requested.emit)

        self._indicator.set_mode("processing")
        self._indicator.show_at_bottom_center()

    def show_connecting(self) -> None:
        """显示连接中状态"""
        if self._indicator is None:
            self._indicator = RecordingIndicator()
            self._indicator.cancel_clicked.connect(self.cancel_requested.emit)
            self._indicator.confirm_clicked.connect(self.confirm_requested.emit)

        self._indicator.set_mode("connecting")
        self._indicator.show_at_bottom_center()

    def hide(self) -> None:
        """隐藏指示器"""
        if self._indicator:
            self._indicator.hide()

    def cleanup(self) -> None:
        """清理资源"""
        if self._indicator:
            self._indicator.close()
            self._indicator.deleteLater()
            self._indicator = None
