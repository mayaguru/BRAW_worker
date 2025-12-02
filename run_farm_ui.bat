@echo off
cd /d "%~dp0"

echo ========================================
echo BRAW Render Farm UI
echo ========================================
echo.

echo Checking dependencies...
cd braw_batch_ui
uv sync
echo.

echo Starting Render Farm UI...
echo.

uv run python braw_batch_ui\farm_ui.py

if errorlevel 1 (
    echo.
    echo ERROR: Failed to run
    echo Please check if uv and PySide6 are installed
    pause
)
