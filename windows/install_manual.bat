@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "SCRIPT_DIR=%~dp0"

mkdir "%AIVA_ROOT%\entrada" 2>nul
mkdir "%AIVA_ROOT%\procesados" 2>nul
mkdir "%AIVA_ROOT%\error" 2>nul
mkdir "%AIVA_ROOT%\output" 2>nul
mkdir "%AIVA_ROOT%\logs" 2>nul
mkdir "%AIVA_ROOT%\state" 2>nul
mkdir "%AIVA_ROOT%\collector" 2>nul

if not exist "%AIVA_ROOT%\config.local.json" (
  copy "%SCRIPT_DIR%config.windows.example.json" "%AIVA_ROOT%\config.local.json" >nul
  echo Config creada en %AIVA_ROOT%\config.local.json
) else (
  echo Config existente detectada. No se pisa %AIVA_ROOT%\config.local.json
)

echo Instalacion manual preparada. No se instalo servicio y no se guardo token.
pause
