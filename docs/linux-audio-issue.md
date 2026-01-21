# Linux 音频输入问题研究报告

## 问题现象

在 Linux 上使用 `uv run python asr_pyqt6_app.py` 运行时，出现：

```
qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version 7.1.2
[MIC] No audio input devices found (Qt multimedia backend may be missing)
```

## 根本原因

PyPI 的 PyQt6 包存在以下问题：

1. **自带独立 Qt 库**：PyQt6 包含完整的 Qt 运行时，位于 `.venv/.../PyQt6/Qt6/lib/`

2. **RPATH 硬编码**：PyQt6 的 `.so` 文件通过 RPATH 硬编码了库路径
   ```
   $ readelf -d PyQt6/QtCore.abi3.so | grep RPATH
   RPATH: [$ORIGIN/Qt6/lib]
   ```

3. **只有 FFmpeg 后端**：PyPI PyQt6 只包含 `libffmpegmediaplugin.so`，而 FFmpeg 后端**不支持音频输入捕获**，只支持媒体播放

4. **ABI 不兼容**：系统的 GStreamer 插件链接到系统 Qt 库，与 PyPI PyQt6 自带的 Qt 库存在 ABI 不兼容

## 验证结果

| 环境 | Qt 后端 | 检测到设备 |
|------|---------|-----------|
| 系统 Python + 系统 PyQt6 | GStreamer | 2 个麦克风 ✓ |
| uv venv + PyPI PyQt6 | FFmpeg | 0 个设备 ✗ |
| uv venv + QT_PLUGIN_PATH | GStreamer (加载但不工作) | 0 个设备 ✗ |

## 尝试过的方案

### 1. 设置 QT_PLUGIN_PATH（无效）
```bash
export QT_PLUGIN_PATH=/usr/lib/qt6/plugins
```
- 结果：GStreamer 插件能加载，但由于 ABI 不兼容无法正常工作

### 2. 设置 LD_LIBRARY_PATH（无效）
```bash
export LD_LIBRARY_PATH=/usr/lib
```
- 结果：PyQt6 的 RPATH 优先级高于 LD_LIBRARY_PATH，仍然加载自带的 Qt 库

### 3. 设置 QT_MEDIA_BACKEND（无效）
```bash
export QT_MEDIA_BACKEND=gstreamer
```
- 结果：能切换到 GStreamer 后端，但由于 ABI 问题仍无法检测设备

## 可行的解决方案

### 方案 A：使用系统 PyQt6（开发环境推荐）

```bash
# Arch Linux
sudo pacman -S python-pyqt6 python-pyqt6-webengine
pip install --user --break-system-packages pynput

# 直接用系统 Python 运行
python asr_pyqt6_app.py
```

### 方案 B：PyInstaller 打包方案

PyInstaller 打包面临的核心问题是 PyPI PyQt6 自带的 Qt 库与系统 GStreamer 插件 ABI 不兼容。

#### B1: 使用系统 PyQt6 打包（推荐）

在打包机器上使用系统 PyQt6 而非 PyPI 版本：

```bash
# 1. 安装系统依赖
sudo pacman -S python-pyqt6 python-pyqt6-webengine qt6-multimedia-gstreamer

# 2. 安装 PyInstaller 到用户目录
pip install --user --break-system-packages pyinstaller pynput

# 3. 用系统 Python 打包
python -m PyInstaller just_talk.spec
```

优点：
- 自然支持 GStreamer，音频输入正常工作
- 打包产物使用系统 Qt，与目标系统兼容性好

缺点：
- 需要目标机器有兼容的 Qt6 和 GStreamer
- 不同发行版可能需要不同的打包环境

#### B2: 运行时依赖系统 GStreamer

打包时不包含 GStreamer，运行时使用目标系统的：

```python
# 在 _bootstrap_runtime() 中添加
def _setup_gstreamer_path() -> None:
    if not sys.platform.startswith("linux"):
        return
    # 设置 GStreamer 插件路径
    gst_paths = [
        "/usr/lib/gstreamer-1.0",
        "/usr/lib/x86_64-linux-gnu/gstreamer-1.0",
    ]
    for path in gst_paths:
        if os.path.isdir(path):
            os.environ.setdefault("GST_PLUGIN_PATH", path)
            break
```

优点：
- 打包体积小
- 利用系统已有的 GStreamer

缺点：
- 需要目标机器安装 GStreamer
- 仍然存在 ABI 兼容性问题

#### B3: 完整打包 GStreamer（复杂）

将系统 GStreamer 插件和依赖库一起打包：

```python
# just_talk.spec 中添加
import os
import glob

# GStreamer 核心库
gst_libs = glob.glob("/usr/lib/libgst*.so*")
binaries += [(lib, ".") for lib in gst_libs]

# GStreamer 插件（最小集合）
gst_plugins = [
    "/usr/lib/gstreamer-1.0/libgstcoreelements.so",
    "/usr/lib/gstreamer-1.0/libgstaudioconvert.so",
    "/usr/lib/gstreamer-1.0/libgstaudioresample.so",
    "/usr/lib/gstreamer-1.0/libgstpulseaudio.so",
    "/usr/lib/gstreamer-1.0/libgstalsa.so",
]
binaries += [(p, "gstreamer-1.0") for p in gst_plugins if os.path.exists(p)]
```

需要的最小 GStreamer 组件：
- 核心库：~8.4MB (`libgst*.so`)
- 音频插件：~736KB

优点：
- 完全自包含，不依赖目标系统

缺点：
- 包体积增加 ~10-20MB
- 依赖链复杂，可能遗漏库
- 仍需解决 Qt ABI 兼容问题

## 推荐方案

| 场景 | 推荐方案 |
|------|----------|
| 开发调试 | 方案 A：系统 PyQt6 |
| 发布 Linux 包 | 方案 B1：系统 PyQt6 打包 |
| 通用二进制 | 考虑 AppImage 或 Flatpak |

## 相关文件

- 音频设备检测代码：`asr_pyqt6_app.py:2593-2616`
- 启动时环境配置：`asr_pyqt6_app.py:68-78` (`_bootstrap_runtime`)
- PyInstaller 配置：`just_talk.spec`
