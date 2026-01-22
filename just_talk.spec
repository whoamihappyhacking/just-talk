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

pyz = PYZ(a.pure, a.zipped_data)

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
        strip=True,  # Strip symbols to reduce size
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
        strip=True,
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
        strip=True,
        upx=False,
        name=name,
    )
