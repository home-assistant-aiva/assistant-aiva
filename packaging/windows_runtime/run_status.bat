@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" status
if errorlevel 1 (
  echo Revisar activacion y configuracion instalada.
)
pause
