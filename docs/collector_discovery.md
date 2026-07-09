# AIVA Collector Discovery

## Objetivo

Discovery detecta posibles fuentes de datos en la PC Windows del comercio para que el instalador las confirme luego en Admin, en la pestaña Fuentes de datos.

## Que detecta

- Carpetas candidatas para `watched_folder`.
- Archivos candidatos `.csv`, `.xlsx`, `.xls`.
- Archivos `.txt` solo cuando el nombre parece reporte comercial.
- Bases locales por extension: SQLite (`.db`, `.sqlite`, `.sqlite3`), Access (`.mdb`, `.accdb`) y Firebird (`.fdb`, `.gdb`).
- Servicios Windows instalados de SQL Server, MySQL, PostgreSQL y Firebird mediante consulta de servicios. No se conecta a esas bases.

## Que no hace

- No lee ventas reales desde bases.
- No abre conexiones a SQL Server, MySQL, PostgreSQL ni Firebird.
- No ejecuta consultas.
- No sube archivos.
- No copia archivos.
- No borra ni modifica archivos del comercio.
- No lee contenido comercial completo.
- No envia Telegram.
- No usa GPT ni LLM.

## Seguridad y privacidad

Discovery trabaja en modo seguro por defecto. Para archivos usa metadata: nombre, extension, tamano y fecha de modificacion. Los ejemplos enviados son solo nombres de archivo, sin rutas completas. `detected_path` se envia porque el instalador lo necesita para confirmar la fuente.

No se guardan tokens ni secretos en config. Si el backend no esta disponible, los discoveries pendientes se guardan en la cola offline existente como payload JSON sanitizado, sin archivos originales ni contenido de filas.

## Carpetas escaneadas

Por defecto escanea de forma limitada:

- `Desktop`, `Documents`, `Downloads` del usuario actual.
- `C:\AIVA`
- `C:\AIVA\Comercial`
- `C:\AIVA\Comercial\Entrada`
- `C:\Sistema`
- `C:\Sistemas`
- `C:\Gestion`
- `C:\Gestión`
- `C:\Ventas`
- `C:\Reportes`
- `C:\Reportes\Ventas`
- `C:\Datos`
- `C:\Data`
- `C:\Backups`
- `C:\Program Files`
- `C:\Program Files (x86)`

No recorre todo `C:\` salvo que se configure `include_drive_roots=true`.

## Exclusiones

No entra en rutas sensibles o ruidosas como:

- `C:\Windows`
- `C:\Windows\System32`
- `C:\System Volume Information`
- `C:\$Recycle.Bin`
- perfiles de navegador bajo `AppData`
- `AppData\Local\Temp`
- `node_modules`
- `.git`
- `__pycache__`
- `venv`
- `.venv`
- carpetas ocultas cuando sea posible

## Scoring

La confianza queda entre `0.0` y `1.0`.

- Alta: rutas tipo `C:\AIVA\Comercial\Entrada`, carpetas Reportes/Ventas con varios CSV/XLSX, o varios archivos con nombres de ventas/stock/productos.
- Media: Documents/Downloads con archivos comerciales.
- Baja: senales debiles, archivos viejos o rutas genericas.

Por defecto no reporta candidatos con confianza menor a `0.25`, limita a 100 candidatos por corrida y reporta como maximo 20.

## Payload

El Collector prepara metadata segura. En backend 6.4A el schema acepta los campos principales y el servicio persiste el request saneado como `raw_discovery_json`; por compatibilidad, el Collector no envia un campo explicito `raw_discovery` hasta que el schema lo permita.

```json
{
  "source_type": "watched_folder",
  "name": "Reportes detectados",
  "detected_path": "C:\\Sistema\\Reportes",
  "confidence": 0.85,
  "capabilities": {
    "files": true,
    "csv": true,
    "xlsx": true
  },
  "sample_metadata": {
    "files_found": 3,
    "examples": ["ventas.xlsx", "stock.xlsx"]
  }
}
```

Para bases por archivo agrega `detected_engine`, `database_file=true` y `connection_not_attempted=true`.

## Comandos

Dry-run, no envia nada:

```bash
python -m aiva_collector.cli discover --config config.local.json --dry-run
```

Salida JSON estable para QA:

```bash
python -m aiva_collector.cli discover --config config.local.json --dry-run --json
```

Escaneo de una ruta controlada:

```bash
python -m aiva_collector.cli discover --config config.local.json --dry-run --include-path /tmp/aiva-discovery-test
```

Reporte al backend:

```bash
python -m aiva_collector.cli discover --config config.local.json --report
```

El endpoint de FASE 6.4A es admin y requiere `X-AIVA-Secret`. Si se usa ese endpoint desde Collector, configurar una variable de entorno segura y referenciarla con:

```json
{
  "discovery_admin_secret_env": "AIVA_DISCOVERY_ADMIN_SECRET"
}
```

La variable debe contener el secret interno del backend. No guardarlo en archivos ni compartirlo por chat.

## Offline

Si hay error temporal de red o backend 5xx, el discovery queda en la cola offline existente y `retry-pending` lo reintenta. Si el error es de auth o schema, se informa claramente y no se imprime ningun secreto.

## Relacion con Admin

Los discoveries aparecen en Admin > Fuentes de datos > Fuentes detectadas. El instalador debe convertir una deteccion en fuente antes de activarla.

## Proximos pasos

- FASE 6.4C: sync automatico desde fuente confirmada.
- FASE 6.4D: API REST.
- FASE 6.4E: lectura real de base local confirmada.
