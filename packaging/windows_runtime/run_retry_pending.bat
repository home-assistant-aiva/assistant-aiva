@echo off
setlocal

set "AIVA_EXE=%~dp0aiva-collector.exe"

"%AIVA_EXE%" retry-pending
pause
