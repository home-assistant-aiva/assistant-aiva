# Prueba de instalacion limpia del ZIP Windows

FASE 4.6 valida que el ZIP manual de AIVA Collector puede descomprimirse en una carpeta temporal y funcionar sin depender de `/opt/aiva-collector` ni de archivos de desarrollo.

## Comando

Desde `/opt/aiva-collector`:

```bash
bash scripts/test_clean_windows_package_install.sh
```

Para indicar un ZIP especifico:

```bash
bash scripts/test_clean_windows_package_install.sh --zip dist/aiva-collector-windows-manual-v0.1.0.zip
```

Para conservar la instalacion temporal:

```bash
bash scripts/test_clean_windows_package_install.sh --zip dist/aiva-collector-windows-manual-v0.1.0.zip --keep-temp
```

## Que valida

- Descomprime el ZIP en `/tmp/aiva_collector_clean_install_<timestamp>`.
- Verifica estructura esperada: codigo, BATs, docs, configs, samples, logs, state y carpetas runtime.
- Rechaza `.venv`, tests, caches, `.env`, `config.local.json`, logs reales, state real y output real dentro del ZIP.
- Crea `.venv_clean_test` dentro de la instalacion temporal.
- Instala el paquete con `python -m pip install -e .` desde la carpeta descomprimida.
- Genera `config.clean-test.local.json` sin token y apuntando a carpetas temporales.
- Ejecuta `validate` y `run-once` sin `--send`.
- Confirma que `samples/output/last_summary.json` se genera dentro de la carpeta temporal.
- Confirma que no aparecen referencias runtime a `/opt/aiva-collector`.
- Escanea archivos runtime por patrones sensibles.

## Resultado esperado

La salida es JSON e incluye:

- `zip_path`
- `zip_sha256`
- `temp_install_dir`
- `validate_status`
- `dry_run_status`
- `products_count`
- `output_summary_path`
- `isolation_ok`
- `secrets_ok`
- `cleaned_temp`

`cleaned_temp` queda en `true` por defecto. Con `--keep-temp`, queda en `false` y se informa la ruta temporal.

## Seguridad

La prueba no ejecuta `run_send.bat`, no usa `--send`, no llama endpoints backend, no requiere token y no guarda `collector_token` en config.
