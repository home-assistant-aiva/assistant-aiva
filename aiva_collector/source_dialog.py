"""Supported desktop setup and preview, without scripts or database editing."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .source_setup import FIELDS, inspect_source, preview_source, save_source_preview


class SourceDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent.root)
        self.parent_app = parent
        self.title("Configurar archivo de ventas")
        self.geometry("820x760")
        self.transient(parent.root)
        self.grab_set()
        self.path = None
        self.preview = None
        panel = ttk.Frame(self, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="CSV o XLSX tabular · una fila por producto/venta · precio y costo unitarios").pack(anchor="w")
        ttk.Label(panel, text="Cada archivo debe contener todas las ventas de los días que declara completos.").pack(anchor="w")
        ttk.Label(panel, text="XLS, bases propietarias, devoluciones negativas y archivos de movimientos parciales no admiten cobertura completa.", wraplength=770).pack(anchor="w")
        self.file_label = ttk.Label(panel, text="Elegí una exportación para configurar y previsualizar.")
        self.file_label.pack(anchor="w", pady=6)
        ttk.Button(panel, text="Elegir archivo CSV / XLSX", command=self.choose).pack(anchor="w")
        options = ttk.Frame(panel)
        options.pack(fill="x", pady=8)
        ttk.Label(options, text="Hoja XLSX (vacía = automática)").grid(row=0, column=0)
        self.sheet = tk.StringVar()
        ttk.Entry(options, textvariable=self.sheet, width=23).grid(row=0, column=1)
        ttk.Label(options, text="Fila encabezado (1–25, vacía = auto)").grid(row=1, column=0)
        self.header = tk.StringVar()
        ttk.Entry(options, textvariable=self.header, width=8).grid(row=1, column=1, sticky="w")
        ttk.Button(options, text="Leer columnas", command=self.read).grid(row=0, column=2, rowspan=2, padx=12)
        self.form = ttk.Frame(panel)
        self.form.pack(fill="x")
        self.mapping = {}
        self.boxes = []
        for index, (key, label) in enumerate(FIELDS.items()):
            ttk.Label(self.form, text=label).grid(row=index//2, column=(index%2)*2, sticky="w", pady=3)
            variable = tk.StringVar()
            box = ttk.Combobox(self.form, textvariable=variable, state="readonly", width=23)
            box.grid(row=index//2, column=(index%2)*2+1, sticky="ew", padx=8)
            self.mapping[key] = variable
            self.boxes.append(box)
            variable.trace_add("write", self.invalidate)
        self.price = tk.StringVar()
        self.discount = tk.StringVar()
        self.prices = {"Bruto: antes del descuento": "gross_before_discount", "Neto: descuento ya incluido": "final_net"}
        self.discounts = {"Importe por unidad": "per_unit", "Importe por línea": "per_line", "Porcentaje sobre bruto (0–100)": "percentage"}
        for label, var, choices in [("El precio es", self.price, self.prices), ("El descuento es", self.discount, self.discounts)]:
            ttk.Label(panel, text=label).pack(anchor="w", pady=(8, 0))
            ttk.Combobox(panel, textvariable=var, values=list(choices), state="readonly", width=48).pack(anchor="w")
            var.trace_add("write", self.invalidate)
        self.timezone = tk.StringVar(value="America/Argentina/Buenos_Aires")
        ttk.Label(panel, text="Zona horaria del comercio (IANA)").pack(anchor="w", pady=(8, 0))
        ttk.Entry(panel, textvariable=self.timezone, width=45).pack(anchor="w")
        self.complete = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Confirmo que cada archivo contiene todas las ventas del comercio por cada día incluido.", variable=self.complete).pack(anchor="w", pady=8)
        ttk.Label(panel, text="Sin esta confirmación se guarda cobertura desconocida; días ausentes nunca se inventan como cero.", wraplength=770).pack(anchor="w")
        for var in (self.sheet, self.header, self.timezone, self.complete):
            var.trace_add("write", self.invalidate)
        self.result = tk.StringVar(value="La vista previa no envía datos. Confirmá los significados con quien genera la exportación.")
        ttk.Label(panel, textvariable=self.result, wraplength=770, justify="left").pack(fill="x", pady=12)
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Previsualizar cálculo y totales", command=self.calculate).pack(side="left")
        self.save_button = ttk.Button(buttons, text="Guardar configuración", state="disabled", command=self.save)
        self.save_button.pack(side="left", padx=12)
        ttk.Button(buttons, text="Cerrar", command=self.destroy).pack(side="right")

    def invalidate(self, *_):
        self.preview = None
        if hasattr(self, "save_button"):
            self.save_button.configure(state="disabled")

    def options(self):
        return {"sheet": self.sheet.get().strip(), "header_row": int(self.header.get()) if self.header.get().strip() else None}

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
            headers, _rows = inspect_source(self.path, **self.options())
            from .column_mapping import detect_column_mapping
            suggestion = detect_column_mapping(headers).mapping
            for (key, variable), box in zip(self.mapping.items(), self.boxes):
                box.configure(values=["", *headers])
                variable.set(suggestion.get(key, ""))
            self.invalidate()
        except Exception as exc:
            messagebox.showerror("Revisar exportación", str(exc), parent=self)

    def calculate(self):
        try:
            if not self.path:
                raise ValueError("Elegí un archivo de ventas.")
            self.preview = preview_source(self.path, {k: v.get() for k, v in self.mapping.items()},
                price=self.prices.get(self.price.get()), discount=self.discounts.get(self.discount.get()),
                complete=self.complete.get(), timezone_name=self.timezone.get().strip(), **self.options())
            totals = " · ".join(f"{k.replace('_', ' ')}: {v}" for k, v in self.preview["totals"].items())
            days = len(self.preview["summary"]["daily_snapshot"]["coverage"])
            self.result.set(self.preview["example"] + "\n" + totals + f"\nDías observados: {days}. Cobertura: " + ("completa declarada" if self.complete.get() else "desconocida"))
            self.save_button.configure(state="normal")
        except Exception as exc:
            self.invalidate()
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
