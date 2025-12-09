# -*- mode: python ; coding: utf-8 -*-
"""
BRAW-Brew PyInstaller spec file
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# PySide6 데이터 파일 수집
pyside6_datas = collect_data_files('PySide6', includes=['plugins/**/*'])

# 소스 경로
src_path = Path('braw_batch_ui')

a = Analysis(
    [str(src_path / 'run_farm.py')],
    pathex=['.', str(src_path)],
    binaries=[],
    datas=pyside6_datas,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui', 
        'PySide6.QtWidgets',
        'shiboken6',
        'psutil',
        'json',
        'subprocess',
        'threading',
        'queue',
        'datetime',
        'uuid',
        'socket',
        'platform',
    ] + collect_submodules('PySide6'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3D',
        'PySide6.QtMultimedia',
        'PySide6.QtQuick',
        'PySide6.QtQml',
    ],
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
    name='BRAW-Brew',
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
    icon=None,
)
