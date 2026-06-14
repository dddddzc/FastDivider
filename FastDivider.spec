# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\15215\\Desktop\\FastDivider\\src\\main.py'],
    pathex=[],
    binaries=[('C:\\Users\\15215\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\pywin32_system32\\pythoncom314.dll', '.'), ('C:\\Users\\15215\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\pywin32_system32\\pythoncom314.dll', '.'), ('C:\\Users\\15215\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\pywin32_system32\\pywintypes314.dll', '.'), ('C:\\Users\\15215\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\pywin32_system32\\pywintypes314.dll', '.')],
    datas=[('C:\\Users\\15215\\Desktop\\FastDivider\\src\\resources\\icon.ico', 'resources'), ('C:\\Users\\15215\\Desktop\\FastDivider\\src\\resources\\icon.png', 'resources')],
    hiddenimports=['PyQt6.sip', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui', 'pyperclip', 'win32api', 'win32con', 'win32gui', 'win32clipboard', 'pythoncom', 'pywintypes', 'PyQt6.QtPlatformSupport', 'src', 'src.app', 'src.main', 'src.core', 'src.core.config', 'src.core.number_parser', 'src.core.clipboard_reader', 'src.core.hotkey_manager', 'src.core.history', 'src.ui', 'src.ui.toast_window', 'src.ui.tray_icon', 'src.ui.settings_dialog', 'src.ui.history_dialog'],
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
    name='FastDivider',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:\\Users\\15215\\Desktop\\FastDivider\\version_info.txt',
    icon=['C:\\Users\\15215\\Desktop\\FastDivider\\src\\resources\\icon.ico'],
)
