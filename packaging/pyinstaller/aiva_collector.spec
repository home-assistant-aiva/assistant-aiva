# -*- mode: python ; coding: utf-8 -*-

import runpy
from pathlib import Path


block_cipher = None
project_root = Path(SPECPATH).parents[1]
version_helpers = runpy.run_path(str(project_root / "scripts" / "generate_windows_version_info.py"))
version_files = version_helpers["write_version_info_files"](
    Path(workpath) / "windows-version-info"
)


manual = Analysis(
    [str(project_root / "packaging" / "pyinstaller" / "aiva_collector_entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
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
    [],
    exclude_binaries=True,
    name="aiva-collector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_files["aiva-collector.exe"]),
)

cli = Analysis(
    [str(project_root / "packaging" / "pyinstaller" / "aiva_collector_cli_entrypoint.py")],
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
cli_pyz = PYZ(cli.pure, cli.zipped_data, cipher=block_cipher)

cli_exe = EXE(
    cli_pyz,
    cli.scripts,
    [],
    exclude_binaries=True,
    name="aiva-collector-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_files["aiva-collector-cli.exe"]),
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
    [],
    exclude_binaries=True,
    name="aiva-collector-background",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_files["aiva-collector-background.exe"]),
)

aiva_collector_bundle = COLLECT(
    manual_exe,
    cli_exe,
    background_exe,
    manual.binaries,
    manual.datas,
    cli.binaries,
    cli.datas,
    background.binaries,
    background.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="aiva-collector",
)
