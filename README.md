# AIVA Collector v1

AIVA Collector lee exportaciones CSV/Excel de una carpeta local del comercio, normaliza columnas, valida datos, calcula un resumen por producto y opcionalmente envia solo ese summary al backend de AIVA Comercial.

No envia tickets completos, no envia archivos Excel, no envia datos crudos, no modifica stock, ventas ni facturacion, no automatiza clicks y no escribe en sistemas del cliente. El estado local guarda metadata, conteos y hashes en SQLite; no guarda tokens ni filas crudas.

## Instalación

```bash
cd /opt/aiva-collector
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
```

## Configuración

```bash
python -m aiva_collector.cli init-config --output config.local.json
```

El token no va en el JSON. Se carga por variable de entorno:

```bash
export AIVA_COLLECTOR_TOKEN
```

Para dry-run el token puede estar ausente.

## Uso manual en Windows

FASE 4.4 incluye un paquete manual para pruebas en Windows, sin instalador exe y sin servicio:

- `windows/config.windows.example.json`
- `windows/run_validate.bat`
- `windows/run_dry.bat`
- `windows/run_discovery_dry.bat`
- `windows/run_discovery_report.bat`
- `windows/run_send.bat`
- `windows/run_status.bat`
- `windows/run_queue_status.bat`
- `windows/run_retry_pending.bat`
- `windows/install_manual.bat`
- `windows/install_dependencies.bat`
- `windows/check_python.bat`
- `windows/set_token_example.bat`
- `windows/collect_diagnostics.bat`

Uso esperado:

```text
C:\AIVA_Comercio
  collector
  entrada
  procesados
  procesados\duplicados
  errores
  output
  logs
  state
  config.local.json
```

El token no va en `config.local.json`. Para una prueba manual en Windows se configura temporalmente:

```bat
set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_AQUI
```

`run_send.bat` exige token y confirmación escrita `ENVIAR` antes de usar `--send`. Ver [windows/README_WINDOWS.md](windows/README_WINDOWS.md) y [docs/aiva_collector_windows_manual.md](docs/aiva_collector_windows_manual.md).

`run_discovery_dry.bat` detecta posibles fuentes sin enviar nada. `run_discovery_report.bat` reporta metadata segura al backend solo con confirmacion `DETECTAR`.

## Paquete ZIP manual para Windows

FASE 4.5 genera un ZIP limpio para copiar a una PC Windows:

```bash
bash scripts/build_windows_package.sh
```

El resultado queda en `dist/aiva-collector-windows-manual-v0.1.0.zip` junto con su manifest JSON y SHA256. El paquete no incluye `.venv`, tests, caches, logs reales, state real, output real, `.env`, `config.local.json` ni tokens. Ver [docs/aiva_collector_windows_package.md](docs/aiva_collector_windows_package.md).

FASE 4.6 valida una instalacion limpia desde ese ZIP en `/tmp`, sin depender del checkout de desarrollo:

```bash
bash scripts/test_clean_windows_package_install.sh
```

La prueba crea una venv temporal, instala desde la carpeta descomprimida, ejecuta `validate` y `run-once` sin `--send`, y confirma aislamiento runtime. Ver [docs/aiva_collector_clean_install_test.md](docs/aiva_collector_clean_install_test.md).

FASE 4.7 agrega el kit piloto Windows: checklist de prueba, plantilla de resultados, pedido de datos al primer cliente y diagnóstico seguro para soporte. Ver [docs/aiva_collector_windows_pilot_checklist.md](docs/aiva_collector_windows_pilot_checklist.md), [docs/aiva_collector_windows_pilot_results_template.md](docs/aiva_collector_windows_pilot_results_template.md), [docs/aiva_collector_first_client_data_request.md](docs/aiva_collector_first_client_data_request.md) y [windows/README_SUPPORT.md](windows/README_SUPPORT.md).

## Comandos principales

```bash
python -m aiva_collector.cli validate --config config.local.json
python -m aiva_collector.cli run-once --config config.local.json
python -m aiva_collector.cli run-auto --config config.local.json
python -m aiva_collector.cli status --config config.local.json
python -m aiva_collector.cli queue-status --config config.local.json
python -m aiva_collector.cli retry-pending --config config.local.json
```

