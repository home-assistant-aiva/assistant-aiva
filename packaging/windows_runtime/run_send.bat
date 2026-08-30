@echo off
setlocal

set "AIVA_ROOT=%ProgramData%\AIVA\Collector"
set "AIVA_EXE=%~dp0aiva-collector-cli.exe"

echo Esto enviara el resumen al backend AIVA. Escribi ENVIAR para continuar.
set /p CONFIRM=Confirmacion:
if /I not "%CONFIRM%"=="ENVIAR" (
  echo Cancelado. No se envio nada.
  pause
  exit /b 1
)

"%AIVA_EXE%" send --config "%AIVA_ROOT%\config.windows.json"
pause
