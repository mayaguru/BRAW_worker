@echo off
chcp 65001 > nul
echo ========================================
echo   BRAW-Brew EXE 빌드
echo ========================================
echo.

cd /d "%~dp0"

REM uv sync로 의존성 설치 (pyinstaller 포함)
echo [1/4] 의존성 설치 중...
uv sync
if errorlevel 1 (
    echo 의존성 설치 실패!
    pause
    exit /b 1
)

REM PyInstaller로 빌드
echo.
echo [2/4] PyInstaller로 빌드 중...
uv run pyinstaller --clean --noconfirm BRAW-Brew.spec
if errorlevel 1 (
    echo 빌드 실패!
    pause
    exit /b 1
)

REM 빌드된 exe를 build/bin으로 복사
echo.
echo [3/4] build/bin 폴더로 복사 중...
set "DEST=..\build\bin"
if not exist "%DEST%" mkdir "%DEST%"

copy /Y "dist\BRAW-Brew.exe" "%DEST%\BRAW-Brew.exe"
if errorlevel 1 (
    echo 복사 실패!
    pause
    exit /b 1
)

REM 정리
echo.
echo [4/4] 임시 파일 정리 중...
rmdir /S /Q build 2>nul
rmdir /S /Q dist 2>nul

echo.
echo ========================================
echo   빌드 완료!
echo   위치: %DEST%\BRAW-Brew.exe
echo ========================================
echo.
pause
