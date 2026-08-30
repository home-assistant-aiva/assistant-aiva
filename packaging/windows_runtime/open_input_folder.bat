@echo off
setlocal

set "AIVA_INPUT=%ProgramData%\AIVA\Collector\entrada"
if not exist "%AIVA_INPUT%" mkdir "%AIVA_INPUT%" 2>nul
start "" "%AIVA_INPUT%"
