# AIVA Collector Reliability

FASE 6.0 agrega una cola offline real sobre el registro local por archivo para que el Collector no pierda summaries si no hay internet o el backend esta caido.

## SQLite local

La base local se crea en `C:\AIVA_Comercio\state\aiva_collector.db` en Windows. En tests o desarrollo usa el `state_dir` configurado.

Tablas:

- `processed_files`: metadata del archivo, hashes, estado, conteos, idempotency key, respuesta saneada del backend y error resumido.
- `processed_file_events`: eventos operativos por archivo.
- `upload_queue`: cola de envio offline con payload JSON normalizado, idempotency key, backoff, retry count y ultimo error.

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

Si el envio sale OK, el archivo se mueve a `procesados` con timestamp. Si hay error bloqueante, se mueve a `errores` con un `.error.txt` al lado. Si el backend no responde, el archivo no se mueve, queda en `entrada`, se salta por estado `pending_send` y se reintenta desde `state\queue`.

Config:

- `move_processed_files`: `true` por defecto en Windows.
- `move_error_files`: `true` por defecto.
- `keep_original_files`: `false` por defecto.

## Offline queue FASE 6.0

`run-auto` procesa cola pendiente al inicio, procesa archivos nuevos y vuelve a intentar pendientes al final. El payload se guarda en `C:\AIVA_Comercio\state\queue\*.json`; no se guarda token ni Excel completo.

Estados de cola:

- `pending`
- `processing`
- `retrying`
- `sent`
- `duplicate`
- `error`

Backoff:

- retry 0: 5 minutos
- retry 1: 15 minutos
- retry 2: 30 minutos
- retry 3: 60 minutos
- despues: 6 horas

`offline_queue_max_retry_count` permite cambiar el maximo de reintentos, con default 10.

## Diagnostico

Comandos utiles:

```bat
aiva-collector.exe run-once --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe run-auto --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe status --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe queue-status --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe retry-pending --config C:\AIVA_Comercio\config.local.json
```

`status` muestra la ruta de la DB local, conteos por estado y pendientes de cola. Para limpiar procesados de forma segura, borrar solo archivos antiguos dentro de `procesados` o `procesados\duplicados`; no borrar `state\aiva_collector.db` salvo que se quiera perder la memoria local de deduplicacion.

Ver tambien [aiva_collector_offline_queue.md](aiva_collector_offline_queue.md).
