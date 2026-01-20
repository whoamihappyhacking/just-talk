"""配置持久化管理"""

import json
from typing import Optional

from PyQt6.QtCore import QSettings

from hotkey.config import GlobalHotkeySettings


class ConfigManager:
    """处理配置的加载和保存"""

    SETTINGS_KEY = "GlobalHotkeys/config"
    ORGANIZATION = "JustTalk"
    APPLICATION = "AsrApp"

    @staticmethod
    def save_config(config: GlobalHotkeySettings) -> None:
        """保存配置到持久化存储"""
        settings = QSettings(ConfigManager.ORGANIZATION, ConfigManager.APPLICATION)

        # 转换为JSON字符串存储
        config_dict = config.to_dict()
        config_json = json.dumps(config_dict, ensure_ascii=False, indent=2)

        settings.setValue(ConfigManager.SETTINGS_KEY, config_json)
        settings.sync()  # 确保立即写入

    @staticmethod
    def load_config() -> GlobalHotkeySettings:
        """从存储加载配置，失败则返回默认配置"""
        settings = QSettings(ConfigManager.ORGANIZATION, ConfigManager.APPLICATION)
        config_json = settings.value(ConfigManager.SETTINGS_KEY, None)

        if not config_json:
            # 首次运行，返回默认配置
            return GlobalHotkeySettings.get_defaults()

        try:
            config_dict = json.loads(config_json)
            return GlobalHotkeySettings.from_dict(config_dict)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            # 配置解析失败，返回默认配置
            print(f"Failed to load config: {e}. Using defaults.")
            return GlobalHotkeySettings.get_defaults()

    @staticmethod
    def reset_to_defaults() -> GlobalHotkeySettings:
        """重置为默认配置并保存"""
        config = GlobalHotkeySettings.get_defaults()
        ConfigManager.save_config(config)
        return config

    @staticmethod
    def get_config_location() -> str:
        """获取配置文件存储位置（用于调试）"""
        settings = QSettings(ConfigManager.ORGANIZATION, ConfigManager.APPLICATION)
        return settings.fileName()
