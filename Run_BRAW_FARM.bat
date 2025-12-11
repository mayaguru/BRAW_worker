@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo BRAW Render Farm UI
echo ========================================
echo.

cd braw_batch_ui

REM Check uv installation
where uv > nul 2>&1
if errorlevel 1 (
    echo [1/3] Installing uv...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo uv installation failed\!
        pause
        exit /b 1
    )
    echo uv installed. Please restart terminal and run again.
    pause
    exit /b 0
)

REM Set local venv path (per-machine, not shared)
set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\BRAW_FARM\.venv

REM Sync dependencies
echo [2/3] Checking dependencies...
uv sync --quiet
if errorlevel 1 (
    echo Dependency installation failed\!
    pause
    exit /b 1
)

REM Run
echo [3/3] Starting...
echo.
uv run python braw_batch_ui\run_farm.py

if errorlevel 1 (
    echo.
    echo ERROR: Failed to run
    pause
)
