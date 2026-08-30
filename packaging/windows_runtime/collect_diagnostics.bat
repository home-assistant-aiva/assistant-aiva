@echo off
setlocal

set "AIVA_ROOT=%ProgramData%\AIVA\Collector"
set "DIAG_DIR=%AIVA_ROOT%\diagnostico"
set "ZIP_PATH=%DIAG_DIR%\aiva_collector_diagnostico.zip"
set "POWERSHELL_EXE="

if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" (
  set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
) else (
  for %%P in (powershell.exe) do (
    if not "%%~$PATH:P"=="" set "POWERSHELL_EXE=%%~$PATH:P"
  )
)

mkdir "%DIAG_DIR%" 2>nul

if exist "%AIVA_ROOT%\logs\aiva_collector.log" (
  copy "%AIVA_ROOT%\logs\aiva_collector.log" "%DIAG_DIR%\aiva_collector.log" >nul
) else (
  echo No existe log del collector en %AIVA_ROOT%\logs\aiva_collector.log
)

if exist "%AIVA_ROOT%\config.windows.json" (
  if defined POWERSHELL_EXE (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='%AIVA_ROOT%\config.windows.json'; $o='%DIAG_DIR%\config.sanitized.json';" ^
    "$j=Get-Content -Raw -LiteralPath $p | ConvertFrom-Json;" ^
    "$j.PSObject.Properties.Remove('collector_token');" ^
    "if ($j.PSObject.Properties.Name -contains 'commerce_id') { $j.commerce_id='MASKED_COMMERCE_ID' };" ^
    "if ($j.PSObject.Properties.Name -contains 'collector_id') { $j.collector_id='MASKED_COLLECTOR_ID' };" ^
    "$j | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 -LiteralPath $o"
  ) else (
    echo PowerShell no disponible. No se copio config.windows.json porque no se pudo sanitizar.
  )
) else (
  echo No existe config.windows.json en %AIVA_ROOT%
)

(
  echo AIVA Collector diagnostico
  echo Fecha y hora:
  if defined POWERSHELL_EXE (
    "%POWERSHELL_EXE%" -NoProfile -Command "Get-Date -Format o"
  ) else (
    echo %DATE% %TIME%
  )
  echo.
  echo Ejecutable instalado:
  if exist "%~dp0aiva-collector-cli.exe" (
    "%~dp0aiva-collector-cli.exe" --help
  ) else (
    echo No se encontro aiva-collector-cli.exe junto a este script.
  )
  echo.
  echo Archivos de entrada:
  dir /b "%AIVA_ROOT%\entrada" 2^>nul
  echo.
  echo Nota: este diagnostico no copia archivos originales del comercio por defecto.
) > "%DIAG_DIR%\info_sistema.txt"

if exist "%ZIP_PATH%" del "%ZIP_PATH%"
if defined POWERSHELL_EXE (
  "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command ^
    "if (Get-Command Compress-Archive -ErrorAction SilentlyContinue) { Compress-Archive -LiteralPath '%DIAG_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force }"
) else (
  echo PowerShell no disponible. Se deja la carpeta de diagnostico sin comprimir.
)

echo Diagnostico generado en %DIAG_DIR%
if exist "%ZIP_PATH%" echo ZIP generado: %ZIP_PATH%
echo Revisar los archivos antes de compartir. No mandar tokens ni contrasenas.
echo Este script no envia nada por internet y no ejecuta envio al backend.
pause
