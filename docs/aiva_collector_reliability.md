# AIVA Collector Reliability

FASE 5.9 agrega registro local por archivo para que el Collector no envie dos veces el mismo contenido y corte datos invalidos antes de llamar al backend.

## SQLite local

La base local se crea en `C:\AIVA_Comercio\state\aiva_collector.db` en Windows. En tests o desarrollo usa el `state_dir` configurado.

Tablas:

- `processed_files`: metadata del archivo, hashes, estado, conteos, idempotency key, respuesta saneada del backend y error resumido.
- `processed_file_events`: eventos operativos por archivo.
- `upload_queue`: estructura minima para FASE 6.0. En esta fase solo registra pendientes si el backend no responde.

No se guardan archivos completos, filas crudas, tokens ni secretos.

## Hashes

- `file_sha256`: detecta cambios fisicos del archivo.
- `normalized_data_hash`: detecta cambios reales de datos ya normalizados. No incluye timestamps de ejecucion, paths locales ni idempotency keys.
- `file_id`: identificador estable derivado de `file_sha256` y nombre de archivo.

## Deduplicacion

Antes de procesar, `run-auto` calcula `file_sha256` y consulta `processed_files`.

- Si el hash ya fue enviado con estado `sent`, no envia de nuevo y mueve el archivo a `procesados\duplicados` si el movimiento esta habilitado.
- Si el nombre es igual pero el contenido cambio, se procesa como nueva version.
- Si el envio al backend quedo pendiente, se conserva estado `pending_send` y se registra `upload_queue`.

La idempotency key enviada al backend se basa en `commerce_id`, `collector_id` y `normalized_data_hash` cuando existe.

## Validacion

Errores bloqueantes:

- faltan columnas requeridas despues del mapping: `producto_nombre`, `cantidad_vendida`, `precio_venta`;
- archivo sin filas validas;
- todas las filas vacias;
- producto vacio;
- cantidad invalida o negativa;
- precio vacio, invalido o negativo;
- archivo corrupto o no legible.

Advertencias:

- producto sin codigo;
- costo vacio;
- stock vacio;
- stock negativo;
- filas descartadas;
- margen incompleto;
- fecha faltante;
- posibles duplicados dentro del archivo.

Con errores bloqueantes no se envia summary. Con advertencias se puede enviar y las advertencias viajan en `metadata.validation`.

## Carpetas

Windows standard:

- `C:\AIVA_Comercio\entrada`
- `C:\AIVA_Comercio\procesados`
- `C:\AIVA_Comercio\procesados\duplicados`
- `C:\AIVA_Comercio\errores`
- `C:\AIVA_Comercio\state`
- `C:\AIVA_Comercio\output`
- `C:\AIVA_Comercio\logs`

Si el envio sale OK, el archivo se mueve a `procesados` con timestamp. Si hay error bloqueante, se mueve a `errores` con un `.error.txt` al lado. Si el backend no responde, el archivo no se mueve y queda pendiente para reintento futuro.

Config:

- `move_processed_files`: `true` por defecto en Windows.
- `move_error_files`: `true` por defecto.
- `keep_original_files`: `false` por defecto.

## Offline queue FASE 6.0

`upload_queue` queda lista para un retry automatico futuro. FASE 5.9 no implementa daemon ni politica completa de reintentos; solo deja el payload referenciado, hash, idempotency key, estado `pending` y ultimo error.

## Diagnostico

Comandos utiles:

```bat
aiva-collector.exe run-once --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe run-auto --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe status --config C:\AIVA_Comercio\config.local.json
```

`status` muestra la ruta de la DB local, conteos por estado y pendientes de cola. Para limpiar procesados de forma segura, borrar solo archivos antiguos dentro de `procesados` o `procesados\duplicados`; no borrar `state\aiva_collector.db` salvo que se quiera perder la memoria local de deduplicacion.
