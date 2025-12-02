@echo off
echo ========================================
echo BRAW Render Farm 배포
echo ========================================
echo.

set SOURCE_DIR=%~dp0braw_batch_ui
set DEST_DIR=P:\00-GIGA\BRAW_CLI\braw_batch_ui

echo 소스: %SOURCE_DIR%
echo 대상: %DEST_DIR%
echo.

if not exist "%DEST_DIR%" (
    echo 대상 폴더 생성 중...
    mkdir "%DEST_DIR%"
)

echo 파일 복사 중...
xcopy /E /I /Y "%SOURCE_DIR%" "%DEST_DIR%"

if errorlevel 1 (
    echo.
    echo ERROR: 복사 실패
    pause
    exit /b 1
)

echo.
echo 배포 완료!
echo.
echo 공유 폴더에서 실행:
echo   P:\00-GIGA\BRAW_CLI\braw_batch_ui\run_farm.bat
echo.
pause
