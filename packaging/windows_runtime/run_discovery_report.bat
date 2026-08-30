@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector-cli.exe"

echo AIVA detectara posibles fuentes. No modificara archivos ni bases.
echo Escribi DETECTAR para enviar metadata segura al backend.
set /p CONFIRM="Confirmacion: "
if /I not "%CONFIRM%"=="DETECTAR" (
  echo Cancelado. No se envio nada.
  pause
  exit /b 1
)

"%AIVA_EXE%" discover --report
pause
