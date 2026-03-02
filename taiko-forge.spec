# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

tja2fumen_datas = collect_data_files('tja2fumen')
app_datas = [
    ('SONG_DLC_123.zip', '.'),
]

a = Analysis(
    ['src/taiko_forge/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=tja2fumen_datas + app_datas,
    hiddenimports=[
        'taiko_forge',
        'taiko_forge.app',
        'taiko_forge.audio',
        'taiko_forge.builder',
        'taiko_forge.config',
        'taiko_forge.downloader',
        'taiko_forge.edat',
        'taiko_forge.ese_browser',
        'taiko_forge.fumen',
        'taiko_forge.tja',
        'tja2fumen',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='taiko-forge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # no terminal window when double-clicked
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
