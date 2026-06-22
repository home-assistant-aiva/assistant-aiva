@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" status --config "%AIVA_ROOT%\config.local.json"
if errorlevel 1 (
  echo Revisar backend_url, commerce_id, collector_id y AIVA_COLLECTOR_TOKEN.
)
pause
