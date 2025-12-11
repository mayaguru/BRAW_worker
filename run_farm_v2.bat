@echo off
chcp 65001 >nul
title BRAW Render Farm V2

set BRAW_FARM_DB=P:\99-Pipeline\Blackmagic\Braw_convert_Project\farm.db
set BRAW_FARM_ROOT=P:\99-Pipeline\Blackmagic\Braw_convert_Project
set BRAW_CLI_PATH=P:\00-GIGA\BRAW_CLI\build\bin\braw_cli.exe
set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\braw_farm_v2\.venv
set UV_LINK_MODE=copy

echo ============================================
echo  BRAW Render Farm V2
echo  DB: %BRAW_FARM_DB%
echo  venv: %UV_PROJECT_ENVIRONMENT%
echo ============================================
echo.

cd /d "%~dp0braw_batch_ui"
uv run python -m braw_batch_ui.farm_ui_v2

pause
