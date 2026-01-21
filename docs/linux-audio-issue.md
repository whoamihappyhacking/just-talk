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

### 方案 B：PyInstaller 打包时包含 GStreamer 插件

详见下一节研究。

## 相关文件

- 音频设备检测代码：`asr_pyqt6_app.py:2593-2616`
- 启动时环境配置：`asr_pyqt6_app.py:68-78` (`_bootstrap_runtime`)
- PyInstaller 配置：`just_talk.spec`
