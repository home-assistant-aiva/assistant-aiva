@echo off
setlocal

set "TASK_NAME=AIVA Collector Auto"

schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
  echo No se encontro o no se pudo quitar la tarea automatica.
  pause
  exit /b 1
)

echo Tarea automatica quitada: %TASK_NAME%
pause
