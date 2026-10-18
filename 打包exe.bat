@echo off
rem Build script: always runs in the folder this .bat lives in (project\),
rem generates metadata.txt from metadata.yaml, then packs bili_ticket_monitor.py into one exe.
setlocal
cd /d "%~dp0"

echo [1/2] generating version resource from metadata.yaml ...
pyivf-make_version --source-format yaml --metadata-source metadata.yaml --outfile metadata.txt
if errorlevel 1 goto :failed

echo [2/2] building exe with pyinstaller ...
pyinstaller -F --version-file metadata.txt bili_ticket_monitor.py
if errorlevel 1 goto :failed

echo.
echo Done. Output: "%~dp0dist\bili_ticket_monitor.exe"
echo.
pause
exit /b 0

:failed
echo.
echo Build FAILED, exit code %errorlevel%.
echo.
pause
exit /b 1
