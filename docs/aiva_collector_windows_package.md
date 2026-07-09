# Paquete ZIP manual de AIVA Collector para Windows

## Que contiene

El archivo `aiva-collector-windows-manual-v0.1.0.zip` contiene el codigo del collector, los BATs de uso manual, configuraciones de ejemplo, muestras de entrada y carpetas vacias necesarias para una prueba local.

Incluye:

- `aiva_collector\`
- `windows\`
- `docs\aiva_collector_windows_manual.md`
- `docs\aiva_collector_windows_package.md`
- `docs\aiva_collector_windows_pilot_checklist.md`
- `docs\aiva_collector_windows_pilot_results_template.md`
- `docs\aiva_collector_first_client_data_request.md`
- `windows\README_SUPPORT.md`
- `windows\collect_diagnostics.bat`
- `windows\run_queue_status.bat`
- `windows\run_retry_pending.bat`
- `windows\run_discovery_dry.bat`
- `windows\run_discovery_report.bat`
- `README.md`
- `pyproject.toml`
- `configs\example_config.json`
- `samples\input\ventas_demo.csv`
- `samples\input\ventas_demo.xlsx` si existe en el build
- `samples\output\.gitkeep`
- `samples\processed\.gitkeep`
- `samples\error\.gitkeep`
- `logs\.gitkeep`
- `state\.gitkeep`

No incluye `.venv`, tests, caches, `.env`, `config.local.json`, logs reales, state real, output real, archivos procesados ni tokens.

## Descompresion recomendada

1. Crear la carpeta `C:\AIVA_Comercio\collector`.
2. Descomprimir el contenido del ZIP dentro de `C:\AIVA_Comercio\collector`.
3. Verificar que exista `C:\AIVA_Comercio\collector\pyproject.toml`.

## Primer uso

Ejecutar estos BATs desde `C:\AIVA_Comercio\collector\windows`:

1. `check_python.bat`
2. `install_manual.bat`
3. `install_dependencies.bat`
4. `run_validate.bat`
5. `run_dry.bat`
6. `run_status.bat` si se quiere consultar estado del collector
7. `run_queue_status.bat` para ver pendientes offline
8. `run_retry_pending.bat` para reintentar pendientes
9. `run_discovery_dry.bat` para detectar posibles fuentes sin enviar nada
10. `run_discovery_report.bat` para reportar metadata segura de fuentes detectadas
11. `set_token_example.bat` para ver como configurar el token temporalmente
12. `run_send.bat` solo cuando el token este configurado y se quiera enviar
13. `collect_diagnostics.bat` solo si hace falta soporte

`run_send.bat` exige que exista `AIVA_COLLECTOR_TOKEN` y pide escribir `ENVIAR` antes de ejecutar el envio.
`run_discovery_report.bat` exige token y confirmacion `DETECTAR`. No sube archivos ni lee contenido comercial completo.
`run_retry_pending.bat` no imprime el token y usa la cola offline.

## Kit piloto

El ZIP incluye documentos para ordenar la primera prueba manual:

- `docs\aiva_collector_windows_pilot_checklist.md`
- `docs\aiva_collector_windows_pilot_results_template.md`
- `docs\aiva_collector_first_client_data_request.md`
- `windows\README_SUPPORT.md`

`collect_diagnostics.bat` prepara una carpeta local de diagnostico en `C:\AIVA_Comercio\diagnostico`; no ejecuta envio, no llama backend y no manda nada por internet.

## Archivos a editar

Editar `C:\AIVA_Comercio\config.local.json`, creado por `install_manual.bat` si no existia.

Campos habituales:

- `backend_url`
- `commerce_id`
- `collector_id`
- `column_mapping`
- `delimiter`
- `encoding`

El token no va en `config.local.json`. Para una prueba manual se configura en la misma ventana:

```bat
set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_AQUI
```

## Archivos que no se deben compartir

No compartir:

- Tokens del collector.
- `.env`.
- `config.local.json` si contiene datos internos del cliente.
- `logs\aiva_collector.log` sin revisarlo antes.
- `output\last_summary.json` si contiene datos sensibles.
- Archivos CSV/XLSX reales del comercio salvo que el cliente lo autorice.

Para soporte pedir:

- Captura del error.
- Nombre del BAT ejecutado.
- Version de Python mostrada por `check_python.bat`.
- `config.local.json` sin secretos.
- Log revisado y sin secretos, si hace falta.
- Nombre y columnas del archivo de entrada.

## Verificar dry-run

`run_dry.bat` ejecuta el collector sin `--send`. Al terminar debe mostrar que no se envio nada al backend y generar:

```text
C:\AIVA_Comercio\output\last_summary.json
```

Si ese archivo se genera y no se ejecuto `run_send.bat`, la prueba fue local.

Para abrir el summary:

```bat
Get-Content C:\AIVA_Comercio\output\last_summary.json -Raw
C:\Windows\System32\notepad.exe C:\AIVA_Comercio\output\last_summary.json
```

## Validacion de instalacion limpia

Antes de copiar el ZIP a una PC Windows se puede validar en Linux que el paquete no depende del checkout de desarrollo:

```bash
bash scripts/test_clean_windows_package_install.sh --zip dist/aiva-collector-windows-manual-v0.1.0.zip
```

La prueba descomprime el ZIP en `/tmp`, crea una venv temporal, instala el collector desde esa carpeta y ejecuta `validate` + `run-once` sin envio.

## Primera prueba con CSV real

1. Copiar un CSV real a `C:\AIVA_Comercio\entrada`.
2. Ajustar `column_mapping` en `C:\AIVA_Comercio\config.local.json`.
3. Ejecutar `run_validate.bat`.
4. Ejecutar `run_dry.bat`.
5. Revisar `C:\AIVA_Comercio\output\last_summary.json`.
6. Configurar `AIVA_COLLECTOR_TOKEN` solo si se va a enviar.
7. Ejecutar `run_send.bat` y confirmar `ENVIAR` solo si el summary esta correcto.
