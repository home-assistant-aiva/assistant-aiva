# Fuente diaria v2 y reproceso selectivo

RC7 conserva la configuración y SQLite de RC6. Una sincronización ordinaria no vuelve a procesar un archivo `sent`; `retry-pending` sólo reenvía payloads ya presentes en la cola. La selección del mapping ahora usa fecha y código detectables cuando un mapping activo de Backend los omite. Un `source_schema_version=1.0.0` explícito sigue siendo v1 hasta configurar la fuente.

## Piloto sintético completo

La carpeta de piloto debe contener sólo un CSV/XLSX compatible. El manifiesto debe acompañar al archivo e identificar un generador por SHA-256, el digest exacto, la zona horaria, el catálogo cerrado y el período. `configure-daily-source` verifica que exista exactamente una observación por fecha y producto del catálogo, incluso los días de venta cero, y que no haya filas descartadas ni descuentos distintos de cero. Guarda una copia de la configuración previa, selecciona el mapping diario y fija la declaración de completitud **sólo para ese digest**. Un archivo posterior con otro digest tendrá cobertura `unknown`.

Ejemplo para soporte, con ruta del ejecutable y carpeta elegidas en la instalación autorizada:

```powershell
aiva-collector-cli.exe configure-daily-source --config "$env:ProgramData\AIVA\Collector\config.windows.json" --file "C:\AIVA-Piloto-Sintetico\Ventas_demo_completas_35d_2026-08-25_a_2026-09-28.xlsx" --manifest "C:\AIVA-Piloto-Sintetico\manifest.json" --expected-sha256 "2a173badfd6bad847af779d89b947139110af3a3d0108601edb05a96e53f2cd3" --expected-commerce-id "commerce_a0e93d3ec7ac" --expected-collector-id "collector_dc15555b7052" --source-id "aiva_demo_synthetic_20260929_complete" --timezone "America/Argentina/Buenos_Aires"
```

La carpeta también incluye `generator.py` para auditar la construcción del libro. El comando anterior cambia sólo la configuración local, no envía datos. Verificar en el archivo instalado la identidad, `source_schema_version=2.0.0`, `daily_source_id`, mapping, zona horaria, `price_semantics=final_net` y `daily_complete_file_sha256` antes de sincronizar. No mostrar tokens ni rutas privadas fuera del equipo.

## Reprocesar un `sent` v1, cuando haga falta

`reprocess-sent-v2` exige la identidad del comercio y Collector, la fuente v2 configurada, el SHA, el archivo exacto dentro de la carpeta configurada y el ID del summary v1. Rechaza archivos fallidos, distintos, con cola v1 pendiente o con un intento v2 ya registrado. Crea una fila nueva v2 y eventos de auditoría; conserva la fila v1, su summary Backend y su cola. El reintento de un fallo temporal usa `retry-pending`, nunca un segundo reproceso.

```powershell
aiva-collector-cli.exe reprocess-sent-v2 --config "$env:ProgramData\AIVA\Collector\config.windows.json" --file "C:\AIVA-Piloto-Sintetico\archivo-exacto.xlsx" --expected-sha256 "SHA256_VERIFICADO" --expected-commerce-id "commerce_a0e93d3ec7ac" --expected-collector-id "collector_dc15555b7052" --expected-source-id "aiva_demo_synthetic_20260929_complete" --expected-v1-summary-id "SUMMARY_V1_VERIFICADO"
```

Para el piloto nuevo del 29/09/2026 esta operación no es necesaria porque el libro tiene un SHA nuevo. El Excel anterior de 105 filas y el RC4 de 44 filas no se mezclan con esa fuente.

## Ventana controlada y reversión

Antes de instalar RC7 o tocar el Windows del comercio: detener temporalmente la tarea `AIVA Collector Auto` tras verificar que no hay ejecución activa; respaldar configuración, SQLite local mediante la API `sqlite3.Connection.backup`, carpeta de cola y último summary en una ubicación protegida; registrar SHA-256 e `integrity_check=ok` del backup; confirmar que se puede abrir una copia restaurada. No copiar el token DPAPI fuera del equipo. Registrar conteos de archivos y cola.

Tras instalación autorizada, comprobar self-check de Desktop/CLI/Background, versión RC7, activación conservada, mapping y tarea programada. Configurar únicamente la carpeta sintética dedicada, sincronizar ese archivo una vez, consultar estado y cola, y verificar en Backend esquema/digest/identidad/snapshots/cobertura/métricas. Un segundo intento debe ser idempotente. El preview debe ejecutarse con `generate_report_for_admin(..., CommerceReportGenerateRequest(report_type="weekly", mode="preview", send_telegram=False), deterministic_only=True)` en Backend; verificar `commerce_reports` y deliveries sin cambios. La ruta HTTP de preview no expone `deterministic_only`, por lo que no sustituye esta comprobación.

Si falla antes del envío, restaurar configuración y estado local desde los backups verificados y reinstalar RC6 conservando ProgramData. Si el v2 ya fue aceptado, no borrar ni alterar las filas Backend: detener el piloto, conservar la auditoría y diagnosticar con los IDs exactos. RC6 no puede abrir un estado RC7 que ya contiene dos filas del mismo SHA en esquemas distintos; conservar el backup RC7 y no reinstalar RC6 sobre esa base migrada. Reactivar la tarea sólo después de validar el estado local. No habilitar Telegram, WhatsApp, pairing/QR ni automatizaciones durante el piloto.
