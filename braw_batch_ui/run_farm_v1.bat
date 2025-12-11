@echo off
chcp 65001 >nul
title BRAW Render Farm V1

REM ============================================
REM BRAW Render Farm V1 실행 배치 파일
REM JSON 파일 기반 (기존 방식)
REM ============================================

echo ============================================
echo  BRAW Render Farm V1 (JSON 기반)
echo ============================================
echo.

cd /d "%~dp0"
uv run python -m braw_batch_ui.farm_ui

pause
