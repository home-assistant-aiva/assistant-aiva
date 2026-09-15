from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "pyinstaller" / "aiva_collector.spec"
DIST_DIR = ROOT / "dist"
APP_DIR_NAME = "aiva-collector"


def build_exe(spec_path: Path = SPEC_PATH, dist_dir: Path = DIST_DIR) -> Path:
    if not spec_path.exists():
        raise FileNotFoundError(f"No existe spec PyInstaller: {spec_path}")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        str(spec_path),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    app_dir = dist_dir / APP_DIR_NAME
    exe_path = app_dir / "aiva-collector.exe"
    cli_path = app_dir / "aiva-collector-cli.exe"
    background_path = app_dir / "aiva-collector-background.exe"
    missing = [path for path in (exe_path, cli_path, background_path) if not path.exists()]
    if missing:
        raise FileNotFoundError("No se generaron ejecutables: " + ", ".join(str(path) for path in missing))
    support_dir = app_dir / "_internal"
    if not support_dir.is_dir() or not any(path.is_file() for path in support_dir.rglob("*")):
        raise FileNotFoundError(f"No se generaron dependencias onedir: {support_dir}")
    return exe_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Windows aiva-collector.exe with PyInstaller")
    parser.add_argument("--spec", default=str(SPEC_PATH))
    parser.add_argument("--dist-dir", default=str(DIST_DIR))
    args = parser.parse_args(argv)

    exe_path = build_exe(Path(args.spec), Path(args.dist_dir))
    print(f"EXE: {exe_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
