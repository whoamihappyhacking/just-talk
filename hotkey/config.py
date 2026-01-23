"""配置数据结构定义"""

import sys
from dataclasses import dataclass, field
from typing import Dict, List

# macOS 平台检测
_IS_MACOS = sys.platform == "darwin"


@dataclass
class HotkeyConfig:
    """单个键盘快捷键配置"""

    enabled: bool
    keys: List[str]  # 内部使用统一格式: "ctrl", "super", "alt", "shift"
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
class TextSnippetConfig:
    """预设文本片段配置"""

    enabled: bool
    keys: List[str]  # 快捷键组合，如 ["ctrl", "shift", "1"]
    text: str  # 要输入的文本内容
    name: str = ""  # 片段名称（可选，用于UI显示）

    def __post_init__(self) -> None:
        """验证配置"""
        if not self.keys:
            raise ValueError("Keys list cannot be empty")
        if not self.text:
            raise ValueError("Text cannot be empty")


@dataclass
class GlobalHotkeySettings:
    """完整快捷键设置"""

    keyboard_hotkeys: Dict[str, HotkeyConfig] = field(default_factory=dict)
    mouse_hotkeys: Dict[str, MouseButtonConfig] = field(default_factory=dict)
    text_snippets: Dict[str, TextSnippetConfig] = field(default_factory=dict)

    @classmethod
    def get_defaults(cls) -> "GlobalHotkeySettings":
        """创建默认配置

        内部键名使用统一格式：ctrl, super, alt, shift
        macOS 上显示时转换为：Control, Command, Option, Shift
        """
        # 所有平台使用相同的内部键名
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
            text_snippets={},
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
            "text_snippets": {
                snip_id: {
                    "enabled": snip.enabled,
                    "keys": snip.keys,
                    "text": snip.text,
                    "name": snip.name,
                }
                for snip_id, snip in self.text_snippets.items()
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

        text_snippets = {
            snip_id: TextSnippetConfig(**snip_data)
            for snip_id, snip_data in data.get("text_snippets", {}).items()
        }

        return cls(
            keyboard_hotkeys=keyboard_hotkeys,
            mouse_hotkeys=mouse_hotkeys,
            text_snippets=text_snippets,
        )
