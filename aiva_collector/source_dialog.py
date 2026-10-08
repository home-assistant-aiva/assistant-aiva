"""Configuracion guiada del archivo de ventas, sin scripts ni bases de datos.

La pantalla muestra siempre como va a leer AIVA los datos reales: el comercio
ve "1.890 → 1.890" o "1.890 → 1,89" antes de guardar, que es la unica forma de
que detecte un formato mal interpretado sin saber nada tecnico.
"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .source_setup import (
    FIELDS,
    NUMBER_FORMATS,
    TIMEZONES,
    inspect_source,
    interpret_sample,
    preview_source,
    save_source_preview,
    suggest_mapping,
)

_REFRESH_DELAY_MS = 350


class SourceDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent.root)
        self.parent_app = parent
        self.title("Configurar archivo de ventas")
        screen_height = self.winfo_screenheight() or 768
        height = max(520, min(820, screen_height - 110))
        self.geometry(f"900x{height}")
        self.minsize(720, 480)
        self.transient(parent.root)
        self.grab_set()
        self.path = None
        self.preview = None
        self._refresh_job = None
        self._loading = False

        # Botones fijos abajo: siempre visibles aunque la pantalla sea chica.
        buttons = ttk.Frame(self, padding=(16, 8))
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Previsualizar cálculo y totales", command=self.calculate).pack(side="left")
        self.save_button = ttk.Button(buttons, text="Guardar configuración", state="disabled", command=self.save)
        self.save_button.pack(side="left", padx=12)
        ttk.Button(buttons, text="Cerrar", command=self.destroy).pack(side="right")

        # Contenido desplazable.
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        panel = ttk.Frame(self._canvas, padding=16)
        self._panel_window = self._canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _event: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda event: self._canvas.itemconfigure(self._panel_window, width=event.width))
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        ttk.Label(panel, text="CSV o XLSX tabular · una fila por producto vendido · precio y costo unitarios").pack(anchor="w")
        ttk.Label(panel, text="XLS, bases propietarias y devoluciones negativas no se admiten en esta fuente.", wraplength=820).pack(anchor="w")
        self.file_label = ttk.Label(panel, text="Elegí una exportación de ventas para configurar y previsualizar.")
        self.file_label.pack(anchor="w", pady=6)
        ttk.Button(panel, text="Elegir archivo CSV / XLSX", command=self.choose).pack(anchor="w")

        options = ttk.Frame(panel)
        options.pack(fill="x", pady=8)
        ttk.Label(options, text="Hoja XLSX (vacía = automática)").grid(row=0, column=0, sticky="w")
        self.sheet = tk.StringVar()
        ttk.Entry(options, textvariable=self.sheet, width=23).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(options, text="Fila de encabezado (1–25, vacía = automática)").grid(row=1, column=0, sticky="w")
        self.header = tk.StringVar()
        ttk.Entry(options, textvariable=self.header, width=8).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(options, text="Leer columnas", command=self.read).grid(row=0, column=2, rowspan=2, padx=12)

        ttk.Label(panel, text="¿Qué columna tiene cada dato? AIVA ya propone una; revisala.", font=("", 10, "bold")).pack(anchor="w", pady=(8, 2))
        self.form = ttk.Frame(panel)
        self.form.pack(fill="x")
        self.mapping = {}
        self.boxes = []
        for index, (key, label) in enumerate(FIELDS.items()):
            ttk.Label(self.form, text=label).grid(row=index // 2, column=(index % 2) * 2, sticky="w", pady=3)
            variable = tk.StringVar()
            box = ttk.Combobox(self.form, textvariable=variable, state="readonly", width=28)
            box.grid(row=index // 2, column=(index % 2) * 2 + 1, sticky="ew", padx=8)
            self.mapping[key] = variable
            self.boxes.append(box)
            variable.trace_add("write", self.invalidate)

        ttk.Label(panel, text="Formato de los números", font=("", 10, "bold")).pack(anchor="w", pady=(10, 0))
        self.number_format = tk.StringVar(value=next(iter(NUMBER_FORMATS)))
        ttk.Combobox(panel, textvariable=self.number_format, values=list(NUMBER_FORMATS), state="readonly", width=52).pack(anchor="w")
        self.number_format.trace_add("write", self.invalidate)
        self.numbers_info = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.numbers_info, wraplength=820, justify="left").pack(fill="x", pady=(4, 0))

        ttk.Label(panel, text="Así va a leer AIVA tus ventas", font=("", 10, "bold")).pack(anchor="w", pady=(10, 2))
        ttk.Label(panel, text="Columna izquierda de cada flecha: lo que dice tu archivo. Derecha: cómo lo entiende AIVA. Revisá que los precios coincidan.", wraplength=820).pack(anchor="w")
        table_frame = ttk.Frame(panel)
        table_frame.pack(fill="x", pady=4)
        self.table = ttk.Treeview(table_frame, columns=("row",), show="headings", height=8)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(xscrollcommand=x_scroll.set)
        self.table.pack(fill="x")
        x_scroll.pack(fill="x")
        self.table.tag_configure("problem", background="#fde2e1")
        self.table_info = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.table_info, wraplength=820, justify="left").pack(fill="x")

        self.price = tk.StringVar()
        self.discount = tk.StringVar()
        self.prices = {"Bruto: antes del descuento": "gross_before_discount", "Neto: descuento ya incluido": "final_net"}
        self.discounts = {"Importe por unidad": "per_unit", "Importe por línea": "per_line", "Porcentaje sobre bruto (0–100)": "percentage"}
        for label, var, choices in [("El precio es", self.price, self.prices), ("El descuento es", self.discount, self.discounts)]:
            ttk.Label(panel, text=label).pack(anchor="w", pady=(8, 0))
            ttk.Combobox(panel, textvariable=var, values=list(choices), state="readonly", width=48).pack(anchor="w")
            var.trace_add("write", self.invalidate)
        ttk.Label(panel, text="Si tu archivo no tiene descuentos, elegí cualquier opción: no cambia nada.", wraplength=820).pack(anchor="w")

        self.timezone = tk.StringVar(value=TIMEZONES[0])
        ttk.Label(panel, text="Zona horaria del comercio").pack(anchor="w", pady=(8, 0))
        self.timezone_box = ttk.Combobox(panel, textvariable=self.timezone, values=list(TIMEZONES), state="readonly", width=45)
        self.timezone_box.pack(anchor="w")
        self.complete = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Confirmo que cada archivo contiene todas las ventas del comercio por cada día incluido.", variable=self.complete).pack(anchor="w", pady=8)
        ttk.Label(panel, text="Sin esta confirmación se guarda cobertura desconocida; los días ausentes nunca se inventan como cero.", wraplength=820).pack(anchor="w")
        for var in (self.sheet, self.header, self.timezone, self.complete):
            var.trace_add("write", self.invalidate)

        self.result = tk.StringVar(value="La vista previa no envía datos. Confirmá los significados con quien genera la exportación.")
        ttk.Label(panel, textvariable=self.result, wraplength=820, justify="left").pack(fill="x", pady=12)

    # -- eventos -------------------------------------------------------------

    def _on_mousewheel(self, event):
        try:
            if self.winfo_exists() and self._canvas.winfo_exists():
                self._canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def invalidate(self, *_):
        self.preview = None
        if hasattr(self, "save_button"):
            self.save_button.configure(state="disabled")
        if not self._loading and self.path is not None and hasattr(self, "table"):
            if self._refresh_job is not None:
                self.after_cancel(self._refresh_job)
            self._refresh_job = self.after(_REFRESH_DELAY_MS, self.refresh_table)

    def options(self):
        header = self.header.get().strip()
        if header and not header.isdigit():
            raise ValueError("La fila de encabezado tiene que ser un número entre 1 y 25.")
        return {"sheet": self.sheet.get().strip(), "header_row": int(header) if header else None}

    def selected_mapping(self):
        return {key: variable.get() for key, variable in self.mapping.items()}

    def selected_number_format(self):
        return NUMBER_FORMATS.get(self.number_format.get(), "auto")

    def choose(self):
        value = filedialog.askopenfilename(parent=self, filetypes=[("Exportación de ventas", "*.csv *.xlsx")])
        if value:
            self.path = Path(value)
            self.file_label.configure(text=self.path.name)
            self.read()

    def read(self):
        if not self.path:
            return
        try:
            headers, rows = inspect_source(self.path, **self.options())
            suggestion = suggest_mapping(headers, rows)
            self._loading = True
            try:
                for (key, variable), box in zip(self.mapping.items(), self.boxes):
                    box.configure(values=["", *headers])
                    variable.set(suggestion.mapping.get(key, ""))
            finally:
                self._loading = False
            if suggestion.status != "auto_approved":
                self.result.set("AIVA propuso columnas con dudas. Revisá cada desplegable y mirá la tabla antes de previsualizar.")
            self.invalidate()
            self.refresh_table()
        except Exception as exc:
            messagebox.showerror("Revisar exportación", str(exc), parent=self)

    def refresh_table(self):
        """Actualiza la tabla de interpretacion. Nunca abre un error modal."""

        self._refresh_job = None
        if not self.path:
            return
        try:
            sample = interpret_sample(
                self.path, self.selected_mapping(), number_format=self.selected_number_format(),
                discount=self.discounts.get(self.discount.get()), **self.options(),
            )
        except Exception as exc:  # mapeo a medio elegir, hoja inexistente, etc.
            self.table_info.set(f"No se puede mostrar la tabla todavía: {exc}")
            return
        self.sample = sample
        columns = ["row", *[f"c{index}" for index in range(len(sample["columns"]))]]
        self.table.configure(columns=columns)
        self.table.heading("row", text="Fila")
        self.table.column("row", width=48, stretch=False, anchor="e")
        for index, title in enumerate(sample["columns"]):
            longest = max([len(title), *(len(str(item["cells"][index])) for item in sample["rows"])])
            self.table.heading(f"c{index}", text=title)
            self.table.column(f"c{index}", width=max(70, min(260, longest * 8 + 16)), stretch=True)
        self.table.delete(*self.table.get_children())
        for item in sample["rows"]:
            self.table.insert("", "end", values=(item["row"], *item["cells"]), tags=("problem",) if item["problem"] else ())
        problems = sum(1 for item in sample["rows"] if item["problem"])
        info = f"Mostrando {len(sample['rows'])} de {sample['total_rows']} ventas."
        if sample.get("skipped_total_rows"):
            info += f" Se ignora {sample['skipped_total_rows']} fila de TOTAL al pie."
        if problems:
            info += f" ⚠ {problems} fila(s) marcadas en rojo no se pueden leer: corregí la columna elegida o la exportación."
        self.table_info.set(info)
        lines = []
        for item in sample["numbers"]:
            line = f"{item['label']} ('{item['column']}'): {item['convention_label']}"
            if item["example"]:
                line += f" — {item['example']}"
            if item["ambiguous"]:
                line += ". ⚠ Ningún valor tiene decimales: si no es así, elegí el formato a mano."
            lines.append(line)
        lines.extend("⚠ " + warning if not warning.startswith("Control superado") else "✓ " + warning for warning in sample["warnings"])
        self.numbers_info.set("\n".join(lines))

    def calculate(self):
        try:
            if not self.path:
                raise ValueError("Elegí un archivo de ventas.")
            self.preview = preview_source(
                self.path, self.selected_mapping(),
                price=self.prices.get(self.price.get()), discount=self.discounts.get(self.discount.get()),
                complete=self.complete.get(), timezone_name=self.timezone.get().strip(),
                number_format=self.selected_number_format(), **self.options(),
            )
            shown = self.preview["totals_display"]
            totals = " · ".join(f"{key.replace('_', ' ')}: {value}" for key, value in shown.items())
            days = len(self.preview["summary"]["daily_snapshot"]["coverage"])
            lines = [self.preview["example"], totals,
                     f"Días observados: {days}. Cobertura: " + ("completa declarada" if self.complete.get() else "desconocida")]
            if self.preview["products_without_code"]:
                lines.append(f"{self.preview['products_without_code']} producto(s) sin código: AIVA los identifica por nombre y categoría.")
            if self.preview["skipped_total_rows"]:
                lines.append(f"Se ignoraron {len(self.preview['skipped_total_rows'])} fila(s) de TOTAL al pie del archivo.")
            for warning in self.preview["warnings"]:
                lines.append(("✓ " if warning.startswith("Control superado") else "⚠ ") + warning)
            self.result.set("\n".join(lines))
            self.save_button.configure(state="normal")
        except Exception as exc:
            self.preview = None
            self.save_button.configure(state="disabled")
            messagebox.showerror("Revisar cálculo", str(exc), parent=self)

    def save(self):
        if self.preview is None:
            return
        try:
            result = save_source_preview(self.preview)
            messagebox.showinfo(result.title, result.message, parent=self)
            self.parent_app.refresh()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("No se pudo guardar", str(exc), parent=self)

    def destroy(self):
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()
