from __future__ import annotations

import argparse
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cli import DEFAULT_BACKEND_URL, DEFAULT_COLLECTOR_VERSION
from .desktop_service import (
    DashboardSnapshot,
    OperationResult,
    activate_installation,
    configure_source_folder,
    export_diagnostics,
    load_dashboard_snapshot,
    logs_folder,
    open_folder,
    synchronize_now,
    test_aiva_connection,
)


APP_TITLE = "AIVA Collector"
WINDOW_SIZE = "980x720"
MIN_WINDOW_SIZE = (860, 650)

COLORS = {
    "navy": "#12233F",
    "blue": "#2367D1",
    "blue_hover": "#1858B8",
    "light_blue": "#EAF2FF",
    "green": "#157A55",
    "light_green": "#E9F8F1",
    "amber": "#946200",
    "light_amber": "#FFF5DA",
    "red": "#B42318",
    "light_red": "#FDECEC",
    "text": "#172033",
    "muted": "#667085",
    "border": "#D9E1EC",
    "surface": "#FFFFFF",
    "background": "#F4F7FB",
}


def _friendly_time(value: str | None) -> str:
    if not value:
        return "Todavía no se ejecutó"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def _task_text(value: bool | None) -> str:
    if value is None:
        return "Disponible sólo en Windows"
    return "Activa cada 15 minutos" if value else "No detectada"


class ActivationDialog(tk.Toplevel):
    def __init__(self, parent: "CollectorApp", on_submit: Callable[[str, str], None]) -> None:
        super().__init__(parent.root)
        self.parent_app = parent
        self.on_submit = on_submit
        self.title("Conectar este equipo con AIVA")
        self.geometry("560x430")
        self.resizable(False, False)
        self.configure(bg=COLORS["surface"])
        self.transient(parent.root)
        self.grab_set()

        container = ttk.Frame(self, style="Surface.TFrame", padding=32)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Conectar con AIVA", style="DialogTitle.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Generá un código de activación en AIVA Comercial y pegalo aquí. El código se usa una sola vez.",
            style="Body.TLabel",
            wraplength=485,
            justify="left",
        ).pack(anchor="w", pady=(10, 22))

        ttk.Label(container, text="Código de activación", style="FieldLabel.TLabel").pack(anchor="w")
        self.code_var = tk.StringVar()
        code_entry = ttk.Entry(container, textvariable=self.code_var, font=("Segoe UI", 13))
        code_entry.pack(fill="x", pady=(7, 12), ipady=7)
        code_entry.focus_set()

        self.advanced_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            container,
            text="Configuración avanzada",
            variable=self.advanced_visible,
            command=self._toggle_advanced,
        ).pack(anchor="w", pady=(2, 6))

        self.advanced_frame = ttk.Frame(container, style="Surface.TFrame")
        ttk.Label(self.advanced_frame, text="Dirección del servicio AIVA", style="FieldLabel.TLabel").pack(anchor="w")
        self.backend_var = tk.StringVar(value=DEFAULT_BACKEND_URL)
        ttk.Entry(self.advanced_frame, textvariable=self.backend_var).pack(fill="x", pady=(7, 0), ipady=5)

        actions = ttk.Frame(container, style="Surface.TFrame")
        actions.pack(side="bottom", fill="x", pady=(24, 0))
        ttk.Button(actions, text="Cancelar", style="Secondary.TButton", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Conectar equipo", style="Primary.TButton", command=self._submit).pack(
            side="right", padx=(0, 10)
        )
        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

    def _toggle_advanced(self) -> None:
        if self.advanced_visible.get():
            self.advanced_frame.pack(fill="x", pady=(6, 0))
        else:
            self.advanced_frame.pack_forget()

    def _submit(self) -> None:
        code = self.code_var.get().strip()
        if not code:
            messagebox.showwarning("Falta el código", "Pegá el código generado desde AIVA Comercial.", parent=self)
            return
        backend = self.backend_var.get().strip() or DEFAULT_BACKEND_URL
        self.destroy()
        self.on_submit(code, backend)


class CollectorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(*MIN_WINDOW_SIZE)
        self.root.configure(bg=COLORS["background"])
        self._result_queue: queue.Queue[tuple[OperationResult, Callable[[OperationResult], None] | None]] = queue.Queue()
        self._busy = False
        self._snapshot: DashboardSnapshot | None = None

        self._configure_styles()
        self._build_layout()
        self.root.after(100, self.refresh)
        self.root.after(150, self._poll_results)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            style.theme_use("clam")
        style.configure("App.TFrame", background=COLORS["background"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Header.TFrame", background=COLORS["navy"])
        style.configure("HeaderTitle.TLabel", background=COLORS["navy"], foreground="white", font=("Segoe UI Semibold", 20))
        style.configure("HeaderSub.TLabel", background=COLORS["navy"], foreground="#C8D5EA", font=("Segoe UI", 10))
        style.configure("PageTitle.TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI Semibold", 16))
        style.configure("DialogTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 19))
        style.configure("CardTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 11))
        style.configure("Metric.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 18))
        style.configure("Body.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("FieldLabel.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 10))
        style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(18, 10))
        style.map("Primary.TButton", background=[("active", COLORS["blue_hover"]), ("!disabled", COLORS["blue"])], foreground=[("!disabled", "white")])
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(14, 9))
        style.configure("Link.TButton", font=("Segoe UI", 9), padding=(8, 5))

    def _build_layout(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(30, 18))
        header.pack(fill="x")
        brand = ttk.Frame(header, style="Header.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="AIVA Collector", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Conexión segura entre tu sistema de ventas y AIVA", style="HeaderSub.TLabel").pack(anchor="w", pady=(2, 0))
        self.version_label = ttk.Label(header, text=f"v{DEFAULT_COLLECTOR_VERSION}", style="HeaderSub.TLabel")
        self.version_label.pack(side="right")

        body = ttk.Frame(self.root, style="App.TFrame", padding=(30, 24, 30, 22))
        body.pack(fill="both", expand=True)

        self.status_frame = tk.Frame(body, bg=COLORS["light_blue"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.status_frame.pack(fill="x")
        status_inner = tk.Frame(self.status_frame, bg=COLORS["light_blue"], padx=20, pady=16)
        status_inner.pack(fill="x")
        self.status_dot = tk.Label(status_inner, text="●", bg=COLORS["light_blue"], fg=COLORS["blue"], font=("Segoe UI", 17))
        self.status_dot.pack(side="left", anchor="n", padx=(0, 12))
        status_copy = tk.Frame(status_inner, bg=COLORS["light_blue"])
        status_copy.pack(side="left", fill="x", expand=True)
        self.status_title = tk.Label(status_copy, text="Revisando estado…", bg=COLORS["light_blue"], fg=COLORS["text"], font=("Segoe UI Semibold", 12), anchor="w")
        self.status_title.pack(fill="x")
        self.status_detail = tk.Label(status_copy, text="", bg=COLORS["light_blue"], fg=COLORS["muted"], font=("Segoe UI", 9), anchor="w", justify="left", wraplength=720)
        self.status_detail.pack(fill="x", pady=(3, 0))

        title_row = ttk.Frame(body, style="App.TFrame")
        title_row.pack(fill="x", pady=(22, 10))
        ttk.Label(title_row, text="Estado de la conexión", style="PageTitle.TLabel").pack(side="left")
        ttk.Button(title_row, text="Actualizar", style="Link.TButton", command=self.refresh).pack(side="right")

        cards = ttk.Frame(body, style="App.TFrame")
        cards.pack(fill="x")
        for column in range(3):
            cards.columnconfigure(column, weight=1, uniform="cards")
        self.connection_card = self._metric_card(cards, 0, "CONEXIÓN", "—", "Comercio sin vincular")
        self.source_card = self._metric_card(cards, 1, "FUENTE DE DATOS", "—", "Elegí una carpeta")
        self.sync_card = self._metric_card(cards, 2, "ÚLTIMA SINCRONIZACIÓN", "—", "Sin actividad registrada")

        actions_title = ttk.Frame(body, style="App.TFrame")
        actions_title.pack(fill="x", pady=(22, 10))
        ttk.Label(actions_title, text="Acciones", style="PageTitle.TLabel").pack(side="left")

        action_panel = ttk.Frame(body, style="Surface.TFrame", padding=18)
        action_panel.pack(fill="x")
        self.connect_button = ttk.Button(action_panel, text="Conectar con AIVA", style="Primary.TButton", command=self.open_activation)
        self.connect_button.pack(side="left")
        self.source_button = ttk.Button(action_panel, text="Elegir carpeta de datos", style="Secondary.TButton", command=self.choose_source)
        self.source_button.pack(side="left", padx=(10, 0))
        self.test_button = ttk.Button(action_panel, text="Probar conexión", style="Secondary.TButton", command=self.test_connection)
        self.test_button.pack(side="left", padx=(10, 0))
        self.sync_button = ttk.Button(action_panel, text="Sincronizar ahora", style="Secondary.TButton", command=self.sync_now)
        self.sync_button.pack(side="left", padx=(10, 0))

        footer = ttk.Frame(body, style="App.TFrame")
        footer.pack(fill="x", side="bottom", pady=(18, 0))
        self.activity_var = tk.StringVar(value="AIVA Collector listo.")
        ttk.Label(footer, textvariable=self.activity_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(footer, text="Abrir datos", style="Link.TButton", command=self.open_source_folder).pack(side="right")
        ttk.Button(footer, text="Ver registros", style="Link.TButton", command=self.open_logs).pack(side="right", padx=(0, 8))
        ttk.Button(footer, text="Exportar diagnóstico", style="Link.TButton", command=self.export_diagnostics).pack(side="right", padx=(0, 8))

    def _metric_card(self, parent: ttk.Frame, column: int, heading: str, value: str, detail: str) -> tuple[tk.StringVar, tk.StringVar]:
        frame = tk.Frame(parent, bg=COLORS["surface"], highlightthickness=1, highlightbackground=COLORS["border"], padx=18, pady=15)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 2 else 5))
        tk.Label(frame, text=heading, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8), anchor="w").pack(fill="x")
        value_var = tk.StringVar(value=value)
        detail_var = tk.StringVar(value=detail)
        tk.Label(frame, textvariable=value_var, bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 15), anchor="w").pack(fill="x", pady=(7, 2))
        tk.Label(frame, textvariable=detail_var, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8), anchor="w", justify="left", wraplength=250).pack(fill="x")
        return value_var, detail_var

    def _set_banner(self, snapshot: DashboardSnapshot) -> None:
        palette = {
            "connected": (COLORS["light_green"], COLORS["green"]),
            "setup": (COLORS["light_blue"], COLORS["blue"]),
            "attention": (COLORS["light_amber"], COLORS["amber"]),
            "error": (COLORS["light_red"], COLORS["red"]),
        }
        background, accent = palette.get(snapshot.state, palette["setup"])
        self.status_frame.configure(bg=background, highlightbackground=accent)
        inner = self.status_frame.winfo_children()[0]
        inner.configure(bg=background)
        for child in inner.winfo_children():
            child.configure(bg=background)
            for grandchild in child.winfo_children():
                grandchild.configure(bg=background)
        self.status_dot.configure(fg=accent)
        self.status_title.configure(text=snapshot.title)
        self.status_detail.configure(text=snapshot.detail)

    def refresh(self) -> None:
        snapshot = load_dashboard_snapshot()
        self._snapshot = snapshot
        self.version_label.configure(text=f"v{snapshot.version}")
        self._set_banner(snapshot)

        connection_value, connection_detail = self.connection_card
        if snapshot.token_configured:
            connection_value.set("Conectado")
            task = _task_text(snapshot.scheduled_task_installed)
            connection_detail.set(f"Comercio {snapshot.commerce_id or 'vinculado'} · Automático: {task}")
        else:
            connection_value.set("Sin activar")
            connection_detail.set("Necesita un código de AIVA Comercial")

        source_value, source_detail = self.source_card
        if snapshot.source_exists:
            source_value.set(f"{snapshot.source_files} archivo(s)")
            source_detail.set(snapshot.input_dir or "Carpeta configurada")
        else:
            source_value.set("Sin carpeta")
            source_detail.set(snapshot.input_dir or "Elegí dónde se generan CSV o Excel")

        sync_value, sync_detail = self.sync_card
        sync_value.set(_friendly_time(snapshot.last_run_at))
        sync_detail.set(
            f"Encontrados {snapshot.files_found} · Elegibles {snapshot.files_eligible} · Omitidos {snapshot.files_skipped} · "
            f"Procesados {snapshot.files_processed} · Enviados {snapshot.summaries_sent} · Duplicados {snapshot.duplicates} · "
            f"Pendientes {snapshot.queue_pending} · Rechazados {snapshot.rejected}"
        )

        self.connect_button.configure(text="Volver a vincular" if snapshot.token_configured else "Conectar con AIVA")
        self.source_button.configure(state="normal" if snapshot.token_configured else "disabled")
        self.test_button.configure(state="normal" if snapshot.token_configured else "disabled")
        self.sync_button.configure(state="normal" if snapshot.token_configured and snapshot.source_exists else "disabled")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.root.configure(cursor="wait" if busy else "")
        if message:
            self.activity_var.set(message)
        if not busy:
            self.refresh()

    def _run_async(
        self,
        action: Callable[[], OperationResult],
        *,
        progress: str,
        done: Callable[[OperationResult], None] | None = None,
    ) -> None:
        if self._busy:
            return
        self._set_busy(True, progress)

        def worker() -> None:
            try:
                result = action()
            except Exception as exc:  # pragma: no cover - desktop process boundary
                result = OperationResult(False, "Error inesperado", str(exc))
            self._result_queue.put((result, done))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self) -> None:
        try:
            while True:
                result, callback = self._result_queue.get_nowait()
                self._set_busy(False)
                self.activity_var.set(result.message)
                if result.ok:
                    messagebox.showinfo(result.title, result.message, parent=self.root)
                else:
                    messagebox.showerror(result.title, result.message, parent=self.root)
                if callback:
                    callback(result)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_results)

    def open_activation(self) -> None:
        ActivationDialog(self, self._activate)

    def _activate(self, code: str, backend: str) -> None:
        self._run_async(
            lambda: activate_installation(code, backend),
            progress="Conectando este equipo con AIVA…",
            done=lambda result: self.root.after(100, self.choose_source) if result.ok else None,
        )

    def choose_source(self) -> None:
        initial = self._snapshot.input_dir if self._snapshot and self._snapshot.source_exists else str(Path.home())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Elegí la carpeta donde se generan las ventas",
            initialdir=initial,
            mustexist=True,
        )
        if not selected:
            return
        self._run_async(lambda: configure_source_folder(selected), progress="Guardando la carpeta de datos…")

    def test_connection(self) -> None:
        self._run_async(test_aiva_connection, progress="Probando la conexión segura con AIVA…")

    def sync_now(self) -> None:
        self._run_async(synchronize_now, progress="Buscando archivos nuevos y sincronizando…")

    def open_source_folder(self) -> None:
        path = self._snapshot.input_dir if self._snapshot and self._snapshot.input_dir else None
        if not path:
            self.choose_source()
            return
        result = open_folder(path)
        if not result.ok:
            messagebox.showerror(result.title, result.message, parent=self.root)

    def open_logs(self) -> None:
        result = open_folder(logs_folder())
        if not result.ok:
            messagebox.showerror(result.title, result.message, parent=self.root)

    def export_diagnostics(self) -> None:
        self._run_async(export_diagnostics, progress="Preparando diagnostico saneado...")


def self_check() -> int:
    required = (
        load_dashboard_snapshot,
        activate_installation,
        configure_source_folder,
        test_aiva_connection,
        synchronize_now,
    )
    if not all(callable(item) for item in required):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-check", action="store_true")
    args, unknown = parser.parse_known_args(argv)
    if args.self_check:
        return self_check()
    if unknown:
        return 2
    root = tk.Tk()
    CollectorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
