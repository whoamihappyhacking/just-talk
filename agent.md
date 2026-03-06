# agent.md

本文件为 AI 编码助手提供项目指引。

## 项目概述

Just Talk（说了么）是一个语音识别桌面应用，支持全局快捷键控制。使用 PyQt6 + WebEngine 作为 UI（HTML/CSS/JS 前端通过 WebView 渲染），pynput 捕获全局键盘/鼠标事件，通过火山引擎豆包语音识别 API 进行实时语音转文字。

## 常用命令

### 运行应用
```bash
uv run python asr_pyqt6_app.py
```

### 构建（Linux）
```bash
uv sync --frozen --extra build
make build-linux
```

### 构建（Windows via Docker+Wine）
```bash
make build-windows
```

### 发布打包
```bash
./scripts/release-linux.sh
```

## 架构

### 核心文件

- **`asr_pyqt6_app.py`**（~4600 行）：主应用文件，包含：
  - SAUC 二进制协议实现（语音转文字流式传输）
  - 纯标准库 WebSocket 客户端（无外部 WS 库依赖）
  - PyQt6 应用 + WebEngine UI
  - QtMultimedia 音频录制
  - QWebChannel 桥接 Python 后端与 Web 前端
  - macOS / KDE Wayland 权限检测与引导系统
  - 多平台自动上屏（X11 XTest、wtype、xdotool、pynput）

- **`x11_paste.py`**：X11 粘贴模块，使用 python-xlib 在单一后台线程中完成设置剪贴板所有权、模拟 Shift+Insert 按键、处理 SelectionRequest 事件的完整流程。关键设计：所有 X11 操作在同一线程和同一 Display 连接中完成，防止竞态条件导致目标窗口卡死。

- **`recording_indicator.py`**：录音悬浮指示器（波形动画、X11 窗口属性实现不抢焦点的叠加层）

- **`hotkey/`**：全局快捷键系统
  - `config.py`：快捷键配置数据类
  - `listener.py`：基于 pynput 的键盘/鼠标监听器
  - `manager.py`：快捷键管理器
  - `persistence.py`：配置持久化
  - `settings_ui.py`：PyQt6 设置对话框

- **`web/`**：前端资源（加载到 WebEngine）
  - `index.html`：主界面（设置、连接配置、权限引导、历史记录等）
  - `app.js`：前端 JavaScript
  - `styles.css`：样式表

### 关键技术细节

- Linux 下强制使用 X11/XCB 平台（`QT_QPA_PLATFORM=xcb`），通过 XWayland 兼容 Wayland
- 录音指示器使用 X11 窗口属性（`_NET_WM_WINDOW_TYPE_NOTIFICATION`、`WM_HINTS`）实现类 screenkey 行为（不抢焦点、置顶）
- 配置存储于 `~/.config/JustTalk/AsrApp.conf`（QSettings）
- PyInstaller 打包配置在 `just_talk.spec`，打包 `web/` 目录和 PyQt6 WebEngine 组件

### 权限系统

**macOS**：通过 ctypes 调用系统框架检测三项权限（输入监控、辅助功能、麦克风），在 UI 中显示引导页。

**KDE Wayland**：通过 D-Bus 查询 `xdg-permission-store` 的 `kde-authorized` 表检测 Remote Desktop 输入控制权限。使用 `busctl`（systemd 自带）操作权限，备选 `dbus-send`。不依赖 Flatpak。

### 快捷键模式

1. **按住说话**（Ctrl+Super 或鼠标中键）：按住录音，松开停止
2. **切换模式**（Alt）：按一下开始，再按一下停止

### 自动上屏方式

识别完成后自动将文字输入到当前焦点窗口，优先级：
1. **直接输入**：xdotool type（X11）/ wtype（Wayland）/ pynput
2. **粘贴上屏**：设置剪贴板 → 模拟 Ctrl+V / Shift+Insert
   - Linux X11：`x11_paste.py`（XTest 扩展）
   - Linux Wayland：wtype
   - macOS：Quartz CGEvent
   - Windows：SendInput API

## 注意事项

- 修改 `x11_paste.py` 时务必保持单线程设计（所有 X11 操作在同一线程 + 同一 Display 连接），否则会引发目标窗口卡死的竞态条件
- `asr_pyqt6_app.py` 是单体文件，修改时注意行号定位准确
- Web 前端与 Python 后端通过 QWebChannel 通信，新增 Python 属性/槽需在 JS 端同步绑定
- Lint 警告中 `Could not find import of PyQt6/Xlib/pynput` 等均为 Pyre2 找不到虚拟环境的误报，不影响运行
