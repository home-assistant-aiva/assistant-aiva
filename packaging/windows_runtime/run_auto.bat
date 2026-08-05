@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" run-auto
set "AIVA_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%AIVA_EXIT_CODE%"=="0" echo El procesamiento termino con errores. Revisa el mensaje anterior y los logs.
pause
exit /b %AIVA_EXIT_CODE%
