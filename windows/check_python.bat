@echo off
setlocal

python --version >nul 2>&1
if errorlevel 1 (
  echo Python no esta instalado o no esta en PATH.
  echo Instala Python 3.11 o superior desde python.org y marca Add Python to PATH.
  pause
  exit /b 1
)

echo Python detectado:
python --version
pause
