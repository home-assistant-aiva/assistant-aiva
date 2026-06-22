from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "pyinstaller" / "aiva_collector.spec"
DIST_DIR = ROOT / "dist"


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
    exe_path = dist_dir / "aiva-collector.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"No se genero {exe_path}")
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
