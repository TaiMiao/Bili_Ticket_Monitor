@echo off
rem ---------------------------------------------------------------------------
rem  Demo launcher: starts the fake API (mock_sale_server.py) in a minimized
rem  window, then runs the monitor against it in this window.
rem  Timeline: 0-12s baseline | 12s A/B/C go on sale | 22-36s D flaps every
rem  request (should be filtered) | 36s D settles | 46s E sold out | 56s G
rem  added | 66s F removed | 80s one HTTP 500 | 88s one HTTP 429.
rem  Close this window (or Ctrl+C) to stop the demo.
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul
title Ticket Monitor demo
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0.."

start "mock-server" /min python -X utf8 "%~dp0mock_sale_server.py"
timeout /t 2 /nobreak >nul

python "%~dp0..\aili_ticket_monitor.py" ^
  --api-url "http://127.0.0.1:5001/api/ticket/project/getV2?version=134&id=900001" ^
  --interval 2 --log --log-file demo.log
set "CODE=%errorlevel%"

taskkill /fi "WINDOWTITLE eq mock-server*" /f >nul 2>&1
echo.
echo [demo] monitor exited with code %CODE%. The fake API has been stopped.
pause
endlocal
