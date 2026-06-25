# AIVA Collector Offline Queue

FASE 6.0 evita perdida de datos cuando la PC del comercio no tiene internet o AIVA Comercial no responde.

## Que pasa si no hay internet

Si el archivo es valido pero no se puede enviar, el Collector:

- guarda el summary normalizado en `C:\AIVA_Comercio\state\queue`;
- registra el item en SQLite `upload_queue`;
- marca el archivo en `processed_files` como `pending_send`;
- conserva el mismo `idempotency_key`;
- deja el archivo original en `entrada`;
- no marca el archivo como error de negocio;
- muestra que quedo pendiente y se reintentara automaticamente.

## Que se guarda

Se guarda solo el payload que ya se iba a enviar al backend:

- `source_file.file_id`
- `source_file.file_name`
- `file_sha256`
- `normalized_data_hash`
- `rows_total`
- `rows_valid`
- `rows_invalid`
- warnings de validacion
- `idempotency_key` en SQLite

No se guarda token, no se guarda Excel completo y no se guardan filas crudas fuera del summary normalizado.

## Estados

- `pending`: listo para enviar.
- `processing`: reintento en curso.
- `retrying`: fallo temporal y tiene `next_retry_at`.
- `sent`: backend confirmo OK.
- `duplicate`: backend confirmo duplicado/idempotente.
- `error`: payload corrupto, error definitivo o maximo de reintentos superado.

## Reintentos

Backoff:

- retry 0: 5 minutos
- retry 1: 15 minutos
- retry 2: 30 minutos
- retry 3: 60 minutos
- despues: 6 horas

El maximo default es 10 y se puede ajustar con `offline_queue_max_retry_count`.

## Comandos

```bat
aiva-collector.exe queue-status --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe retry-pending --config C:\AIVA_Comercio\config.local.json
```

`queue-status` muestra pendientes, reintentando, enviados, duplicados, errores, proximo reintento, ultima falla y DB local.

`retry-pending` intenta enviar ahora los pendientes. No imprime token.

## Movimiento de archivos

Mientras el backend no confirma, el archivo queda en `entrada` y no se reparsea porque `processed_files.status` queda en `pending_send`. Cuando la cola se envia OK, el Collector mueve el archivo a `procesados` si todavia existe. Si el archivo original no existe, marca la cola como enviada y registra el warning: `archivo original no encontrado, payload ya fue enviado`.

## Limpieza

Existen funciones internas testeadas:

- `cleanup_sent_queue(days=30)`
- `cleanup_old_events(days=90)`

No se ejecutan automaticamente en FASE 6.0.

## Diagnostico

Revisar:

- `C:\AIVA_Comercio\state\aiva_collector.db`
- `C:\AIVA_Comercio\state\queue`
- `C:\AIVA_Comercio\logs\aiva_collector.log`
- salida de `queue-status`

No borrar `state\aiva_collector.db` salvo que se quiera perder deduplicacion local y memoria de pendientes.
