from __future__ import annotations

import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from aiva_collector.cli import main

MAX_LOG_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5


def _background_log_path() -> Path:
    program_data = Path.home()
    if sys.platform.startswith("win"):
        import os

        program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    return program_data / "AIVA" / "Collector" / "logs" / "background-runner.log"


def _rotate_background_log(log_path: Path) -> None:
    if not log_path.exists() or log_path.stat().st_size < MAX_LOG_BYTES:
        return
    oldest = log_path.with_name(f"{log_path.name}.{BACKUP_COUNT}")
    oldest.unlink(missing_ok=True)
    for index in range(BACKUP_COUNT - 1, 0, -1):
        current = log_path.with_name(f"{log_path.name}.{index}")
        if current.exists():
            current.rename(log_path.with_name(f"{log_path.name}.{index + 1}"))
    log_path.rename(log_path.with_name(f"{log_path.name}.1"))


if __name__ == "__main__":
    log_path = _background_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_background_log(log_path)
    try:
        with log_path.open("a", encoding="utf-8") as fh, redirect_stdout(fh), redirect_stderr(fh):
            raise SystemExit(main())
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"background runner fatal error: {exc}\n")
        raise SystemExit(2)
