# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# Collect everything needed for these packages
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=webview_binaries + pystray_binaries,
    datas=[
        ('frontend', 'frontend'),  # bundle the frontend folder
        ('layouts.json', '.'),      # bundle the default layouts
    ] + webview_datas + pystray_datas,
    hiddenimports=[
        'win32api', 'win32gui', 'win32con', 'win32process',
        'PIL._tkinter_finder',
    ] + webview_hiddenimports + pystray_hiddenimports,
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
    name='DesktopOrganizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # False = no console window appears when launched
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',  # uncomment once you have an icon file
)