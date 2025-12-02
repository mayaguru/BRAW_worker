@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64

echo Cleaning build directory...
rmdir /s /q build 2>nul
mkdir build

echo Configuring CMake...
cmake -B build -DCMAKE_BUILD_TYPE=Release -DBRAW_ENABLE_SDK=ON -DBUILD_UI=OFF
if errorlevel 1 (
    echo CMake configuration failed!
    pause
    exit /b 1
)

echo Building...
cmake --build build --config Release
if errorlevel 1 (
    echo Build failed!
    pause
    exit /b 1
)

echo Build completed successfully!
pause
