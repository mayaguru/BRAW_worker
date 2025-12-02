@echo off
cd /d "%~dp0"

echo ========================================
echo BRAW Render Farm UI
echo ========================================
echo.

REM CLI 경로 찾기
set CLI_PATH=

REM 1. 로컬 build 폴더 확인
if exist "..\build\bin\braw_cli.exe" (
    set CLI_PATH=..\build\bin\braw_cli.exe
    goto :found_cli
)

if exist "..\build\src\app\Release\braw_cli.exe" (
    set CLI_PATH=..\build\src\app\Release\braw_cli.exe
    goto :found_cli
)

REM 2. 현재 폴더에 CLI 있는지 확인
if exist "braw_cli.exe" (
    set CLI_PATH=braw_cli.exe
    goto :found_cli
)

REM 3. 공유 폴더 상위에서 찾기
if exist "..\braw_cli.exe" (
    set CLI_PATH=..\braw_cli.exe
    goto :found_cli
)

echo ERROR: braw_cli.exe를 찾을 수 없습니다.
echo.
echo 다음 중 하나의 위치에 braw_cli.exe를 배치하세요:
echo   1. %~dp0braw_cli.exe
echo   2. %~dp0..\braw_cli.exe
echo   3. %~dp0..\build\bin\braw_cli.exe
echo.
pause
exit /b 1

:found_cli
echo CLI 경로: %CLI_PATH%
echo.

REM Python 가상환경 확인
if exist ".venv\Scripts\python.exe" (
    echo 가상환경에서 실행...
    .venv\Scripts\python.exe braw_batch_ui\run_farm.py
) else (
    echo 시스템 Python에서 실행...
    python braw_batch_ui\run_farm.py
)

if errorlevel 1 (
    echo.
    echo ERROR: 실행 실패
    echo.
    echo 수동 설치:
    echo   pip install PySide6
    echo.
    pause
)
