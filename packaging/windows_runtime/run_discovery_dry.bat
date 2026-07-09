@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" discover --dry-run --config "%AIVA_ROOT%\config.local.json"
echo Discovery finalizado. No se envio nada al backend.
pause
