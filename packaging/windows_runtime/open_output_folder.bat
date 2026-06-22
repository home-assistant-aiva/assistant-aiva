@echo off
setlocal

set "AIVA_OUTPUT=C:\AIVA_Comercio\output"
if not exist "%AIVA_OUTPUT%" mkdir "%AIVA_OUTPUT%" 2>nul
start "" "%AIVA_OUTPUT%"
