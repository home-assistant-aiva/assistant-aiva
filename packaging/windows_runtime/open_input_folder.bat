@echo off
setlocal

set "AIVA_INPUT=C:\AIVA_Comercio\entrada"
if not exist "%AIVA_INPUT%" mkdir "%AIVA_INPUT%" 2>nul
start "" "%AIVA_INPUT%"