`run-once` sin `--send` es la prueba sin enviar: muestra mapping, validacion, duplicado local y si se enviaria. No mueve archivos, no envia y no marca `sent` en SQLite.

`run-auto` es "Procesar ahora": procesa cola pendiente, espera archivos estables, deduplica por hash, valida, envia summary si corresponde, registra `state/aiva_collector.db` y mueve archivos a `procesados`, `procesados/duplicados` o `errores`.

En Windows RC4, el instalador `AIVA-Collector-Setup-v0.2.6-interactive-rc4.exe` instala dos ejecutables. `aiva-collector.exe` abre un menu interactivo cuando se ejecuta sin argumentos; `aiva-collector-background.exe` queda reservado para la tarea automatica silenciosa. La tarea programada usa exclusivamente `aiva-collector-background.exe run-auto --config "%ProgramData%\AIVA\Collector\config.local.json"`, conserva ProgramData y no pasa tokens por argumentos.

`queue-status` muestra pendientes, reintentando, enviados, errores, proximo reintento y DB local. `retry-pending` intenta enviar ahora los pendientes sin imprimir token.

El summary generado queda en `samples/output/last_summary.json` o en el `output_dir` configurado.

## Enviar al backend

Sólo se envía si se pasa explícitamente `--send` y existe el token:

```bash
python -m aiva_collector.cli run-once --config config.local.json --send
```

Antes del envío se reporta status `running`; luego `ok` o `error`. El token no se imprime.

## Robustez local

FASE 6.0 agrega:

- `processed_files` y `processed_file_events` en SQLite local.
- `file_sha256` para detectar cambios fisicos.
- `normalized_data_hash` para detectar cambios reales de datos.
- idempotency key estable por comercio, collector y contenido normalizado.
- validaciones bloqueantes y advertencias antes del envio.
- `upload_queue` real con payload JSON en `state/queue`, backoff y reintento automatico.

Ver [docs/aiva_collector_reliability.md](docs/aiva_collector_reliability.md) y [docs/aiva_collector_offline_queue.md](docs/aiva_collector_offline_queue.md).

## Integración backend demo

La prueba controlada crea o reutiliza un comercio demo, lo activa, crea un collector demo, ejecuta el collector contra el backend local y verifica recomendaciones, reporte y auditoría. Usa sólo `samples/input`, no mueve archivos procesados, no envía Telegram y no guarda ni imprime tokens.

Requisitos:

- Backend AIVA Comercial activo en `http://127.0.0.1:8080`.
- `AIVA_INTERNAL_SECRET` disponible en el entorno o en `/opt/aiva-backend/.env`.
- Endpoints audit de FASE 4.3A desplegados para las verificaciones post-integración.

Integración normal:

```bash
bash scripts/run_backend_integration_demo.sh
```

Reutilizar el último demo activo o reactivarlo:

```bash
bash scripts/run_backend_integration_demo.sh --reuse-latest-demo
```

Prueba idempotente explícita:

```bash
bash scripts/run_backend_integration_demo.sh --reuse-latest-demo --test-idempotency
```

El primer envío debe quedar `sent` o, si el mismo summary ya existía de una corrida anterior, `duplicate_summary`. El segundo envío con el mismo summary y la misma idempotency key debe devolver `duplicate_summary` sin incrementar `summaries_count`.

Crear un demo nuevo aunque exista uno reutilizable:

```bash
bash scripts/run_backend_integration_demo.sh --force-new-demo
```

El flag histórico `--deactivate-old-demos` ya no ejecuta limpieza desde la integración. Si se usa, sólo imprime el comando seguro de cleanup y termina sin crear comercio, collector, summary ni reporte.

El script:

- valida `GET /health`;
- crea o reutiliza `Demo Integracion Collector AIVA`;
- crea `Collector Demo Integracion`; si existe uno previo, no reutiliza su token porque el backend no lo expone de nuevo;
- genera una config temporal en `/tmp` sin `collector_token`;
- pasa `AIVA_COLLECTOR_TOKEN` sólo al subproceso de `run-once --send`;
- confirma `duplicate_summary` en modo `--test-idempotency`;
- consulta audit post-integración;
- imprime `commerce_id`, `collector_id`, `recommendations_count` y `report_id`, pero no secretos.

