"""macOS 全局快捷键监听器 - 使用 Quartz CGEventTap"""

import threading
from typing import Dict, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal

from hotkey.config import GlobalHotkeySettings


class MacOSHotkeyListenerThread(QThread):
    """macOS 专用的全局快捷键监听器，使用 Quartz CGEventTap"""

    # Qt信号用于线程安全通信
    hotkey_pressed = pyqtSignal(str, str)  # (hotkey_id, action: "press"/"release"/"toggle")
    mouse_button_event = pyqtSignal(str, str)  # (button_id, action: "press"/"release")
    snippet_triggered = pyqtSignal(str, str)  # (snippet_id, text)
    listener_error = pyqtSignal(str)

    def __init__(self, config: GlobalHotkeySettings) -> None:
        super().__init__()
        self._config = config
        self._stop_event = threading.Event()
        self._tap = None
        self._run_loop_source = None

        # 状态跟踪
        self._pressed_keys: Set[str] = set()
        self._active_combos: Dict[str, bool] = {}

    def stop(self) -> None:
        """请求停止监听器"""
        self._stop_event.set()

    def run(self) -> None:
        """主线程循环 - 运行 Quartz 事件监听"""
        try:
            import Quartz
            from Quartz import (
                CGEventTapCreate,
                CGEventTapEnable,
                CFMachPortCreateRunLoopSource,
                CFRunLoopGetCurrent,
                CFRunLoopAddSource,
                CFRunLoopRun,
                CFRunLoopStop,
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                kCGEventKeyDown,
                kCGEventKeyUp,
                kCGEventFlagsChanged,
                kCGEventOtherMouseDown,
                kCGEventOtherMouseUp,
                kCFRunLoopCommonModes,
            )

            # 事件类型掩码
            event_mask = (
                (1 << kCGEventKeyDown) |
                (1 << kCGEventKeyUp) |
                (1 << kCGEventFlagsChanged) |
                (1 << kCGEventOtherMouseDown) |
                (1 << kCGEventOtherMouseUp)
            )

            # 创建事件回调
            def event_callback(proxy, event_type, event, refcon):
                try:
                    if event_type == kCGEventKeyDown:
                        self._handle_key_down(event)
                    elif event_type == kCGEventKeyUp:
                        self._handle_key_up(event)
                    elif event_type == kCGEventFlagsChanged:
                        self._handle_flags_changed(event)
                    elif event_type == kCGEventOtherMouseDown:
                        self._handle_mouse_down(event)
                    elif event_type == kCGEventOtherMouseUp:
                        self._handle_mouse_up(event)
                except Exception as e:
                    self.listener_error.emit(f"事件处理错误: {e}")
                return event

            # 创建事件 tap
            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                event_mask,
                event_callback,
                None
            )

            if self._tap is None:
                self.listener_error.emit(
                    "全局快捷键需要辅助功能权限。\n\n"
                    "请打开「系统设置 → 隐私与安全性 → 辅助功能」，\n"
                    "然后允许本应用控制您的电脑。"
                )
                return

            # 创建 RunLoop source
            self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            run_loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(run_loop, self._run_loop_source, kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)

            # 启动监听循环
            while not self._stop_event.is_set():
                # 运行 RunLoop 一小段时间
                Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.1, False)

        except ImportError as e:
            self.listener_error.emit(
                f"无法导入 Quartz 库: {e}\n"
                "请运行: pip install pyobjc-framework-Quartz"
            )
        except Exception as e:
            error_msg = str(e)
            if "accessibility" in error_msg.lower() or "trusted" in error_msg.lower():
                self.listener_error.emit(
                    "全局快捷键需要辅助功能权限。\n\n"
                    "请打开「系统设置 → 隐私与安全性 → 辅助功能」，\n"
                    "然后允许本应用控制您的电脑。"
                )
            else:
                self.listener_error.emit(f"启动监听器失败: {e}")

    def _get_key_name_from_keycode(self, keycode: int) -> Optional[str]:
        """将 macOS keycode 转换为标准键名"""
        # macOS 虚拟按键码映射
        keycode_map = {
            # 字母键 (A-Z)
            0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
            8: "c", 9: "v", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
            16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6",
            23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0",
            31: "o", 32: "u", 34: "i", 35: "p", 37: "l", 38: "j", 40: "k",
            45: "n", 46: "m",
            # 特殊键
            36: "enter",
            48: "tab",
            49: "space",
            51: "backspace",
            53: "esc",
            117: "delete",
            115: "home",
            119: "end",
            116: "page_up",
            121: "page_down",
            123: "left",
            124: "right",
            125: "down",
            126: "up",
            # 功能键
            122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6",
            98: "f7", 100: "f8", 101: "f9", 109: "f10", 103: "f11", 111: "f12",
        }
        return keycode_map.get(keycode)

    def _get_modifier_names(self, flags: int) -> Set[str]:
        """从修饰键标志位获取按下的修饰键"""
        import Quartz

        modifiers = set()

        if flags & Quartz.kCGEventFlagMaskControl:
            modifiers.add("ctrl")
        if flags & Quartz.kCGEventFlagMaskCommand:
            modifiers.add("super")
        if flags & Quartz.kCGEventFlagMaskAlternate:
            modifiers.add("alt")
        if flags & Quartz.kCGEventFlagMaskShift:
            modifiers.add("shift")

        return modifiers

    def _handle_key_down(self, event) -> None:
        """处理按键按下"""
        import Quartz

        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        key_name = self._get_key_name_from_keycode(keycode)

        if key_name:
            self._pressed_keys.add(key_name)

        # 获取当前修饰键状态
        flags = Quartz.CGEventGetFlags(event)
        modifier_keys = self._get_modifier_names(flags)
        all_pressed = self._pressed_keys | modifier_keys

        self._check_hotkeys(all_pressed)
        self._check_snippets(all_pressed)

    def _handle_key_up(self, event) -> None:
        """处理按键释放"""
        import Quartz

        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        key_name = self._get_key_name_from_keycode(keycode)

        # 获取当前修饰键状态
        flags = Quartz.CGEventGetFlags(event)
        modifier_keys = self._get_modifier_names(flags)

        self._check_hotkey_releases(key_name, modifier_keys)

        if key_name:
            self._pressed_keys.discard(key_name)

    def _handle_flags_changed(self, event) -> None:
        """处理修饰键状态变化"""
        import Quartz

        flags = Quartz.CGEventGetFlags(event)
        current_modifiers = self._get_modifier_names(flags)

        # 检测哪些修饰键被释放
        old_modifiers = self._pressed_keys & {"ctrl", "super", "alt", "shift"}
        released_modifiers = old_modifiers - current_modifiers

        for mod in released_modifiers:
            self._check_hotkey_releases(mod, current_modifiers)

        # 更新修饰键状态
        self._pressed_keys -= {"ctrl", "super", "alt", "shift"}
        self._pressed_keys |= current_modifiers

        # 检查快捷键
        all_pressed = self._pressed_keys | current_modifiers
        self._check_hotkeys(all_pressed)

    def _handle_mouse_down(self, event) -> None:
        """处理鼠标按下"""
        import Quartz

        button_number = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGMouseEventButtonNumber
        )

        # 按钮 2 是中键
        if button_number == 2:
            self._handle_middle_mouse("press")

    def _handle_mouse_up(self, event) -> None:
        """处理鼠标释放"""
        import Quartz

        button_number = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGMouseEventButtonNumber
        )

        if button_number == 2:
            self._handle_middle_mouse("release")

    def _handle_middle_mouse(self, action: str) -> None:
        """处理鼠标中键事件"""
        for mb_id, config in self._config.mouse_hotkeys.items():
            if not config.enabled or config.button != "middle":
                continue

            if action == "press":
                if config.mode == "hold":
                    self.mouse_button_event.emit(mb_id, "press")
                else:
                    self.mouse_button_event.emit(mb_id, "toggle")
            elif action == "release":
                if config.mode == "hold":
                    self.mouse_button_event.emit(mb_id, "release")

    @staticmethod
    def _modifier_keys() -> Set[str]:
        return {"ctrl", "right_ctrl", "super", "right_super", "alt", "right_alt", "shift", "right_shift"}

    def _check_hotkeys(self, all_pressed: Set[str]) -> None:
        """检查是否触发了快捷键"""
        for hotkey_id, config in self._config.keyboard_hotkeys.items():
            if not config.enabled:
                continue

            required_keys = set(config.keys)
            if required_keys.issubset(all_pressed):
                if hotkey_id not in self._active_combos:
                    self._active_combos[hotkey_id] = True

                    if config.mode == "hold":
                        self.hotkey_pressed.emit(hotkey_id, "press")
                    else:
                        self.hotkey_pressed.emit(hotkey_id, "toggle")

    def _check_snippets(self, all_pressed: Set[str]) -> None:
        """检查是否触发了文本片段"""
        for snip_id, snip_config in self._config.text_snippets.items():
            if not snip_config.enabled:
                continue

            required_keys = set(snip_config.keys)
            if required_keys == all_pressed:
                snip_key = f"snippet:{snip_id}"
                if snip_key not in self._active_combos:
                    self._active_combos[snip_key] = True
                    self.snippet_triggered.emit(snip_id, snip_config.text)

    def _check_hotkey_releases(self, released_key: Optional[str], current_modifiers: Set[str]) -> None:
        """检查是否释放了激活的快捷键"""
        modifier_keys = self._modifier_keys()

        for hotkey_id, config in self._config.keyboard_hotkeys.items():
            if hotkey_id not in self._active_combos:
                continue

            if released_key and released_key in config.keys:
                if config.mode == "hold":
                    non_modifier_keys = {k for k in config.keys if k not in modifier_keys}
                    if non_modifier_keys:
                        if released_key not in non_modifier_keys:
                            continue

                del self._active_combos[hotkey_id]

                if config.mode == "hold":
                    self.hotkey_pressed.emit(hotkey_id, "release")

        # 清理片段快捷键状态
        for snip_id, snip_config in self._config.text_snippets.items():
            snip_key = f"snippet:{snip_id}"
            if snip_key in self._active_combos:
                if released_key and released_key in snip_config.keys:
                    del self._active_combos[snip_key]
