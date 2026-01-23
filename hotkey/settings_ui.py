"""快捷键设置UI对话框"""

import sys
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from hotkey.config import GlobalHotkeySettings, HotkeyConfig, MouseButtonConfig, TextSnippetConfig

# macOS 平台检测
_IS_MACOS = sys.platform == "darwin"


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
            text_snippets=current_config.text_snippets.copy(),
        )

        self._hotkey_widgets = {}
        self._mouse_widgets = {}
        self._snippet_widgets = {}

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
            if _IS_MACOS:
                primary_label = "主快捷键（⌃Control+⌘Command 按住模式）"
            else:
                primary_label = "主快捷键（Ctrl+Super 按住模式）"
            primary_widget = self._create_hotkey_widget(
                "primary", primary_label, primary_config, True
            )
            kb_layout.addWidget(primary_widget)
            self._hotkey_widgets["primary"] = primary_widget

        # 自由说模式
        freehand_config = self._config.keyboard_hotkeys.get("freehand")
        if freehand_config:
            if _IS_MACOS:
                freehand_label = "自由说模式（⌥Option 切换模式）"
            else:
                freehand_label = "自由说模式（Alt 切换模式）"
            freehand_widget = self._create_hotkey_widget(
                "freehand", freehand_label, freehand_config, False
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

        # 文本片段部分
        snippet_group = QtWidgets.QGroupBox("预设文本片段")
        snippet_layout = QtWidgets.QVBoxLayout(snippet_group)
        snippet_layout.setSpacing(10)

        # 片段说明
        snippet_info = QtWidgets.QLabel(
            "配置快捷键直接输入预设文本，无需录音。"
        )
        snippet_info.setStyleSheet("color: #6b7280; font-size: 11px;")
        snippet_layout.addWidget(snippet_info)

        # 片段列表容器
        self._snippets_container = QtWidgets.QWidget()
        self._snippets_layout = QtWidgets.QVBoxLayout(self._snippets_container)
        self._snippets_layout.setContentsMargins(0, 0, 0, 0)
        self._snippets_layout.setSpacing(8)

        # 加载现有片段
        for snip_id, snip_config in self._config.text_snippets.items():
            widget = self._create_snippet_widget(snip_id, snip_config)
            self._snippets_layout.addWidget(widget)
            self._snippet_widgets[snip_id] = widget

        snippet_layout.addWidget(self._snippets_container)

        # 添加新片段按钮
        add_snippet_btn = QtWidgets.QPushButton("+ 添加片段")
        add_snippet_btn.clicked.connect(self._add_snippet)
        snippet_layout.addWidget(add_snippet_btn)

        layout.addWidget(snippet_group)

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

    def _create_snippet_widget(
        self, snippet_id: str, config: TextSnippetConfig
    ) -> QtWidgets.QWidget:
        """创建文本片段配置部件"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 启用checkbox
        enabled_cb = QtWidgets.QCheckBox()
        enabled_cb.setChecked(config.enabled)
        layout.addWidget(enabled_cb)

        # 名称输入
        name_edit = QtWidgets.QLineEdit()
        name_edit.setText(config.name or snippet_id)
        name_edit.setPlaceholderText("名称")
        name_edit.setMaximumWidth(100)
        layout.addWidget(name_edit)

        # 快捷键按钮
        keys_text = self._format_keys(config.keys) if config.keys else "设置快捷键"
        keys_btn = QtWidgets.QPushButton(keys_text)
        keys_btn.setMinimumWidth(120)
        keys_btn.clicked.connect(
            lambda: self._capture_snippet_hotkey(snippet_id, keys_btn, config.keys)
        )
        layout.addWidget(keys_btn)

        # 文本内容输入
        text_edit = QtWidgets.QLineEdit()
        text_edit.setText(config.text)
        text_edit.setPlaceholderText("要输入的文本内容")
        text_edit.setMinimumWidth(150)
        layout.addWidget(text_edit)

        # 删除按钮
        delete_btn = QtWidgets.QPushButton("删除")
        delete_btn.setStyleSheet("color: #dc2626;")
        delete_btn.clicked.connect(lambda: self._delete_snippet(snippet_id))
        layout.addWidget(delete_btn)

        # 保存引用
        widget._enabled_cb = enabled_cb
        widget._name_edit = name_edit
        widget._keys_btn = keys_btn
        widget._text_edit = text_edit
        widget._current_keys = config.keys.copy()
        widget._snippet_id = snippet_id

        return widget

    def _add_snippet(self) -> None:
        """添加新的文本片段"""
        import uuid
        snippet_id = f"snippet_{uuid.uuid4().hex[:8]}"
        config = TextSnippetConfig(
            enabled=True,
            keys=["ctrl", "shift", "1"],
            text="",
            name="新片段",
        )
        widget = self._create_snippet_widget(snippet_id, config)
        self._snippets_layout.addWidget(widget)
        self._snippet_widgets[snippet_id] = widget

    def _capture_snippet_hotkey(
        self, snippet_id: str, button: QtWidgets.QPushButton, current_keys: list
    ) -> None:
        """捕获片段快捷键"""
        dialog = HotkeyCaptureDialog(current_keys, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_keys = dialog.get_captured_keys()
            if new_keys:
                button.setText(self._format_keys(new_keys))
                widget = self._snippet_widgets.get(snippet_id)
                if widget:
                    widget._current_keys = new_keys

    def _delete_snippet(self, snippet_id: str) -> None:
        """删除片段"""
        widget = self._snippet_widgets.get(snippet_id)
        if widget:
            self._snippets_layout.removeWidget(widget)
            widget.deleteLater()
            del self._snippet_widgets[snippet_id]

    def _format_keys(self, keys: list) -> str:
        """格式化按键列表为显示文本"""
        if _IS_MACOS:
            display_map = {
                "ctrl": "⌃ Control",
                "right_ctrl": "右⌃",
                "super": "⌘ Command",
                "alt": "⌥ Option",
                "shift": "⇧ Shift",
                "space": "空格",
            }
        else:
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

        # 收集文本片段配置
        self._config.text_snippets = {}
        for snip_id, widget in self._snippet_widgets.items():
            text = widget._text_edit.text().strip()
            if text:  # 只保存有文本内容的片段
                try:
                    self._config.text_snippets[snip_id] = TextSnippetConfig(
                        enabled=widget._enabled_cb.isChecked(),
                        keys=widget._current_keys,
                        text=text,
                        name=widget._name_edit.text().strip() or snip_id,
                    )
                except ValueError:
                    # 跳过无效配置
                    pass

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
        try:
            if event.type() == QtCore.QEvent.Type.KeyPress:
                # 在 macOS 上需要安全地获取 key
                key = getattr(event, 'key', lambda: None)()
                if key is None:
                    return super().eventFilter(obj, event)

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
        except Exception:
            # 忽略转换错误，让事件继续传播
            pass

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
            if _IS_MACOS:
                display_map = {
                    "ctrl": "⌃ Control",
                    "super": "⌘ Command",
                    "alt": "⌥ Option",
                    "shift": "⇧ Shift",
                    "space": "空格",
                }
            else:
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
