@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" run-once
echo Dry-run finalizado. No se envio nada al backend.
echo Revisar C:\AIVA_Comercio\output\last_summary.json
pause
