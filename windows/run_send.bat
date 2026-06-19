@echo off
setlocal

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

python -m aiva_collector.cli run-once --config C:\AIVA_Comercio\config.local.json --send
pause
