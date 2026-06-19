@echo off
setlocal

python -m aiva_collector.cli run-once --config C:\AIVA_Comercio\config.local.json
echo Dry-run finalizado. No se envio nada al backend.
echo Revisar C:\AIVA_Comercio\output\last_summary.json
pause
