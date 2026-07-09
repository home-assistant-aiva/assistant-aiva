@echo off
setlocal

python -m aiva_collector.cli status
if errorlevel 1 (
  echo Revisar activacion y configuracion instalada.
)
pause
