@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

if "%AIVA_COLLECTOR_TOKEN%"=="" (
  echo Falta AIVA_COLLECTOR_TOKEN. No se envio nada.
  pause
  exit /b 1
)

echo Esto enviara el resumen al backend AIVA. Escribi ENVIAR para continuar.
set /p CONFIRM=Confirmacion:
if /I not "%CONFIRM%"=="ENVIAR" (
  echo Cancelado. No se envio nada.
  pause
  exit /b 1
)

"%AIVA_EXE%" send --config "%AIVA_ROOT%\config.local.json"
pause
