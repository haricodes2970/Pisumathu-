# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('config', 'config'), ('core', 'core'), ('ui', 'ui'), ('audio', 'audio'), ('transcription', 'transcription')]
binaries = []
hiddenimports = ['config.settings', 'core.controller', 'core.typer', 'core.startup', 'ui.main_window', 'ui.pill', 'ui.tray', 'audio.capture', 'transcription.engine', 'whisper', 'torch', 'pyaudio', 'pynput', 'pystray', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.messagebox', 'tkinter.filedialog']
tmp_ret = collect_all('tkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['pisumathu.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='Pisumathu',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Pisumathu',
)
