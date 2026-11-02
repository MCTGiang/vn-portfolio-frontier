@echo off
cd /d D:\Projects\vn-portfolio-frontier
if not exist logs mkdir logs

REM Locale-independent YYYYMMDD via PowerShell (fixes VN date "T 2, 11/ 2/2026" bug)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set LOGDATE=%%i
set LOGFILE=logs\predictions_%LOGDATE%.log

echo. >> "%LOGFILE%"
echo === Scheduler run started: %date% %time% === >> "%LOGFILE%"
echo CWD: %CD% >> "%LOGFILE%"

if not exist .venv\Scripts\activate.bat (
    echo FATAL: .venv not found >> "%LOGFILE%"
    exit /b 98
)
call .venv\Scripts\activate.bat
where python >> "%LOGFILE%" 2>&1

python scripts\log_daily_prediction.py --today >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%

echo === Scheduler run finished rc=%RC%: %date% %time% === >> "%LOGFILE%"
exit /b %RC%
