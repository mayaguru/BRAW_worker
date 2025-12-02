@echo off
cd /d "%~dp0"

echo ========================================
echo BRAW Batch Export UI
echo ========================================
echo.

cd braw_batch_ui

echo Starting Python UI...
echo (Check taskbar if window doesn't appear)
echo.

uv run python braw_batch_ui\main.py

if errorlevel 1 (
    echo.
    echo ERROR: Failed to run
    echo Please check if uv is installed
    pause
)