Endpoints audit usados:

- `GET /admin/commerce/businesses/{commerce_id}/ingestion-summaries`
- `GET /admin/commerce/businesses/{commerce_id}/audit`

Estado local:

`state/collector_state.json` guarda estado operativo como `last_backend_send_at`, `last_backend_status_code`, `last_backend_summary_status`, `last_backend_report_id`, `last_backend_commerce_id`, `last_backend_collector_id`, `last_idempotency_key_hash` e `idempotency_confirmed`. No guarda `collector_token`, `token_hash`, `Authorization` ni `AIVA_INTERNAL_SECRET`.

## Limpieza segura de demos

La limpieza operativa de demos está separada de la integración. Lista comercios desde `GET /admin/commerce/businesses` y sólo considera demos cuyo `display_name` empieza exactamente con `Demo Integracion Collector AIVA`.

Dry-run, modo por defecto:

```bash
bash scripts/cleanup_demo_businesses.sh --dry-run
```

Aplicar desactivación, si el dry-run es correcto:

```bash
bash scripts/cleanup_demo_businesses.sh --confirm --keep-latest 1
```

Opciones útiles:

- `--keep-latest N`: mantiene los últimos N demos según `created_at` o `updated_at`; por defecto mantiene 1.
- `--keep-commerce-id <commerce_id>`: mantiene siempre ese comercio; se puede repetir.
- `--max-to-deactivate N`: limita cuántos demos activos puede desactivar en una corrida; por defecto 20.
- `--include-inactive`: muestra demos ya inactivos en el listado, sin volver a desactivarlos.
- `--json`: imprime salida estructurada sin secretos.
- `--base-url`: override de backend; por defecto usa `BASE_URL`, `AIVA_BACKEND_URL` o `http://127.0.0.1:8080`.

Reglas de seguridad:

- Sin `--confirm` nunca modifica nada.
- Con `--confirm` sólo llama `POST /admin/commerce/businesses/{commerce_id}/deactivate` sobre candidatos demo activos.
- Nunca borra datos, collectors, summaries, reports ni recommendations.
- No ejecuta Collector, no usa `run-once`, no envía summaries, no genera reportes y no envía Telegram.
- No toca comercios reales ni nombres parecidos que no cumplan el prefijo exacto.
- Lee `AIVA_INTERNAL_SECRET` desde el entorno o `/opt/aiva-backend/.env`, pero no lo imprime.

## CSV esperado

Columnas demo:

- `fecha`
- `producto_codigo`
- `producto_nombre`
- `categoria`
- `cantidad_vendida`
- `precio_venta`
- `costo_unitario`
- `stock_actual`

`producto_nombre`, `cantidad_vendida` y `precio_venta` son mínimos. `producto_codigo` puede estar vacío. Si falta categoría se usa `Sin categoria`; costo y stock pueden ser nulos.

## Adaptar columnas

Editar `column_mapping` en `config.local.json`. La clave izquierda es el campo canónico de AIVA y el valor derecho es el nombre de columna en el CSV/XLSX.

## Errores comunes

- `Falta token`: sólo aplica al usar `--send` o `status`.
- `Faltan columnas requeridas`: revisar `column_mapping` y encabezados del archivo.
- `openpyxl no está disponible`: instalar dependencias con `pip install -e ".[dev]"`.
- `duplicate_summary`: el backend ya recibió un summary equivalente para ese período.

## Próximos pasos

- Mapeo asistido.
- Servicio Windows.
- Empaquetado exe.
- HMAC.
- Scheduler.

## AIVA Collector Discovery

El Collector incluye `discover` para detectar posibles fuentes de datos sin leer contenido comercial completo ni modificar archivos:

```bash
python -m aiva_collector.cli discover --config config.local.json --dry-run
```

Para reportar detecciones al backend de Fuentes de datos:

```bash
python -m aiva_collector.cli discover --config config.local.json --report
```

Ver `docs/collector_discovery.md`.
