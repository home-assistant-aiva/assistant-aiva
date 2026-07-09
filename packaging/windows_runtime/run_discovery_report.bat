@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"

if "%AIVA_COLLECTOR_TOKEN%"=="" (
  echo Falta AIVA_COLLECTOR_TOKEN. No se envio nada.
  pause
  exit /b 2
)

echo AIVA detectara posibles fuentes. No modificara archivos ni bases.
echo Escribi DETECTAR para enviar metadata segura al backend.
set /p CONFIRM="Confirmacion: "
if /I not "%CONFIRM%"=="DETECTAR" (
  echo Cancelado. No se envio nada.
  pause
  exit /b 1
)

"%AIVA_EXE%" discover --report --config "%AIVA_ROOT%\config.local.json"
pause
