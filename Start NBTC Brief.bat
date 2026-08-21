@echo off
title National Border Targeting Centre Brief
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 ( py server.py & goto :done )
where python >nul 2>nul
if %errorlevel%==0 ( python server.py & goto :done )
echo.
echo  Python was not found. Install once from https://www.python.org/downloads/
echo  and tick "Add python.exe to PATH", then run this again.
echo.
pause
:done
