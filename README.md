# Just Talk 项目文档

## 快速启动

```bash
uv run python asr_pyqt6_app.py
```

## 全局快捷键和录音指示器使用说明

### 默认快捷键配置

按住录音模式（按住时录音，松开停止）：
1. Ctrl + Super (Win键) - 主快捷键
2. 鼠标中键 - 按住录音

自由说模式（切换录音状态）：
3. Alt 键 - 按一下开始，再按一下结束

### 录音指示器功能

#### 波形与按钮
- 竖条波形动画（按住模式 11 条，自由说模式 15 条）
- 白色波形 + 黑色胶囊背景；自由说模式显示红/绿圆形按钮
- 定时器 33ms 刷新（约 30fps）

#### 按住模式
```
┌─────────────────┐
│  ～～～～～～～  │  只显示波形
└─────────────────┘
```
- 胶囊尺寸：120x50px

#### 自由说模式
```
┌─────────────────────────────┐
│  ～～～～～～～   ×    ✓   │
└─────────────────────────────┘
```
- **× 按钮**: 取消录音（也可按 Esc 键）
- **✓ 按钮**: 结束录音（也可再按 Alt 键）
- 胶囊尺寸：220x50px

#### 处理中 / 连接中
- 三点加载动画，居中显示

## 🚀 使用方法

### 按住录音
1. 按住 **Ctrl + Super** 或 **鼠标中键**
2. 屏幕底部出现波形指示器
3. 开始说话
4. 松开按键，录音自动停止

### 自由说模式
1. 按一下 **Alt** 键
2. 屏幕底部出现带按钮的指示器
3. 开始说话
4. 再按一下 **Alt** 或点击 **✓** 按钮结束
5. 或点击 **×** 按钮取消录音

## ⚙️ 自定义配置

在页面中的快捷键设置区域可以修改：
   - 启用/禁用快捷键
   - 自定义按键组合
   - 切换模式（按住/切换）

## 🔧 技术细节

### 配置文件位置
- Linux: `~/.config/JustTalk/AsrApp.conf`
- 配置自动保存（QSettings）

### 快捷键监听
- 使用 pynput 实现全局监听
- 独立线程运行，不影响主应用性能

### 录音指示器特性
- 无边框窗口，透明背景
- 始终置顶
- 不占用任务栏
- 自动定位到屏幕底部中间（距底部约 80px，受阴影边距影响）

## ⚠️ 注意事项

### Linux 权限
如果快捷键不工作，可能需要 X11 权限（视桌面环境而定）：
```bash
xhost +local:
```

### Wayland 限制
- Wayland 桌面环境可能不支持全局快捷键
- 建议使用 X11 会话

### 快捷键冲突
- Ctrl+Super 在某些桌面环境可能被系统占用
- 可以在设置中修改为其他组合

## 🐛 问题排查

### 快捷键不响应
1. 检查"启用全局快捷键"是否勾选
2. 运行应用时查看终端是否有错误信息
3. 尝试 `xhost +local:` 授予权限

### 录音指示器不显示
1. 确保录音功能正常启动
2. 检查屏幕底部是否被遮挡
3. 尝试最小化其他窗口

### 鼠标中键无反应
1. 检查配置中鼠标中键是否启用
2. 确认是真正的鼠标中键（不是滚轮滚动）

## 🧪 演示资源

参见 `demo/DEMO.md`。

## 📦 打包构建

### 本机构建（PyInstaller）
1. 安装构建依赖：
   `uv sync --extra build`
   （确保包含 PyQt6-WebEngine 依赖）

2. 运行构建：
   `uv run pyinstaller just_talk.spec`

产物在 `dist/` 下。构建为平台相关，需在目标平台上打包。
`just_talk.spec` 已将 `web/` 前端资源一起打包。

### Windows 原生构建
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

### Windows（Docker + Wine，可选）
本项目可使用 https://github.com/barracuda-cloudgen-access/pyinstaller 的容器，通过 Wine 构建 Windows 二进制。
Makefile 里已有封装：

```
make build-windows
```

产物在 `dist/windows/`。

Note: 该镜像入口会注入默认 PyInstaller 参数，会与 `.spec` 冲突，所以 Makefile 会覆盖 entrypoint 直接运行 `pyinstaller just_talk.spec`。

可覆盖镜像与镜像源配置：

```
PYINSTALLER_IMAGE=fydeinc/pyinstaller \
PYINSTALLER_PYPI_URL=https://pypi.tuna.tsinghua.edu.cn/ \
PYINSTALLER_PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
WIN_BINARY_NAME=just-talk-win64 \
WIN_ICON=icon.png \
make build-windows
```

如果 onefile 的 Windows 二进制无法启动，可尝试 onedir + console 调试：

```
WIN_ONEFILE=0 WIN_CONSOLE=1 make build-windows
```

## X11 录音指示器使用说明

## 🎯 设计目标

使用 X11 的原生特性实现类似 **screen-key** 的效果：
- 不抢焦点（可以继续在其他窗口打字）
- 始终置顶
- 不在任务栏显示
- 绕过窗口管理器控制

## 🔧 X11 技术实现

### 1. Qt 窗口标志
```python
Qt.WindowType.FramelessWindowHint           # 无边框
Qt.WindowType.WindowStaysOnTopHint          # 始终置顶
Qt.WindowType.X11BypassWindowManagerHint    # 绕过窗口管理器
```

