@echo off
setlocal

python -m aiva_collector.cli discover --dry-run --config C:\AIVA_Comercio\config.local.json
echo Discovery finalizado. No se envio nada al backend.
pause
