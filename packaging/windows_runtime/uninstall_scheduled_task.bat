@echo off
setlocal

set "TASK_NAME=AIVA Collector Auto"
set "AIVA_QUIET=0"

if /I "%~1"=="/quiet" set "AIVA_QUIET=1"

schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
  schtasks /Query /TN "%TASK_NAME%" >nul 2>nul
  if errorlevel 1 exit /b 0
  echo No se pudo quitar la tarea automatica.
  if "%AIVA_QUIET%"=="0" pause
  exit /b 1
)

echo Tarea automatica quitada: %TASK_NAME%
if "%AIVA_QUIET%"=="0" pause
