@echo off
setlocal

python -m aiva_collector.cli status --config C:\AIVA_Comercio\config.local.json
if errorlevel 1 (
  echo Revisar backend_url, commerce_id, collector_id y AIVA_COLLECTOR_TOKEN.
)
pause
