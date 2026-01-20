"""配置数据结构定义"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class HotkeyConfig:
    """单个键盘快捷键配置"""

    enabled: bool
    keys: List[str]  # e.g., ["ctrl", "super"] or ["right_ctrl"]
    mode: str  # "hold" or "toggle"

    def __post_init__(self) -> None:
        """验证配置"""
        if self.mode not in ("hold", "toggle"):
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'hold' or 'toggle'")
        if not self.keys:
            raise ValueError("Keys list cannot be empty")


@dataclass
class MouseButtonConfig:
    """鼠标按键配置"""

    enabled: bool
    button: str  # "middle" (目前只支持鼠标中键)
    mode: str  # "hold" or "toggle"

    def __post_init__(self) -> None:
        """验证配置"""
        if self.mode not in ("hold", "toggle"):
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'hold' or 'toggle'")
        if self.button not in ("middle",):
            raise ValueError(f"Invalid button: {self.button}. Only 'middle' is supported.")


@dataclass
class GlobalHotkeySettings:
    """完整快捷键设置"""

    keyboard_hotkeys: Dict[str, HotkeyConfig] = field(default_factory=dict)
    mouse_hotkeys: Dict[str, MouseButtonConfig] = field(default_factory=dict)

    @classmethod
    def get_defaults(cls) -> "GlobalHotkeySettings":
        """创建默认配置"""
        return cls(
            keyboard_hotkeys={
                "primary": HotkeyConfig(
                    enabled=True, keys=["ctrl", "super"], mode="hold"
                ),
                "freehand": HotkeyConfig(
                    enabled=True, keys=["alt", "super"], mode="toggle"
                ),
            },
            mouse_hotkeys={
                "middle_button": MouseButtonConfig(
                    enabled=False, button="middle", mode="hold"
                )
            },
        )

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        return {
            "keyboard_hotkeys": {
                hk_id: {
                    "enabled": hk.enabled,
                    "keys": hk.keys,
                    "mode": hk.mode,
                }
                for hk_id, hk in self.keyboard_hotkeys.items()
            },
            "mouse_hotkeys": {
                mb_id: {
                    "enabled": mb.enabled,
                    "button": mb.button,
                    "mode": mb.mode,
                }
                for mb_id, mb in self.mouse_hotkeys.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalHotkeySettings":
        """从字典创建配置对象"""
        keyboard_hotkeys = {
            hk_id: HotkeyConfig(**hk_data)
            for hk_id, hk_data in data.get("keyboard_hotkeys", {}).items()
        }

        mouse_hotkeys = {
            mb_id: MouseButtonConfig(**mb_data)
            for mb_id, mb_data in data.get("mouse_hotkeys", {}).items()
        }

        return cls(keyboard_hotkeys=keyboard_hotkeys, mouse_hotkeys=mouse_hotkeys)
