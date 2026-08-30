@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector-cli.exe"

"%AIVA_EXE%" discover --dry-run
echo Discovery finalizado. No se envio nada al backend.
pause
