@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" discover --dry-run
echo Discovery finalizado. No se envio nada al backend.
pause
