@echo off
setlocal
title National Border Targeting Centre Brief
cd /d "%~dp0"
where py >nul 2>nul || goto :no_python

py -3 -c "import fastapi, uvicorn, authlib, alembic, sqlalchemy" >nul 2>nul
if errorlevel 1 (
  echo Installing required Python packages. This may take a few minutes the first time...
  py -3 -m pip install -r requirements.txt
  if errorlevel 1 goto :install_failed
)

set BMA_BRIEFING_PUBLIC_URL=http://localhost:8770
set BMA_BRIEFING_DEVELOPMENT_AUTH=true
set BMA_BRIEFING_DEVELOPMENT_EMAIL=christo.bezuidenhout@bma.gov.za
set BMA_BRIEFING_BIND_HOST=127.0.0.1
set BMA_BRIEFING_PORT=8770

start "NBTC Brief" http://localhost:8770/login
py -3 server.py
goto :done

:no_python
echo.
echo Python 3 was not found. Install Python 3.12 or later and run this file again.
echo.
goto :done

:install_failed
echo.
echo The required Python packages could not be installed.
echo Check the internet connection and run this file again.
echo.

:done
pause
