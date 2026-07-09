@echo off
setlocal

echo AIVA detectara posibles fuentes. No modificara archivos ni bases.
echo Escribi DETECTAR para enviar metadata segura al backend.
set /p CONFIRM="Confirmacion: "
if /I not "%CONFIRM%"=="DETECTAR" (
  echo Cancelado. No se envio nada.
  pause
  exit /b 1
)

python -m aiva_collector.cli discover --report
pause
