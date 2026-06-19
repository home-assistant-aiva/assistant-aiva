@echo off
setlocal

set "AIVA_COLLECTOR_DIR=C:\AIVA_Comercio\collector"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python no esta instalado o no esta en PATH.
  echo Instala Python 3.11 o superior desde python.org y marca Add Python to PATH.
  pause
  exit /b 1
)

if not exist "%AIVA_COLLECTOR_DIR%\pyproject.toml" (
  echo No se encontro %AIVA_COLLECTOR_DIR%\pyproject.toml
  echo Descomprimir el ZIP en C:\AIVA_Comercio\collector y reintentar.
  pause
  exit /b 1
)

echo Esto requiere internet para descargar dependencias Python.
python -m pip install -U pip
if errorlevel 1 (
  echo Fallo la actualizacion de pip.
  pause
  exit /b 1
)

python -m pip install -e "%AIVA_COLLECTOR_DIR%"
if errorlevel 1 (
  echo Fallo la instalacion de dependencias del collector.
  pause
  exit /b 1
)

echo Dependencias instaladas. No se ejecuto envio y no se guardo token.
pause
