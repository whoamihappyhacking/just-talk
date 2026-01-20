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

name = os.environ.get("JT_BINARY_NAME", "just-talk")
onefile = os.environ.get("JT_ONEFILE", "1") == "1"
console = os.environ.get("JT_CONSOLE", "0") == "1"
icon_path = os.environ.get("JT_ICON")
if icon_path and not os.path.exists(icon_path):
    icon_path = None

datas = [("web", "web")]
if os.path.exists("icon.png"):
    datas.append(("icon.png", "."))
datas += collect_data_files("PyQt6", subdir="Qt6/plugins")
datas += collect_data_files("PyQt6", subdir="Qt6/resources")
datas += collect_data_files("PyQt6", subdir="Qt6/translations")
datas += collect_data_files("PyQt6", subdir="Qt6/resources/qtwebengine_dictionaries")
datas += collect_data_files("PyQt6", subdir="Qt6/translations/qtwebengine_locales")
datas += collect_data_files(
    "PyQt6",
    subdir="Qt6/bin",
    includes=["*.dll", "*.exe", "*.pak", "*.dat", "*.bin"],
)

binaries = []
binaries += collect_dynamic_libs("PyQt6")
binaries += collect_dynamic_libs("PyQt6.QtWebEngineCore")

a = Analysis(
    ["asr_pyqt6_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

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
        strip=False,
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
        strip=False,
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
        strip=False,
        upx=False,
        name=name,
    )
