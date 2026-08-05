@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_PYTHON=%AIVA_ROOT%\.venv\Scripts\python.exe"

"%AIVA_PYTHON%" -m aiva_collector.cli configure-source --config "%AIVA_ROOT%\config.local.json"
pause
