# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the BravoLED Config Switcher GUI.
#
# Build with:
#     pip install pyinstaller
#     pyinstaller bravo_switcher.spec
#
# Output: dist\BravoSwitcher.exe  (a single-file, windowed executable)
#
# What this spec handles that a plain "pyinstaller bravo_switcher_gui.py" would miss:
#   1. SimConnect ships a native SimConnect.dll that the library loads at runtime
#      from next to its own package file. PyInstaller does not pick up that DLL
#      automatically, so we locate it and bundle it into a "SimConnect" folder
#      inside the exe, preserving the path the library expects.
#   2. SimConnect is imported lazily (inside a function), so we declare it and its
#      submodules as hidden imports so PyInstaller definitely includes them.
#
# NOTE: build this on Windows with SimConnect installed in the same Python
# environment (pip install SimConnect pyinstaller). The .exe is Windows-only.

import os
from PyInstaller.utils.hooks import collect_submodules

# --- Locate the SimConnect package and its bundled DLL -----------------------
try:
    import SimConnect
    _sc_dir = os.path.dirname(SimConnect.__file__)
    _sc_dll = os.path.join(_sc_dir, "SimConnect.dll")
    if not os.path.exists(_sc_dll):
        raise FileNotFoundError(
            "SimConnect.dll not found at %s -- is the SimConnect package installed?" % _sc_dll)
    # (source_path, destination_folder_inside_exe)
    _datas = [(_sc_dll, "SimConnect")]
except Exception as e:
    raise SystemExit(
        "Could not locate the SimConnect package/DLL: %s\n"
        "Run 'pip install SimConnect' in this environment first." % e)

# Make sure all SimConnect submodules and the pywin32 bits come along.
hidden = collect_submodules("SimConnect")
hidden += ["win32api", "win32con", "win32event", "win32process", "pywintypes"]


block_cipher = None

a = Analysis(
    ["bravo_switcher_gui.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="BravoLED Aircraft Switcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app, no console box pops up
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="bravo_switcher.ico",     # uncomment and supply a .ico to brand the exe
)
