@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" run-once --config "%AIVA_ROOT%\config.local.json"
echo Dry-run finalizado. No se envio nada al backend.
echo Revisar %AIVA_ROOT%\output\last_summary.json
pause
