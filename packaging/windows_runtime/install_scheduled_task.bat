@echo off
setlocal

set "TASK_NAME=AIVA Collector Auto"
set "AIVA_ROOT=%ProgramData%\AIVA\Collector"
set "AIVA_EXE=%~dp0aiva-collector-background.exe"
set "AIVA_LOG=%AIVA_ROOT%\logs\scheduled_task.log"
set "TASK_XML=%TEMP%\aiva-collector-task.xml"
set "TASK_LIMIT=PT30M"
set "AIVA_QUIET=0"

if /I "%~1"=="/quiet" set "AIVA_QUIET=1"

if not exist "%AIVA_ROOT%\logs" mkdir "%AIVA_ROOT%\logs" 2>nul

if not exist "%AIVA_EXE%" (
  echo No se encontro el runner silencioso: "%AIVA_EXE%"
  if "%AIVA_QUIET%"=="0" pause
  exit /b 1
)

for %%T in ("AIVA Collector" "AIVA Collector Scheduled" "AIVA Collector Auto") do (
  schtasks /Delete /TN %%~T /F >nul 2>nul
)

>"%TASK_XML%" (
  echo ^<?xml version="1.0"?^>
  echo ^<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
  echo   ^<RegistrationInfo^>^<Description^>AIVA Collector automatico silencioso^</Description^>^</RegistrationInfo^>
  echo   ^<Triggers^>
  echo     ^<LogonTrigger^>
  echo       ^<Enabled^>true^</Enabled^>
  echo       ^<Delay^>PT60S^</Delay^>
  echo       ^<Repetition^>^<Interval^>PT15M^</Interval^>^<StopAtDurationEnd^>false^</StopAtDurationEnd^>^</Repetition^>
  echo     ^</LogonTrigger^>
  echo   ^</Triggers^>
  echo   ^<Principals^>
  echo     ^<Principal id="Author"^>
  echo       ^<LogonType^>InteractiveToken^</LogonType^>
  echo       ^<RunLevel^>LeastPrivilege^</RunLevel^>
  echo     ^</Principal^>
  echo   ^</Principals^>
  echo   ^<Settings^>
  echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
  echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
  echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
  echo     ^<AllowHardTerminate^>true^</AllowHardTerminate^>
  echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^>
  echo     ^<RunOnlyIfNetworkAvailable^>false^</RunOnlyIfNetworkAvailable^>
  echo     ^<Hidden^>true^</Hidden^>
  echo     ^<ExecutionTimeLimit^>%TASK_LIMIT%^</ExecutionTimeLimit^>
  echo     ^<RestartOnFailure^>^<Interval^>PT5M^</Interval^>^<Count^>3^</Count^>^</RestartOnFailure^>
  echo   ^</Settings^>
  echo   ^<Actions Context="Author"^>
  echo     ^<Exec^>
  echo       ^<Command^>%AIVA_EXE%^</Command^>
  echo       ^<Arguments^>run-auto --config "%AIVA_ROOT%\config.windows.json"^</Arguments^>
  echo       ^<WorkingDirectory^>%~dp0^</WorkingDirectory^>
  echo     ^</Exec^>
  echo   ^</Actions^>
  echo ^</Task^>
)

schtasks /Create /TN "%TASK_NAME%" /XML "%TASK_XML%" /F
if errorlevel 1 (
  echo No se pudo crear la tarea automatica.
  if "%AIVA_QUIET%"=="0" pause
  exit /b 1
)
del "%TASK_XML%" >nul 2>nul

echo Tarea automatica instalada: %TASK_NAME%
if "%AIVA_QUIET%"=="0" pause
