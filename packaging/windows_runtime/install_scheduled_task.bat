@echo off
setlocal

set "TASK_NAME=AIVA Collector Auto"
set "AIVA_ROOT=C:\AIVA_Comercio"
set "AIVA_EXE=%~dp0aiva-collector.exe"
set "AIVA_LOG=%AIVA_ROOT%\logs\scheduled_task.log"

if not exist "%AIVA_ROOT%\logs" mkdir "%AIVA_ROOT%\logs" 2>nul

schtasks /Create /TN "%TASK_NAME%" /SC MINUTE /MO 15 /TR "\"%AIVA_EXE%\" run-auto --config \"%AIVA_ROOT%\config.local.json\" >> \"%AIVA_LOG%\" 2>&1" /F
if errorlevel 1 (
  echo No se pudo crear la tarea automatica.
  pause
  exit /b 1
)

echo Tarea automatica instalada: %TASK_NAME%
pause
