@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" configure-source
set "AIVA_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%AIVA_EXIT_CODE%"=="0" echo No se pudo configurar la fuente. Revisa el mensaje anterior.
pause
exit /b %AIVA_EXIT_CODE%
