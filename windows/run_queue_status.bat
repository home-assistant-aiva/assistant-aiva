@echo off
setlocal

python -m aiva_collector.cli queue-status --config C:\AIVA_Comercio\config.local.json
pause
