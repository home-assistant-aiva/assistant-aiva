@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" run-once
echo Dry-run finalizado. No se envio nada al backend.
echo Revisar %ProgramData%\AIVA\Collector\ultimo_summary\last_summary.json
pause
