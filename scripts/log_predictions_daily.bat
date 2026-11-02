@echo off
REM =============================================================
REM scripts/log_predictions_daily.bat
REM Windows Task Scheduler wrapper for daily prediction logger.
REM
REM Setup in Task Scheduler:
REM   Name    : vn-portfolio-daily-predictions
REM   Trigger : Mon-Fri 16:30 local
REM   Depends : vn-portfolio-sync-prices (60-min delay OR separate trigger 16:30)
REM   Battery : [uncheck] Start the task only if on AC power
REM   Battery : [check]   Stop if goes to battery
REM   Program : D:\Projects\vn-portfolio-frontier\scripts\log_predictions_daily.bat
REM =============================================================

cd /d D:\Projects\vn-portfolio-frontier

REM Ensure logs folder exists
if not exist logs mkdir logs

REM Activate venv
call .venv\Scripts\activate.bat

REM Build dated log file
set LOGDATE=%date:~-4%%date:~3,2%%date:~0,2%
set LOGFILE=logs\predictions_%LOGDATE%.log

echo. >> %LOGFILE%
echo === Run started: %date% %time% === >> %LOGFILE%

REM Run logger
python scripts\log_daily_prediction.py --today >> %LOGFILE% 2>&1
set RC=%ERRORLEVEL%

echo === Run finished rc=%RC%: %date% %time% === >> %LOGFILE%

REM Non-zero exit codes:
REM   0 = clean
REM   1 = partial success (some sources failed)
REM   2 = full failure
REM Task Scheduler will show the exit code in history for monitoring.
exit /b %RC%
