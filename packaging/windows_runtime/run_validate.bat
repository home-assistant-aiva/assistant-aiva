@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector-cli.exe"

"%AIVA_EXE%" validate
pause
