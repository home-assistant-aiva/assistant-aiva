@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" retry-pending --config "%AIVA_ROOT%\config.local.json"
pause
