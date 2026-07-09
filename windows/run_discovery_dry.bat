@echo off
setlocal

python -m aiva_collector.cli discover --dry-run
echo Discovery finalizado. No se envio nada al backend.
pause
