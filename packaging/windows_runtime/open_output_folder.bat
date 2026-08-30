@echo off
setlocal

set "AIVA_OUTPUT=%ProgramData%\AIVA\Collector\ultimo_summary"
if not exist "%AIVA_OUTPUT%" mkdir "%AIVA_OUTPUT%" 2>nul
start "" "%AIVA_OUTPUT%"
