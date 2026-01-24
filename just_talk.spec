# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hiddenimports = []
hiddenimports += ["pkgutil"]
hiddenimports += collect_submodules("PyQt6.QtMultimedia")
hiddenimports += collect_submodules("PyQt6.QtWebEngineWidgets")
hiddenimports += collect_submodules("PyQt6.QtWebEngineCore")
hiddenimports += collect_submodules("PyQt6.QtWebChannel")
hiddenimports += collect_submodules("pynput")
hiddenimports += collect_submodules("sounddevice")
hiddenimports += ["numpy"]
# pynput platform backends (not always collected automatically)
hiddenimports += [
    # Windows backend
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "pynput._util.win32",
    # X11/Linux backend
    "pynput.keyboard._xorg",
    "pynput.mouse._xorg",
    "pynput._util.xorg",
    "Xlib",
    "Xlib.display",
    "Xlib.ext",
    "Xlib.ext.xtest",
    "Xlib.keysymdef",
    "Xlib.keysymdef.latin1",
    "Xlib.keysymdef.miscellany",
]

name = os.environ.get("JT_BINARY_NAME", "just-talk")
onefile = os.environ.get("JT_ONEFILE", "1") == "1"
console = os.environ.get("JT_CONSOLE", "0") == "1"
icon_path = os.environ.get("JT_ICON")
if icon_path and not os.path.exists(icon_path):
    icon_path = None

datas = [("web", "web")]
if os.path.exists("icon.png"):
    datas.append(("icon.png", "."))

# 只收集必要的 Qt 插件
qt_plugins_needed = [
    "platforms",
    "platformthemes",
    "multimedia",
    "xcbglintegrations",
    "egldeviceintegrations",
    "imageformats",
    "iconengines",
    "tls",
]
for plugin in qt_plugins_needed:
    datas += collect_data_files("PyQt6", subdir=f"Qt6/plugins/{plugin}")

# WebEngine 资源 (必需)
datas += collect_data_files("PyQt6", subdir="Qt6/resources")
datas += collect_data_files(
    "PyQt6",
    subdir="Qt6/bin",
    includes=["*.dll", "*.exe", "*.pak", "*.dat", "*.bin"],
)
# QtWebEngineProcess on Linux is in libexec
datas += collect_data_files("PyQt6", subdir="Qt6/libexec")

# 只保留中英文翻译，减少约 45MB
datas += collect_data_files(
    "PyQt6",
    subdir="Qt6/translations",
    includes=["qt_zh*.qm", "qt_en*.qm", "qtbase_zh*.qm", "qtbase_en*.qm"],
)
datas += collect_data_files(
    "PyQt6",
    subdir="Qt6/translations/qtwebengine_locales",
    includes=["zh*.pak", "en*.pak"],
)

binaries = []
binaries += collect_dynamic_libs("PyQt6")
binaries += collect_dynamic_libs("PyQt6.QtWebEngineCore")

# 排除不需要的模块以减小体积
excludes = [
    "PyQt6.Qt3D",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtLocation",
    "PyQt6.QtSensors",
    "PyQt6.QtSerialPort",
    "PyQt6.QtTest",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtSql",
    "PyQt6.QtXml",
    "PyQt6.QtDataVisualization",
    "PyQt6.QtCharts",
    "PyQt6.QtQuick3D",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtTextToSpeech",
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "matplotlib",
    "scipy",
    "pandas",
    "PIL",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
]

a = Analysis(
    ["asr_pyqt6_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# 过滤掉不需要的 Qt 库 (Quick3D, PDF 等)
a.binaries = [
    b for b in a.binaries
    if not any(x in b[0] for x in [
        "Quick3D",
        "Pdf",
        "RemoteObjects",
        "Bluetooth",
        "Nfc",
        "Sensors",
        "SerialPort",
        "TextToSpeech",
        "VirtualKeyboard",
        "Wayland",  # X11 only for now
        "Charts",
        "DataVisualization",
        "3D",
    ])
]

# Avoid bundling distro-specific OpenGL/GLX stack libs that can break on other distros.
# Exclude host X11/GL stacks to avoid bundling distro-specific drivers/libs.
gl_exclude_prefixes = (
    "libOpenGL",
    "libGL",
    "libGLX",
    "libGLdispatch",
    "libEGL",
    "libGLESv2",
    "libgbm",
    "libdrm",
    "libxcb-glx",
)

def _keep_binary(entry):
    name = os.path.basename(entry[0])
    if name.startswith(gl_exclude_prefixes):
        return False
    # X11/XCB/Wayland system libs should come from the target distro.
    x11_prefixes = (
        "libX11",
        "libX11-xcb",
        "libXau",
        "libXcursor",
        "libXdamage",
        "libXdmcp",
        "libXext",
        "libXfixes",
        "libXi",
        "libXinerama",
        "libXrandr",
        "libXrender",
        "libXtst",
        "libICE",
        "libSM",
        "libxcb",
        "libxkbcommon",
        "libxkbcommon-x11",
        "libwayland-client",
        "libwayland-cursor",
        "libwayland-egl",
    )
    return not name.startswith(x11_prefixes)

a.binaries = [b for b in a.binaries if _keep_binary(b)]

pyz = PYZ(a.pure, a.zipped_data)

# Only strip on Linux (Wine doesn't have strip)
import sys
do_strip = sys.platform.startswith("linux")

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=do_strip,
        upx=False,
        console=console,
        icon=icon_path,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=do_strip,
        upx=False,
        console=console,
        exclude_binaries=True,
        icon=icon_path,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=do_strip,
        upx=False,
        name=name,
    )

    # macOS: 生成 .app bundle
    if sys.platform == 'darwin':
        app = BUNDLE(
            coll,
            name='Just Talk.app',
            icon='icon.icns' if os.path.exists('icon.icns') else None,
            bundle_identifier='com.justtalk.app',
            info_plist={
                'CFBundleShortVersionString': '0.1.4',
                'CFBundleIconFile': 'icon.icns',
                'NSMicrophoneUsageDescription': '需要麦克风权限进行语音识别',
                'NSAppleEventsUsageDescription': '需要辅助功能权限实现全局快捷键',
                'NSHighResolutionCapable': True,
            },
        )
