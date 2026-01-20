"""快捷键管理器 - 协调监听器和应用状态"""

from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from hotkey.config import GlobalHotkeySettings
from hotkey.listener import HotkeyListenerThread


class HotkeyManager(QObject):
    """管理全局快捷键功能"""

    # 信号：请求开始/停止录音，附带模式信息
    start_recording_requested = pyqtSignal(str)  # 参数：mode ("hold" 或 "toggle")
    stop_recording_requested = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = GlobalHotkeySettings.get_defaults()
        self._listener_thread: Optional[HotkeyListenerThread] = None
        self._recording_state = "idle"  # idle, recording_hold, recording_toggle
        self._active_hotkey: Optional[str] = None
        self._enabled = True
        self._suspended = False

    def get_config(self) -> GlobalHotkeySettings:
        """获取当前配置"""
        return self._config

    def update_config(self, config: GlobalHotkeySettings) -> None:
        """更新配置并重启监听器"""
        self._config = config

        # 如果监听器正在运行，重启它
        if self._listener_thread and self._listener_thread.isRunning():
            self.stop_listening()
            if self._enabled and not self._suspended:
                self.start_listening()

    def set_enabled(self, enabled: bool) -> None:
        """启用或禁用快捷键"""
        self._enabled = enabled
        if enabled:
            if not self._suspended:
                self.start_listening()
        else:
            self.reset_state()
            self.stop_listening()

    def set_suspended(self, suspended: bool) -> None:
        """临时暂停快捷键（用于录制快捷键等场景）"""
        if self._suspended == suspended:
            return
        self._suspended = suspended
        if suspended:
            self.reset_state()
            self.stop_listening()
        else:
            if self._enabled:
                self.start_listening()

    def start_listening(self) -> None:
        """启动快捷键监听"""
        if not self._enabled or self._suspended:
            return

        if self._listener_thread and self._listener_thread.isRunning():
            return  # 已在运行

        try:
            self._listener_thread = HotkeyListenerThread(self._config)
            self._listener_thread.hotkey_pressed.connect(self._on_hotkey_event)
            self._listener_thread.mouse_button_event.connect(self._on_mouse_event)
            self._listener_thread.listener_error.connect(self._on_listener_error)
            self._listener_thread.start()
        except Exception as e:
            self.error_occurred.emit(f"启动快捷键监听失败: {e}")

    def stop_listening(self) -> None:
        """停止快捷键监听"""
        if not self._listener_thread:
            return

        try:
            self._listener_thread.stop()

            # 等待线程结束（带超时）
            if not self._listener_thread.wait(2000):  # 2秒超时
                # 超时，强制终止
                self._listener_thread.terminate()
                self._listener_thread.wait()

            self._listener_thread = None
        except Exception as e:
            self.error_occurred.emit(f"停止监听器失败: {e}")

    def _on_hotkey_event(self, hotkey_id: str, action: str) -> None:
        """处理快捷键事件"""
        if not self._enabled or self._suspended:
            return
        if action == "press":
            # 按住模式 - 开始录音
            if self._recording_state == "idle":
                self._recording_state = "recording_hold"
                self._active_hotkey = hotkey_id
                self.start_recording_requested.emit("hold")  # 传递模式

        elif action == "release":
            # 按住模式 - 停止录音
            if (
                self._recording_state == "recording_hold"
                and self._active_hotkey == hotkey_id
            ):
                self._recording_state = "idle"
                self._active_hotkey = None
                # 无论按住时长多久，都发送停止信号
                # 应用层会根据是否发送了音频数据来决定是取消还是正常提交
                self.stop_recording_requested.emit()

        elif action == "toggle":
            # 切换模式 - 切换录音状态
            if self._recording_state == "idle":
                self._recording_state = "recording_toggle"
                self._active_hotkey = hotkey_id
                self.start_recording_requested.emit("toggle")  # 传递模式
            elif (
                self._recording_state == "recording_toggle"
                and self._active_hotkey == hotkey_id
            ):
                self._recording_state = "idle"
                self._active_hotkey = None
                self.stop_recording_requested.emit()
            # 如果是不同的快捷键或处于hold状态，忽略

    def _on_mouse_event(self, button_id: str, action: str) -> None:
        """处理鼠标按键事件 - 与键盘快捷键逻辑相同"""
        if not self._enabled or self._suspended:
            return
        self._on_hotkey_event(button_id, action)

    def _on_listener_error(self, error_msg: str) -> None:
        """处理监听器错误"""
        self.error_occurred.emit(error_msg)

    def reset_state(self) -> None:
        """重置录音状态（用于错误恢复）"""
        self._recording_state = "idle"
        self._active_hotkey = None
