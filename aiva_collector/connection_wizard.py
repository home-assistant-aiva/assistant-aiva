"""Tk connection workflow. Reader operations run outside the UI thread."""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config_discovery import resolve_runtime_config
from .connection_config import digest, load_connection, period, set_paused
from .connection_setup import activate, detect_options, load_draft, preview, save_draft, source_identity
from .connection_sync import state_path, synchronize
from .connectors import create_connector
from .connectors.base import AccessError, safe_error
from .source_credentials import CredentialVault

FIELDS = ('fecha', 'producto_codigo', 'producto_nombre', 'categoria', 'cantidad_vendida', 'precio_venta',
          'descuento', 'costo_unitario', 'stock_actual', 'fecha_stock')
LABELS = {'files': 'Archivos CSV/Excel', 'rest': 'API REST', 'sqlite': 'Base SQLite (solo lectura)',
          'odbc': 'SQL Server por ODBC', 'unknown': 'No sé qué sistema tengo'}


class ConnectionWizard(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('Asistente de conexión AIVA')
        self.geometry('1000x700')
        self.minsize(850, 650)
        self.collector_config = resolve_runtime_config().config
        self.context = __import__('aiva_collector.connection_config', fromlist=['context']).context(self.collector_config)
        self.reviewed = None
        self.sample = []
        self.credentials = {}
        self.busy = False
        self.messages = queue.Queue()
        self.vars = {}
        self.mapping = {}
        self.profile = {}
        self.expected_profile = None
        self.book = ttk.Notebook(self)
        self.book.pack(fill='both', expand=True, padx=15, pady=10)
        self.pages = []
        for label in ('1. Origen', '2. Acceso', '3. Campos', '4. Historial', '5. Revisión'):
            shell = ttk.Frame(self.book)
            self.book.add(shell, text=label)
            canvas = tk.Canvas(shell, highlightthickness=0)
            scroll = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True)
            page = ttk.Frame(canvas, padding=14)
            window = canvas.create_window((0, 0), window=page, anchor='nw')
            page.bind('<Configure>', lambda event, c=canvas: c.configure(scrollregion=c.bbox('all')))
            canvas.bind('<Configure>', lambda event, c=canvas, w=window: c.itemconfigure(w, width=event.width))
            self.pages.append(page)
        self.status = tk.StringVar(value='Elegí una alternativa. Detectar no prueba el acceso ni los datos.')
        ttk.Label(self, textvariable=self.status, wraplength=940).pack(fill='x', padx=20, pady=8)
        footer = ttk.Frame(self, padding=12)
        footer.pack(fill='x')
        ttk.Button(footer, text='Guardar y continuar más tarde', command=self.save_progress).pack(side='left')
        ttk.Button(footer, text='Cerrar', command=self.destroy).pack(side='right')
        self._origin()
        self._access()
        self._fields()
        self._history()
        self._review()
        self.restore()
        self.after(100, self.poll)

    def entry(self, page, key, label, value='', *, secret=False):
        ttk.Label(page, text=label).pack(anchor='w', pady=(7, 2))
        var = tk.StringVar(value=value)
        self.vars[key] = var
        ttk.Entry(page, textvariable=var, show='•' if secret else '').pack(fill='x')
        return var

    def _origin(self):
        p = self.pages[0]
        ttk.Label(p, text='Comercio: ' + self.collector_config.commerce_id + ' · Collector: ' + self.collector_config.collector_id, wraplength=900).pack(anchor='w')
        self.kind = tk.StringVar(value='files')
        for key, label in LABELS.items():
            ttk.Radiobutton(p, text=label, variable=self.kind, value=key, command=self.select_kind).pack(anchor='w', pady=3)
        self.consent = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, variable=self.consent, text='Autorizo consultar nombres de DSN/controladores y la carpeta que elija; no buscar contraseñas.').pack(anchor='w', pady=12)
        ttk.Button(p, text='Detectar opciones disponibles en una carpeta elegida', command=self.detect).pack(anchor='w')
        self.options = tk.Text(p, height=13, wrap='word')
        self.options.pack(fill='both', expand=True, pady=8)
        self.options.insert('end', 'Si el sistema no permite exportar ni tiene API/base autorizada, pedile al proveedor una exportación tabular con fecha, producto, cantidad y precio unitario. No se automatizan pantallas.\n')

    def _access(self):
        p = self.pages[1]
        ttk.Label(p, text='API y ODBC requieren un perfil JSON documentado del proveedor. Los ejemplos incluidos son sintéticos; no certifican marcas comerciales.', wraplength=900).pack(anchor='w')
        ttk.Button(p, text='Cargar perfil de integración JSON', command=self.import_profile).pack(anchor='w', pady=8)
        self.form = ttk.Frame(p)
        self.form.pack(fill='x')
        self.auth_form = ttk.Frame(p)
        self.auth_form.pack(fill='x')
        ttk.Button(p, text='Probar conexión y leer muestra acotada', command=self.test_access).pack(anchor='w', pady=14)
        self.access_result = tk.Text(p, height=6, wrap='word')
        self.access_result.pack(fill='both', expand=True)
        self.select_kind()

    def select_kind(self):
        for child in self.form.winfo_children():
            child.destroy()
        for child in self.auth_form.winfo_children():
            child.destroy()
        kind = self.kind.get()
        self.sample, self.reviewed = [], None
        self.credentials = {}
        self.profile = {'kind': kind, 'timezone': 'America/Argentina/Buenos_Aires', 'semantics': 'whole_day_snapshot'}
        if kind == 'files':
            self.entry(self.form, 'source_path', 'Archivo CSV/XLSX de referencia')
            ttk.Button(self.form, text='Elegir archivo', command=self.choose_file).pack(anchor='w', pady=4)
            self.entry(self.form, 'sheet', 'Hoja XLSX (vacía: detección; se procesa una sola hoja)')
            self.entry(self.form, 'header', 'Fila de encabezado XLSX (1 a 25; vacía: detectar)')
        elif kind == 'sqlite':
            self.entry(self.form, 'source_path', 'Archivo de base SQLite autorizado (no es la SQLite interna de AIVA)')
            ttk.Button(self.form, text='Elegir base', command=self.choose_file).pack(anchor='w', pady=4)
            self.entry(self.form, 'table', 'Tabla ordinaria autorizada')
            self.entry(self.form, 'columns', 'Columnas necesarias separadas por coma (no incluir datos personales)')
            self.entry(self.form, 'date_column', 'Columna de fecha ISO o timestamp ISO de venta')
        elif kind in {'rest', 'odbc'}:
            self.entry(self.form, 'provider', 'Nombre del sistema/proveedor (informativo)')
            self.entry(self.form, 'documentation', 'URL de documentación (informativa; AIVA no inventa rutas)')
            ttk.Label(self.form, text='Cargá un perfil revisado que defina rutas o tablas, filtros de fecha, campos, autenticación y paginación.', wraplength=900).pack(anchor='w', pady=12)
        else:
            ttk.Label(self.form, text='Consultá el nombre y versión del sistema y si permite exportar CSV/XLSX, API documentada o una cuenta de base en solo lectura. Podés usar Detectar con autorización.', wraplength=900).pack(anchor='w')

    def choose_file(self):
        types = [('CSV/XLSX', '*.csv *.xlsx')] if self.kind.get() == 'files' else [('SQLite', '*.db *.sqlite *.sqlite3')]
        selected = filedialog.askopenfilename(parent=self, filetypes=types)
        if selected:
            self.vars['source_path'].set(selected)

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Perfil JSON', '*.json')])
        if not path:
            return
        try:
            if Path(path).stat().st_size > 100000:
                raise AccessError('profile_limit', 'El perfil es demasiado grande.')
            from .connection_config import validate_profile
            value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            validate_profile(value)
            self.kind.set(value['kind'])
            self.select_kind()
            self.profile = value
            self.fill_profile_controls(value)
            self.credentials = {}
            self.auth_controls()
            self.status.set('Perfil cargado. Todavía no se probaron el acceso ni los campos.')
        except Exception as exc:
            self.show_error(exc)

    def fill_profile_controls(self, profile):
        if profile['kind'] == 'sqlite':
            for key, value in [('source_path', profile['path']), ('table', profile['table']), ('columns', ','.join(profile['columns'])), ('date_column', profile['date_column'])]:
                self.vars[key].set(value)
        elif profile['kind'] == 'files':
            folder = Path(profile['folder'])
            source = next((f for f in folder.iterdir() if f.suffix.lower() == profile.get('suffix')), None) if folder.exists() else None
            self.vars['source_path'].set(str(source or ''))
            self.vars['sheet'].set(profile.get('reader', {}).get('xlsx_sheet', ''))
            self.vars['header'].set(profile.get('reader', {}).get('xlsx_header_row') or '')
        self.vars['timezone'].set(profile.get('timezone', 'America/Argentina/Buenos_Aires'))
        self.vars['cost_basis'].set(profile.get('cost_basis', 'unknown'))
        for key, field in [('price', 'price_semantics'), ('discount', 'discount_semantics')]:
            self.vars[key].set(profile.get('reader', {}).get(field, self.vars[key].get()))
        self.complete.set(profile.get('complete_days', False))

    def auth_controls(self):
        for child in self.auth_form.winfo_children():
            child.destroy()
        auth = self.profile.get('auth', 'none')
        if auth in {'basic', 'database_password'}:
            self.entry(self.auth_form, 'credential_user', 'Usuario específico de API/base (no contraseña de la aplicación)')
            self.entry(self.auth_form, 'credential_password', 'Contraseña de API/base', secret=True)
        elif auth in {'bearer', 'api_key'}:
            self.entry(self.auth_form, 'credential_token', 'Token o clave API', secret=True)
        elif auth == 'oauth_pkce':
            ttk.Button(self.auth_form, text='Autorizar con el proveedor (OAuth PKCE)', command=self.authorize).pack(anchor='w')
        elif auth == 'windows_integrated':
            ttk.Label(self.auth_form, text='Se usará la identidad de la sesión de Windows. Esa misma cuenta debe ejecutar el proceso background.').pack(anchor='w')
        ttk.Button(self.auth_form, text='Eliminar credenciales guardadas', command=self.delete_credentials).pack(anchor='w', pady=5)

    def get_profile(self):
        profile = dict(self.profile)
        if profile['kind'] == 'files':
            path = Path(self.vars['source_path'].get()).resolve(strict=True)
            if path.suffix.lower() not in {'.csv', '.xlsx'}:
                raise AccessError('format_unsupported', 'Sólo CSV y XLSX; no se admite XLS.')
            profile.update(folder=str(path.parent), suffix=path.suffix.lower())
            reader = dict(profile.get('reader', {}))
            reader['xlsx_sheet'] = self.vars['sheet'].get()
            reader['xlsx_header_row'] = int(self.vars['header'].get()) if self.vars['header'].get() else None
            profile['reader'] = reader
        elif profile['kind'] == 'sqlite':
            profile.update(path=self.vars['source_path'].get(), table=self.vars['table'].get(),
                           columns=[x.strip() for x in self.vars['columns'].get().split(',')], date_column=self.vars['date_column'].get())
        if hasattr(self, 'complete'):
            profile.update(complete_days=self.complete.get(), timezone=self.vars['timezone'].get(),
                           cost_basis=self.vars['cost_basis'].get(), number_format=self.vars['numbers'].get())
            profile['reader'] = {**profile.get('reader', {}), 'price_semantics': self.vars['price'].get(),
                                 'discount_semantics': self.vars['discount'].get()}
        return profile

    def get_secrets(self):
        auth = self.profile.get('auth', 'none')
        result = dict(self.credentials)
        if auth in {'basic', 'database_password'}:
            if self.vars.get('credential_password') and self.vars['credential_password'].get():
                result = {'username': self.vars['credential_user'].get(), 'password': self.vars['credential_password'].get()}
        elif auth in {'bearer', 'api_key'}:
            if self.vars.get('credential_token') and self.vars['credential_token'].get():
                result = {'access_token' if auth == 'bearer' else 'api_key': self.vars['credential_token'].get()}
        return result

    def _fields(self):
        p = self.pages[2]
        ttk.Label(p, text='Propuestas locales por reglas. Confirmá cada columna y el significado económico antes de activar.', wraplength=900).pack(anchor='w')
        grid = ttk.Frame(p)
        grid.pack(fill='x')
        self.combos = {}
        for i, field in enumerate(FIELDS):
            ttk.Label(grid, text=field).grid(row=i, column=0, sticky='w', pady=2)
            variable = tk.StringVar()
            self.mapping[field] = variable
            combo = ttk.Combobox(grid, textvariable=variable, state='readonly', width=65)
            combo.grid(row=i, column=1, sticky='ew', padx=10)
            self.combos[field] = combo
        for key, label, values, default in (
            ('numbers', 'Formato numérico', ('auto', 'comma', 'dot'), 'auto'),
            ('price', 'Significado del precio', ('final_net', 'gross_before_discount'), 'final_net'),
            ('discount', 'Descuento', ('per_unit', 'per_line', 'percentage'), 'per_line'),
            ('cost_basis', 'Costo informado', ('unknown', 'historical', 'current'), 'unknown')):
            ttk.Label(p, text=label).pack(anchor='w', pady=(5, 0))
            var = tk.StringVar(value=default)
            self.vars[key] = var
            ttk.Combobox(p, textvariable=var, values=values, state='readonly').pack(fill='x')

    def _history(self):
        p = self.pages[3]
        self.vars['days'] = tk.StringVar(value='90')
        ttk.Label(p, text='Historial en días: termina por defecto en el último día cerrado. 90 días no son tres meses calendario.').pack(anchor='w')
        ttk.Combobox(p, textvariable=self.vars['days'], values=('30','90','180','365','personalizado'), state='readonly').pack(fill='x', pady=5)
        self.entry(p, 'start', 'Desde personalizado (AAAA-MM-DD)')
        self.entry(p, 'end', 'Hasta personalizado (AAAA-MM-DD)')
        self.entry(p, 'timezone', 'Zona horaria IANA del comercio', 'America/Argentina/Buenos_Aires')
        self.today = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, variable=self.today, text='Incluir hoy: se marcará como parcial').pack(anchor='w', pady=8)
        self.complete = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, variable=self.complete, text='Confirmo con el proveedor: cada lectura contiene todas las ventas de cada día incluido.').pack(anchor='w', pady=8)
        self.vars['frequency'] = tk.StringVar(value='15')
        ttk.Label(p, text='Frecuencia en minutos (la tarea consulta al iniciar sesión y cada 15 minutos)').pack(anchor='w')
        ttk.Combobox(p, textvariable=self.vars['frequency'], values=('15','30','60','180','360','1440'), state='readonly').pack(fill='x')
        self.entry(p, 'review_days', 'Ventana reciente de revisión de correcciones (días completos)', '7')
        ttk.Label(p, text='Para ampliar historial, elegí un rango mayor y volvé a confirmar. El archivo ya visto se reevalúa con la nueva configuración. Las fechas ausentes siguen sin información.', wraplength=900).pack(anchor='w', pady=12)

    def get_window(self):
        custom = self.vars['days'].get() == 'personalizado'
        if custom and (not self.vars['start'].get() or not self.vars['end'].get()):
            raise AccessError('period_invalid', 'Completá desde y hasta.')
        return period(days=90 if custom else int(self.vars['days'].get()), timezone=self.vars['timezone'].get(),
            start=self.vars['start'].get() if custom else None, end=self.vars['end'].get() if custom else None, include_today=self.today.get())

    def _review(self):
        p = self.pages[4]
        ttk.Button(p, text='Previsualizar lectura y revisar período', command=self.preview).pack(anchor='w')
        self.review_text = tk.Text(p, wrap='word', height=18)
        self.review_text.pack(fill='both', expand=True, pady=8)
        self.confirm = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, variable=self.confirm, text='Confirmé campos, unidades, precios, costos, cobertura, rango y frecuencia.').pack(anchor='w')
        ttk.Button(p, text='Guardar fuente y ejecutar primera sincronización supervisada', command=self.activate).pack(anchor='w', pady=8)
        row = ttk.Frame(p)
        row.pack(fill='x')
        ttk.Button(row, text='Pausar', command=lambda: self.pause(True)).pack(side='left')
        ttk.Button(row, text='Reanudar', command=lambda: self.pause(False)).pack(side='left')
        ttk.Button(row, text='Sincronizar ahora', command=lambda: self.run(lambda: synchronize(resolve_runtime_config().config, force=True), self.sync_result)).pack(side='left')

    def run(self, work, done):
        if self.busy:
            self.status.set('Esperá a que termine la operación actual.')
            return
        self.busy = True
        self.status.set('Leyendo de forma acotada…')
        def target():
            try:
                self.messages.put((True, work(), done))
            except Exception as exc:
                self.messages.put((False, safe_error(exc), done))
        threading.Thread(target=target, daemon=True).start()

    def poll(self):
        try:
            ok, result, done = self.messages.get_nowait()
            self.busy = False
            if ok:
                done(result)
            else:
                self.status.set(result['code'] + ': ' + result['message'])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def show_error(self, exc):
        error = safe_error(exc)
        self.status.set(error['code'] + ': ' + error['message'])

    def test_access(self):
        try:
            profile, window, credentials = self.get_profile(), self.get_window(), self.get_secrets()
            # Files need a date column to count the selected range. Read the selected
            # workbook as a bounded sample before any date mapping is proposed.
            if profile['kind'] == 'files':
                source_path = self.vars['source_path'].get()
                def work():
                    from .readers import read_file
                    from .connectors.base import bounded_rows
                    path = Path(source_path)
                    if path.stat().st_size > 50000000:
                        raise AccessError('file_limit', 'Pedí un archivo menor a 50 MB.')
                    rows = bounded_rows(read_file(path, __import__('aiva_collector.config', fromlist=['CollectorConfig']).CollectorConfig({**profile['reader'], 'max_input_rows': 50000}, self.collector_config.config_path)), 50000)
                    return {'fields': list(rows[0]) if rows else [], 'sample': rows[:100]}
            else:
                def work():
                    with create_connector(profile, credentials) as connector:
                        return connector.test(window)
            def done(result):
                self.sample = result['sample']
                self.expected_profile = digest(profile)
                from .column_mapping import detect_column_mapping
                suggested = detect_column_mapping(result['fields'], self.sample, fill_from_values=True)
                for field, variable in self.mapping.items():
                    self.combos[field]['values'] = ('', *result['fields'])
                    variable.set(profile.get('mapping', {}).get(field, suggested.mapping.get(field, '')))
                self.access_result.delete('1.0', 'end')
                self.access_result.insert('end', 'Acceso probado. Campos encontrados: ' + ', '.join(result['fields']) + '\nFalta revisar mapeo, cobertura y período; conectar no habilita todas las funciones.')
                self.status.set('Acceso correcto; revisá los campos y sus ejemplos.')
                self.book.select(2)
            self.run(work, done)
        except Exception as exc:
            self.show_error(exc)

    def preview(self):
        try:
            profile, window = self.get_profile(), self.get_window()
            mapping = {k: v.get() for k, v in self.mapping.items() if v.get()}
            if self.expected_profile != digest(profile):
                raise AccessError('access_test_required', 'Cambió el acceso o sus opciones. Volvé a Probar conexión antes de revisar.')
            reviewed = preview(self.collector_config, profile, mapping, window, self.get_secrets(), sample=self.sample)
            self.reviewed = reviewed
            self.form_signature = self.signature()
            self.confirm.set(False)
            self.review_text.delete('1.0', 'end')
            self.review_text.insert('end', f"Comercio: {self.collector_config.commerce_id}\nFuente: {profile['kind']}\nPeríodo solicitado: {window.start} a {window.end}\nFrecuencia: {self.vars['frequency'].get()} minutos; revisión: {self.vars['review_days'].get()} días\nCobertura: {'declarada por el usuario; pendiente de lectura completa' if self.complete.get() else 'desconocida'}\nMuestra acotada; no demuestra toda la cobertura ni los totales del período. Rango encontrado en la muestra: {reviewed['found_window']['start']} a {reviewed['found_window']['end']}. Dentro: {reviewed['counts']['inside']}; fuera: {reviewed['counts']['outside']}.\nCampos faltantes: {', '.join(k for k in FIELDS if k not in mapping)}\nFormato ambiguo: {', '.join(reviewed['ambiguous']) or 'sin aviso'}\n")
            self.review_text.insert('end', '\nTotales de la muestra (no del período completo): ' + json.dumps(reviewed['sample_totals'], ensure_ascii=False) + '\n')
            self.review_text.insert('end', '\nEjemplos locales: origen → interpretación\n')
            for row in reviewed['examples']:
                self.review_text.insert('end', ' | '.join(f"{k}: {v['source']} → {v['interpreted']}" for k,v in row.items()) + '\n')
            self.review_text.insert('end', '\nFunciones: se consultarán al Backend tras recibir los datos; sin costos históricos, stock vigente o días completos pueden quedar limitadas.\n')
            self.status.set('Vista previa lista para revisar. No se enviaron datos.')
        except Exception as exc:
            self.show_error(exc)

    def signature(self):
        return digest([self.get_profile(), {k:v.get() for k,v in self.mapping.items()}, str(self.get_window()),
                       self.vars['frequency'].get(), self.vars['review_days'].get(), self.get_secrets()])

    def activate(self):
        try:
            if not self.reviewed or not self.confirm.get() or self.signature() != self.form_signature:
                raise AccessError('confirmation_required', 'Volvé a previsualizar y confirmar la configuración vigente.')
            config = resolve_runtime_config().config
            reviewed, credentials = self.reviewed, self.get_secrets()
            frequency, days = int(self.vars['frequency'].get()), int(self.vars['review_days'].get())
            def work():
                activate(config, reviewed, frequency=frequency, review_days=days, secrets=credentials)
                return synchronize(config, force=True)
            self.run(work, self.sync_result)
        except Exception as exc:
            self.show_error(exc)

    def sync_result(self, result):
        self.status.set(f"{result['state']}: {result.get('message', '')} Enviados: {result.get('sent', 0)}. Sin duplicar: {result.get('duplicates', 0)}. Días sin información: {result.get('missing_days', 0)}.")
        self.review_text.insert('end', f"\nCobertura de esta ejecución: completos {len(result.get('complete_dates', []))}; parciales/desconocidos {len(result.get('partial_dates', []))}; sin información {len(result.get('missing_dates', []))}.\n")
        self.review_text.insert('end', '\nResultado del Backend:\n' + json.dumps(result.get('capabilities', 'Disponibilidad no informada por este Backend.'), ensure_ascii=False, indent=2) + '\n')

    def pause(self, paused):
        try:
            from .connection_sync import connection_lock
            with connection_lock(self.collector_config):
                set_paused(self.collector_config, paused)
            self.status.set('Fuente pausada.' if paused else 'Fuente reanudada; se conserva el avance confirmado.')
        except Exception as exc:
            self.show_error(exc)

    def authorize(self):
        from .oauth_access import authorize
        self.run(lambda: authorize(self.profile), lambda value: (setattr(self, 'credentials', value), self.status.set('Autorización recibida en memoria; se protegerá al confirmar la fuente.')))

    def delete_credentials(self):
        try:
            setup = load_connection(self.collector_config)
            if setup:
                CredentialVault(self.collector_config, setup['source_id']).delete()
                set_paused(self.collector_config, True)
            self.credentials = {}
            for key in ('credential_user', 'credential_password', 'credential_token'):
                if key in self.vars:
                    self.vars[key].set('')
            self.reviewed = None
            self.status.set('Credenciales locales eliminadas y fuente pausada. Revocá también el acceso en el proveedor si corresponde.')
        except Exception as exc:
            self.show_error(exc)

    def detect(self):
        if not self.consent.get():
            self.show_error(AccessError('consent_required', 'Marcá la autorización antes de inspeccionar conexiones o rutas.'))
            return
        selected = filedialog.askdirectory(parent=self)
        self.run(lambda: detect_options(self.collector_config, [selected] if selected else [], consent=True), self.show_options)

    def show_options(self, options):
        self.options.delete('1.0', 'end')
        for item in options:
            self.options.insert('end', f"{item['label']} — {item['state']} — confianza de detección {item['confidence']}\nFalta: {item['missing']}\nMotivos: {', '.join(item['reasons'])}\n\n")
        self.status.set('Alternativas detectadas. Elegí una; ninguna se activa automáticamente.')

    def save_progress(self):
        try:
            values = {k:v.get() for k,v in self.vars.items() if not k.startswith('credential_')}
            save_draft(self.collector_config, {'kind': self.kind.get(), 'profile': self.profile, 'values': values,
                                     'mapping': {k:v.get() for k,v in self.mapping.items()}, 'complete': self.complete.get(), 'today': self.today.get()})
            self.status.set('Avance guardado sin secretos ni muestras. Al volver, probá acceso y confirmá nuevamente.')
        except Exception as exc:
            self.show_error(exc)

    def restore(self):
        try:
            draft = load_draft(self.collector_config)
            setup = load_connection(self.collector_config)
            if draft:
                self.kind.set(draft['kind'])
                self.select_kind()
                self.profile = draft['profile']
                self.auth_controls()
                for k,v in draft['values'].items():
                    if k in self.vars:
                        self.vars[k].set(v)
                self.complete.set(draft.get('complete', False))
                self.today.set(draft.get('today', False))
                for k,v in draft.get('mapping', {}).items():
                    self.combos[k]['values'] = ('', v)
                    self.mapping[k].set(v)
            elif setup:
                self.kind.set(setup['profile']['kind'])
                self.select_kind()
                self.profile = setup['profile']
                self.auth_controls()
                p = self.profile
                if p['kind'] == 'files':
                    folder = Path(p['folder'])
                    file = next((f for f in folder.iterdir() if f.suffix.lower() == p.get('suffix')), None)
                    self.vars['source_path'].set(str(file or ''))
                    self.vars['sheet'].set(p.get('reader', {}).get('xlsx_sheet', ''))
                    self.vars['header'].set(p.get('reader', {}).get('xlsx_header_row') or '')
                elif p['kind'] == 'sqlite':
                    for key, value in [('source_path', p['path']), ('table', p['table']), ('columns', ','.join(p['columns'])), ('date_column', p['date_column'])]:
                        self.vars[key].set(value)
                self.vars['timezone'].set(p['timezone'])
                self.vars['days'].set('personalizado')
                self.vars['start'].set(setup['window']['start'])
                self.vars['end'].set(setup['window']['end'])
                self.vars['frequency'].set(str(setup['frequency_minutes']))
                self.vars['review_days'].set(str(setup['review_days']))
                self.complete.set(p.get('complete_days', False))
                for key in ('price', 'discount'):
                    self.vars[key].set(p.get('reader', {}).get('price_semantics' if key == 'price' else 'discount_semantics', self.vars[key].get()))
                self.vars['cost_basis'].set(p.get('cost_basis', 'unknown'))
                self.credentials = CredentialVault(self.collector_config, setup['source_id']).load()
            if state_path(self.collector_config).exists():
                status = json.loads(state_path(self.collector_config).read_text())
                self.status.set(f"Último estado: {status.get('state')}. Última recepción confirmada: {status.get('last_success') or 'ninguna'}. {status.get('message', '')}")
        except Exception as exc:
            self.show_error(exc)
