@echo off
setlocal

set "AIVA_ROOT=C:\AIVA_Comercio"
set "DIAG_DIR=%AIVA_ROOT%\diagnostico"
set "ZIP_PATH=%DIAG_DIR%\aiva_collector_diagnostico.zip"

mkdir "%DIAG_DIR%" 2>nul

if exist "%AIVA_ROOT%\logs\aiva_collector.log" (
  copy "%AIVA_ROOT%\logs\aiva_collector.log" "%DIAG_DIR%\aiva_collector.log" >nul
) else (
  echo No existe log del collector en %AIVA_ROOT%\logs\aiva_collector.log
)

if exist "%AIVA_ROOT%\output\last_summary.json" (
  copy "%AIVA_ROOT%\output\last_summary.json" "%DIAG_DIR%\last_summary.json" >nul
) else (
  echo No existe last_summary.json en %AIVA_ROOT%\output
)

if exist "%AIVA_ROOT%\config.local.json" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='%AIVA_ROOT%\config.local.json'; $o='%DIAG_DIR%\config.sanitized.json';" ^
    "$j=Get-Content -Raw -LiteralPath $p | ConvertFrom-Json;" ^
    "$j.PSObject.Properties.Remove('collector_token');" ^
    "if ($j.PSObject.Properties.Name -contains 'commerce_id') { $j.commerce_id='MASKED_COMMERCE_ID' };" ^
    "if ($j.PSObject.Properties.Name -contains 'collector_id') { $j.collector_id='MASKED_COLLECTOR_ID' };" ^
    "$j | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 -LiteralPath $o"
) else (
  echo No existe config.local.json en %AIVA_ROOT%
)

(
  echo AIVA Collector diagnostico
  echo Fecha y hora:
  powershell -NoProfile -Command "Get-Date -Format o"
  echo.
  echo Python:
  python --version 2^>^&1
  echo.
  echo Carpeta actual:
  cd
  echo.
  echo Archivos de entrada:
  dir /b "%AIVA_ROOT%\entrada" 2^>nul
  echo.
  echo Nota: revisar config.sanitized.json y last_summary.json antes de compartir.
) > "%DIAG_DIR%\info_sistema.txt"

if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Get-Command Compress-Archive -ErrorAction SilentlyContinue) { Compress-Archive -LiteralPath '%DIAG_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force }"

echo Diagnostico generado en %DIAG_DIR%
if exist "%ZIP_PATH%" echo ZIP generado: %ZIP_PATH%
echo Revisar los archivos antes de compartir. No mandar tokens ni contrasenas.
echo Este script no envia nada por internet y no ejecuta envio al backend.
pause
