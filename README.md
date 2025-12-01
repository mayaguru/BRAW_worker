# BRAW Converter Skeleton

이 프로젝트는 Blackmagic RAW SDK를 직접 사용해 BRAW 파일을 디코딩하고 이미지를 출력하는 C++ 기반 파이프라인의 초기 스캐폴드입니다. Python 의존성 없이 Dimension_Player 스타일의 구조(코어 DLL, Export 모듈, CLI/UI 실행 파일)를 그대로 따릅니다.

## 구조

- `src/core`: BRAW 디코더, 프레임 버퍼 등 핵심 로직
- `src/export`: 테스트용 이미지 출력기 (현재는 PPM)
- `src/app`: CLI 엔트리 (`braw_cli`)
- `third_party/BlackmagicRAW`: BRAW SDK 헤더/라이브러리를 복사하는 자리

## 빌드

```bash
cmake -S . -B build -DBRAW_ENABLE_SDK=ON
cmake --build build --config Release
```

SDK 헤더(`BlackmagicRawAPI.h`)와 `lib` 파일을 `third_party/BlackmagicRAW` 밑에 복사한 뒤 위 명령을 실행하세요.

## 사용 예시

```bash
build/Release/braw_cli D:/_DEV/Braw/A001_11051030_C001.braw frame0000.ppm 0
build/Release/braw_viewer
```

`braw_viewer` 는 간단한 Qt UI로, BRAW 파일을 선택해 첫 프레임을 확인할 수 있습니다. SDK가 없는 상태에서는 가짜 데이터를 표시하므로 UI 및 파이프라인을 먼저 검증할 수 있습니다. 실제 BRAW 읽기는 SDK 헤더/라이브러리를 설치 경로(`C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\SDK`)에서 자동으로 탐지하거나 `third_party/BlackmagicRAW` 에 복사한 뒤 `-DBRAW_SDK_ROOT=...` 로 지정하면 됩니다.
