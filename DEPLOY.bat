@echo off
echo ========================================
echo BRAW Render Farm 배포
echo ========================================
echo.

set SOURCE_DIR=%~dp0braw_batch_ui
set DEST_DIR=P:\00-GIGA\BRAW_CLI\braw_batch_ui
set CLI_DEST=P:\00-GIGA\BRAW_CLI
set SDK_DIR=C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win\Libraries

echo 소스: %SOURCE_DIR%
echo 대상: %DEST_DIR%
echo.

REM 1. 프로그램 파일 복사
if not exist "%DEST_DIR%" (
    echo 대상 폴더 생성 중...
    mkdir "%DEST_DIR%"
)

echo [1/3] 프로그램 파일 복사 중...
xcopy /E /I /Y "%SOURCE_DIR%" "%DEST_DIR%"

if errorlevel 1 (
    echo.
    echo ERROR: 프로그램 복사 실패
    pause
    exit /b 1
)

REM 2. CLI 실행 파일 복사
echo.
echo [2/3] CLI 실행 파일 복사 중...

if exist "%~dp0build\bin\braw_cli.exe" (
    copy /Y "%~dp0build\bin\braw_cli.exe" "%CLI_DEST%\"
    echo   복사: build\bin\braw_cli.exe
) else if exist "%~dp0build\src\app\Release\braw_cli.exe" (
    copy /Y "%~dp0build\src\app\Release\braw_cli.exe" "%CLI_DEST%\"
    echo   복사: build\src\app\Release\braw_cli.exe
) else (
    echo   경고: braw_cli.exe를 찾을 수 없습니다.
    echo   수동으로 복사하세요: %CLI_DEST%\braw_cli.exe
)

REM 3. BRAW SDK DLL 복사
echo.
echo [3/3] BRAW SDK DLL 복사 중...

if exist "%SDK_DIR%\BlackmagicRawAPI.dll" (
    copy /Y "%SDK_DIR%\*.dll" "%CLI_DEST%\"
    echo   복사: SDK DLL 파일들
    echo     - BlackmagicRawAPI.dll
    echo     - DecoderCUDA.dll
    echo     - DecoderOpenCL.dll
    echo     - InstructionSetServicesAVX.dll
    echo     - InstructionSetServicesAVX2.dll
) else (
    echo   경고: BRAW SDK DLL을 찾을 수 없습니다.
    echo   경로: %SDK_DIR%
    echo.
    echo   수동 복사가 필요합니다:
    echo   1. Blackmagic RAW SDK 설치
    echo   2. DLL 파일을 %CLI_DEST%\ 로 복사
)

echo.
echo ========================================
echo 배포 완료!
echo ========================================
echo.
echo 공유 폴더 구조:
echo   P:\00-GIGA\BRAW_CLI\
echo   ├─ braw_cli.exe           (CLI 실행 파일)
echo   ├─ BlackmagicRawAPI.dll   (SDK DLL)
echo   ├─ Decoder*.dll           (디코더 DLL)
echo   └─ braw_batch_ui\         (렌더팜 프로그램)
echo.
echo 각 PC에서 실행:
echo   P:\00-GIGA\BRAW_CLI\braw_batch_ui\run_farm.bat
echo.
pause
