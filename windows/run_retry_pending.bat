@echo off
setlocal

python -m aiva_collector.cli retry-pending --config C:\AIVA_Comercio\config.local.json
pause
