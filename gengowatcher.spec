# -*- mode: python ; coding: utf-8 -*-

# This is the recommended spec file for building GengoWatcher.

block_cipher = None

# Analysis block: This is where PyInstaller finds all the code.
a = Analysis(
    ['gengowatcher.py'],  # Your main script file
    pathex=[],
    binaries=[],
    
    # --- Data Files ---
    # This section is CRUCIAL. It tells PyInstaller what non-Python files to bundle.
    # Format: ('source_path_on_disk', 'destination_folder_in_bundle')
    datas=[
        ('assets/icon.ico', 'assets')  # Bundles the icon into an 'assets' folder inside the .exe
    ],
    
    # --- Hidden Imports ---
    # PyInstaller sometimes can't find modules that are imported dynamically.
    # We must list them here to prevent 'ModuleNotFoundError' at runtime.
    hiddenimports=[
        'plyer.platforms.win.notification', # For Windows notifications
        'win10toast' # Another backend for plyer notifications
    ],
    
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False
)

# PYC block: Handles compiled Python files. Usually no changes are needed here.
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# EXE block: Defines the final executable.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GengoWatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compresses the final executable. Requires UPX to be installed.
    upx_exclude=[],
    
    # --- Console Window ---
    # `console=True` is ESSENTIAL. It ensures the terminal window appears.
    # If this is False, your application will run invisibly in the background.
    console=True,
    
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    
    # --- Application Icon ---
    # Sets the icon for the .exe file itself.
    icon='assets/icon.ico'
)

# COLLECT block: Gathers all the files into the final output directory.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GengoWatcher'
)