from __future__ import annotations

import sys
import traceback

from aiva_collector.config import collector_data_dir
from aiva_collector.desktop_app import main


def _write_startup_error(exc: BaseException) -> None:
    try:
        log_path = collector_data_dir() / "logs" / "desktop-startup.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"AIVA Collector desktop startup error: {exc}\n")
            traceback.print_exc(file=handle)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as exc:
        _write_startup_error(exc)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "AIVA Collector",
                "No se pudo abrir AIVA Collector. Se guardó un diagnóstico en la carpeta de registros.",
                parent=root,
            )
            root.destroy()
        except Exception:
            pass
        raise SystemExit(2)
