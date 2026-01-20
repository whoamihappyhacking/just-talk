"""快捷键设置UI对话框"""

from typing import Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt

from hotkey.config import GlobalHotkeySettings, HotkeyConfig, MouseButtonConfig


class HotkeySettingsDialog(QtWidgets.QDialog):
    """全局快捷键设置对话框"""

    def __init__(
        self,
        current_config: GlobalHotkeySettings,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("全局快捷键设置")
        self.setModal(True)
        self.setMinimumSize(600, 500)

        # 复制配置以便编辑
        self._config = GlobalHotkeySettings(
            keyboard_hotkeys=current_config.keyboard_hotkeys.copy(),
            mouse_hotkeys=current_config.mouse_hotkeys.copy(),
        )

        self._hotkey_widgets = {}
        self._mouse_widgets = {}

        self._build_ui()

    def _build_ui(self) -> None:
        """构建UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # 说明文字
        info = QtWidgets.QLabel(
            "配置全局快捷键，即使应用在后台也能使用。\n"
            "支持按住模式（按住时录音）和切换模式（点击切换状态）。"
        )
        info.setStyleSheet("color: #6b7280; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 键盘快捷键部分
        kb_group = QtWidgets.QGroupBox("键盘快捷键")
        kb_layout = QtWidgets.QVBoxLayout(kb_group)
        kb_layout.setSpacing(10)

        # 主快捷键
        primary_config = self._config.keyboard_hotkeys.get("primary")
        if primary_config:
            primary_widget = self._create_hotkey_widget(
                "primary", "主快捷键（Ctrl+Super 按住模式）", primary_config, True
            )
            kb_layout.addWidget(primary_widget)
            self._hotkey_widgets["primary"] = primary_widget

        # 自由说模式
        freehand_config = self._config.keyboard_hotkeys.get("freehand")
        if freehand_config:
            freehand_widget = self._create_hotkey_widget(
                "freehand", "自由说模式（Alt 切换模式）", freehand_config, False
            )
            kb_layout.addWidget(freehand_widget)
            self._hotkey_widgets["freehand"] = freehand_widget

        layout.addWidget(kb_group)

        # 鼠标按键部分
        mouse_group = QtWidgets.QGroupBox("鼠标按键")
        mouse_layout = QtWidgets.QVBoxLayout(mouse_group)
        mouse_layout.setSpacing(10)

        # 鼠标中键
        middle_config = self._config.mouse_hotkeys.get("middle_button")
        if middle_config:
            middle_widget = self._create_mouse_widget(
                "middle_button", "鼠标中键", middle_config
            )
            mouse_layout.addWidget(middle_widget)
            self._mouse_widgets["middle_button"] = middle_widget

        layout.addWidget(mouse_group)

        # 按钮行
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        reset_btn = QtWidgets.QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(reset_btn)

        cancel_btn = QtWidgets.QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QtWidgets.QPushButton("保存")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _create_hotkey_widget(
        self,
        hotkey_id: str,
        label: str,
        config: HotkeyConfig,
        fixed_mode: bool = False,
    ) -> QtWidgets.QWidget:
        """创建快捷键配置部件"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 启用checkbox
        enabled_cb = QtWidgets.QCheckBox()
        enabled_cb.setChecked(config.enabled)
        layout.addWidget(enabled_cb)

        # 标签
        label_widget = QtWidgets.QLabel(label)
        label_widget.setMinimumWidth(180)
        layout.addWidget(label_widget)

        # 快捷键显示/编辑按钮
        keys_text = self._format_keys(config.keys)
        keys_btn = QtWidgets.QPushButton(keys_text)
        keys_btn.setMinimumWidth(150)
        keys_btn.clicked.connect(
            lambda: self._capture_hotkey(hotkey_id, keys_btn, config.keys)
        )
        layout.addWidget(keys_btn)

        # 模式选择（如果不是固定模式）
        mode_combo = QtWidgets.QComboBox()
        mode_combo.addItem("按住模式", "hold")
        mode_combo.addItem("切换模式", "toggle")
        idx = 0 if config.mode == "hold" else 1
        mode_combo.setCurrentIndex(idx)
        mode_combo.setVisible(not fixed_mode)
        layout.addWidget(mode_combo)

        layout.addStretch()

        # 保存引用
        widget._enabled_cb = enabled_cb
        widget._keys_btn = keys_btn
        widget._mode_combo = mode_combo
        widget._current_keys = config.keys.copy()

        return widget

    def _create_mouse_widget(
        self, button_id: str, label: str, config: MouseButtonConfig
    ) -> QtWidgets.QWidget:
        """创建鼠标按键配置部件"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 启用checkbox
        enabled_cb = QtWidgets.QCheckBox()
        enabled_cb.setChecked(config.enabled)
        layout.addWidget(enabled_cb)

        # 标签
        label_widget = QtWidgets.QLabel(label)
        label_widget.setMinimumWidth(180)
        layout.addWidget(label_widget)

        # 按钮显示（不可编辑）
        button_label = QtWidgets.QLabel(self._format_button(config.button))
        button_label.setStyleSheet(
            "padding: 6px 12px; border: 1px solid #d1d5db; "
            "border-radius: 6px; background: #f9fafb;"
        )
        button_label.setMinimumWidth(150)
        layout.addWidget(button_label)

        # 模式选择
        mode_combo = QtWidgets.QComboBox()
        mode_combo.addItem("切换模式", "toggle")
        mode_combo.addItem("按住模式", "hold")
        idx = 0 if config.mode == "toggle" else 1
        mode_combo.setCurrentIndex(idx)
        layout.addWidget(mode_combo)

        layout.addStretch()

        # 保存引用
        widget._enabled_cb = enabled_cb
        widget._mode_combo = mode_combo

        return widget

    def _format_keys(self, keys: list) -> str:
        """格式化按键列表为显示文本"""
        display_map = {
            "ctrl": "Ctrl",
            "right_ctrl": "右Ctrl",
            "super": "Super",
            "alt": "Alt",
            "shift": "Shift",
            "space": "空格",
        }

        return " + ".join(display_map.get(k, k.upper()) for k in keys)

    def _format_button(self, button: str) -> str:
        """格式化鼠标按钮为显示文本"""
        button_map = {"middle": "鼠标中键"}
        return button_map.get(button, button)

    def _capture_hotkey(
        self, hotkey_id: str, button: QtWidgets.QPushButton, current_keys: list
    ) -> None:
        """捕获快捷键组合"""
        dialog = HotkeyCaptureDialog(current_keys, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_keys = dialog.get_captured_keys()
            if new_keys:
                button.setText(self._format_keys(new_keys))
                # 更新配置
                widget = self._hotkey_widgets.get(hotkey_id)
                if widget:
                    widget._current_keys = new_keys

    def _reset_defaults(self) -> None:
        """恢复默认配置"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "确认",
            "确定要恢复默认配置吗？",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._config = GlobalHotkeySettings.get_defaults()
            # 关闭并重新打开对话框
            self.accept()

    def _save_and_close(self) -> None:
        """保存配置并关闭"""
        # 收集键盘快捷键配置
        for hk_id, widget in self._hotkey_widgets.items():
            self._config.keyboard_hotkeys[hk_id] = HotkeyConfig(
                enabled=widget._enabled_cb.isChecked(),
                keys=widget._current_keys,
                mode=widget._mode_combo.currentData(),
            )

        # 收集鼠标按键配置
        for mb_id, widget in self._mouse_widgets.items():
            old_config = self._config.mouse_hotkeys[mb_id]
            self._config.mouse_hotkeys[mb_id] = MouseButtonConfig(
                enabled=widget._enabled_cb.isChecked(),
                button=old_config.button,  # 按钮类型不变
                mode=widget._mode_combo.currentData(),
            )

        self.accept()

    def get_config(self) -> GlobalHotkeySettings:
        """获取配置"""
        return self._config


class HotkeyCaptureDialog(QtWidgets.QDialog):
    """快捷键捕获对话框"""

    def __init__(
        self, current_keys: list, parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("按下快捷键组合")
        self.setModal(True)
        self.setFixedSize(400, 200)

        self._captured_keys = []
        self._current_keys = set()

        self._build_ui()

        # 安装事件过滤器
        self.installEventFilter(self)

    def _build_ui(self) -> None:
        """构建UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(20)

        # 说明
        instruction = QtWidgets.QLabel(
            "请按下您想要设置的快捷键组合\n"
            "（例如：Ctrl + Super 或 右Ctrl）\n\n"
            "按 Esc 取消，按 Enter 确认"
        )
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet("color: #6b7280; font-size: 13px;")
        layout.addWidget(instruction)

        # 预览
        self.preview = QtWidgets.QLabel("等待输入...")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "font-size: 16px; font-weight: bold; "
            "padding: 12px; background: #f3f4f6; "
            "border-radius: 8px; color: #111827;"
        )
        layout.addWidget(self.preview)

        layout.addStretch()

    def eventFilter(
        self, obj: QtCore.QObject, event: QtCore.QEvent
    ) -> bool:  # noqa: N802
        """事件过滤器 - 捕获按键"""
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()

            # ESC取消
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True

            # Enter确认
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                if self._captured_keys:
                    self.accept()
                return True

            # 转换按键
            key_name = self._qt_key_to_name(key)
            if key_name and key_name not in self._current_keys:
                self._current_keys.add(key_name)
                self._captured_keys = sorted(self._current_keys)
                self._update_preview()

            return True

        elif event.type() == QtCore.QEvent.Type.KeyRelease:
            return True

        return super().eventFilter(obj, event)

    def _qt_key_to_name(self, key: int) -> Optional[str]:
        """将Qt按键转换为标准名称"""
        key_map = {
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Meta: "super",  # Windows键/Super键
            Qt.Key.Key_Alt: "alt",
            Qt.Key.Key_Shift: "shift",
            Qt.Key.Key_Space: "space",
        }

        if key in key_map:
            return key_map[key]

        # 检查是否是字母数字键
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).lower()

        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)

        return None

    def _update_preview(self) -> None:
        """更新预览显示"""
        if self._captured_keys:
            display_map = {
                "ctrl": "Ctrl",
                "super": "Super",
                "alt": "Alt",
                "shift": "Shift",
                "space": "空格",
            }
            display = " + ".join(
                display_map.get(k, k.upper()) for k in self._captured_keys
            )
            self.preview.setText(display)
        else:
            self.preview.setText("等待输入...")

    def get_captured_keys(self) -> list:
        """获取捕获的按键"""
        return self._captured_keys
