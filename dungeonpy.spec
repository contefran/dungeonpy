# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for DungeonPy.
# Build with:  pyinstaller dungeonpy.spec --noconfirm
#
# Assets/, Maps/, Savegames/ are kept EXTERNAL (next to the binary) so the DM
# can add custom images and maps without rebuilding.

a = Analysis(
    ['run_dnd_py.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # websockets 12+ uses asyncio-native API; these submodules are loaded
        # dynamically at runtime and must be listed explicitly for PyInstaller.
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.server',
        'websockets.asyncio.client',
        'websockets.asyncio.connection',
        'websockets.exceptions',
        # PIL / Pillow
        'PIL._tkinter_finder',
        'PIL.Image',
        'PIL.ImageTk',
        # PySimpleGUI backend
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.simpledialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim large scientific packages that are not used
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'notebook', 'IPython', 'jupyter',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dungeonpy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # keep console visible — useful for verbose/error output
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='dungeonpy',
)
