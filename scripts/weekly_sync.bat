@echo off
REM Day 13 D2: Weekly sync wrapper for Windows Task Scheduler.
REM Workaround for M30 (vnstock Silver tier device registration limit).
REM Scheduled: Monday + Thursday 18:30 ICT (after HSX close + settlement buffer).
REM Script sync_prices.py has internal safety clamp (M30): skip today if < 15:30 ICT.

cd /d D:\Projects\vn-portfolio-frontier
call .venv\Scripts\activate.bat

echo [%date% %time%] Starting weekly_sync.bat
echo.

echo === sync_prices ===
python scripts\sync_prices.py --today
if %ERRORLEVEL% neq 0 (
    echo FAILED sync_prices with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo === sync_benchmarks ===
python scripts\sync_benchmarks.py --today
if %ERRORLEVEL% neq 0 (
    echo FAILED sync_benchmarks with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo [%date% %time%] weekly_sync.bat DONE
exit /b 0
