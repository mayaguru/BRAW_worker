@echo off
cd /d "%~dp0"

echo ========================================
echo BRAW Render Farm UI (Simple)
echo ========================================
echo.

cd braw_batch_ui

echo Starting...
echo.

python braw_batch_ui\run_farm.py

if errorlevel 1 (
    echo.
    echo ERROR: Failed to run
    pause
)
