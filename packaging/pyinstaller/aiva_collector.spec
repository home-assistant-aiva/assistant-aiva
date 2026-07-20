# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


block_cipher = None
project_root = Path(SPECPATH).parents[1]


manual = Analysis(
    [str(project_root / "packaging" / "pyinstaller" / "aiva_collector_entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "requests",
        "openpyxl",
        "et_xmlfile",
        "certifi",
        "charset_normalizer",
        "idna",
        "urllib3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
manual_pyz = PYZ(manual.pure, manual.zipped_data, cipher=block_cipher)

manual_exe = EXE(
    manual_pyz,
    manual.scripts,
    manual.binaries,
    manual.zipfiles,
    manual.datas,
    [],
    name="aiva-collector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

background = Analysis(
    [str(project_root / "packaging" / "pyinstaller" / "aiva_collector_background_entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "requests",
        "openpyxl",
        "et_xmlfile",
        "certifi",
        "charset_normalizer",
        "idna",
        "urllib3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
background_pyz = PYZ(background.pure, background.zipped_data, cipher=block_cipher)

background_exe = EXE(
    background_pyz,
    background.scripts,
    background.binaries,
    background.zipfiles,
    background.datas,
    [],
    name="aiva-collector-background",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