### 2. Qt 窗口属性
```python
Qt.WidgetAttribute.WA_TranslucentBackground  # 透明背景
Qt.WidgetAttribute.WA_ShowWithoutActivating  # 显示时不激活
Qt.WidgetAttribute.WA_X11DoNotAcceptFocus    # X11不接受焦点
Qt.FocusPolicy.NoFocus                       # 不接受焦点策略
```

### 3. X11 窗口属性（使用 python-xlib）

#### _NET_WM_WINDOW_TYPE
设置窗口类型为 **NOTIFICATION**（通知窗口）
```python
_NET_WM_WINDOW_TYPE = _NET_WM_WINDOW_TYPE_NOTIFICATION
```
效果：
- 窗口管理器会特殊对待
- 不会在 Alt+Tab 中显示
- 不会抢焦点

#### _NET_WM_STATE
设置窗口状态
```python
_NET_WM_STATE = [
    _NET_WM_STATE_ABOVE,          # 始终在其他窗口之上
    _NET_WM_STATE_SKIP_TASKBAR,   # 不在任务栏显示
    _NET_WM_STATE_SKIP_PAGER,     # 不在工作区切换器显示
]
```

#### WM_HINTS
设置窗口提示（不接受输入焦点）
```python
wm_hints.flags |= 1  # InputHint
wm_hints.input = 0   # 不接受输入
```

## 🎨 视觉效果

### 按住模式
```
┌─────────────────┐
│  ～～～～～～～  │  仅显示波形动画
└─────────────────┘
```
胶囊尺寸: 120x50px（外层含阴影边距）

### 自由说模式
```
┌─────────────────────────────┐
│  ～～～～～～～   ×    ✓   │  波形 + 按钮
└─────────────────────────────┘
```
胶囊尺寸: 220x50px（外层含阴影边距）

### 样式特点
- 黑色胶囊背景 + 阴影
- 白色竖条波形（按住 11 条 / 自由说 15 条）
- 红色取消按钮、绿色确认按钮
- ~30fps 刷新

## 🚀 使用体验

### 不抢焦点测试
1. 打开任意文本编辑器
2. 开始打字
3. 按下 Ctrl+Super 触发录音
4. **继续打字** - 焦点不会被抢走！
5. 录音指示器显示在屏幕底部
6. 松开按键停止录音

### 窗口行为
- ✅ 不会在 Alt+Tab 中出现
- ✅ 不会在任务栏显示
- ✅ 不会在工作区切换器显示
- ✅ 点击窗口不会激活它
- ✅ 始终保持在最上层
- ✅ 可以点击按钮但不影响其他窗口焦点

## 🔍 与 screen-key 的对比

| 特性 | screen-key | 录音指示器 | 说明 |
|------|-----------|----------|------|
| 窗口类型 | NOTIFICATION | NOTIFICATION | ✅ 相同 |
| 不抢焦点 | ✅ | ✅ | 使用 WM_HINTS |
| 始终置顶 | ✅ | ✅ | _NET_WM_STATE_ABOVE |
| 不在任务栏 | ✅ | ✅ | _NET_WM_STATE_SKIP_TASKBAR |
| 透明背景 | ✅ | ✅ | Qt 透明背景 |
| 绕过 WM | ✅ | ✅ | X11BypassWindowManagerHint |

## 📋 依赖要求

### 必需
- PyQt6
- python-xlib (Linux 下 pynput 依赖)

### 可选
如果 python-xlib 不可用，仍然可以使用 Qt 的窗口标志，但 X11 特性会减少。

## 🎯 支持的桌面环境

### 完全支持
- ✅ GNOME (X11)
- ✅ KDE Plasma (X11)
- ✅ XFCE
- ✅ i3wm
- ✅ Openbox

### 部分支持
- ⚠️ GNOME (Wayland) - 有限制
- ⚠️ KDE Plasma (Wayland) - 有限制

### 技术原因
Wayland 不支持全局快捷键和某些窗口属性，建议使用 X11 会话。

## 🐛 故障排查

### 窗口会抢焦点
**原因**: X11 属性未生效  
**解决**:
```python
# 确保 python-xlib 已安装
pip install python-xlib

# 或使用 uv
uv add python-xlib
```

### 窗口不置顶
**原因**: 窗口管理器不支持 _NET_WM_STATE_ABOVE  
**解决**: 检查桌面环境是否支持 EWMH 标准

### 窗口在任务栏显示
**原因**: 窗口管理器忽略 _NET_WM_STATE_SKIP_TASKBAR  
**解决**: 这是窗口管理器的行为，某些 WM 不遵守此属性

## 💡 技术细节

### 窗口创建流程
1. 创建 Qt 窗口并设置标志/属性
2. 调用 `winId()` 生成原生窗口句柄
3. 使用 python-xlib 设置 X11 属性
4. 显示窗口并刷新显示

### 焦点策略
```python
# Qt 层面
self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
self.cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
self.confirm_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

# X11 层面
wm_hints.input = 0  # 告诉 WM 不要给焦点
```

## 📖 参考资料

- [Extended Window Manager Hints (EWMH)](https://specifications.freedesktop.org/wm-spec/wm-spec-latest.html)
- [python-xlib documentation](https://python-xlib.github.io/)
- [Qt X11 Extras](https://doc.qt.io/qt-6/qtx11extras-index.html)
- [screen-key project](https://gitlab.com/screenkey/screenkey)
