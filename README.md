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

Windows에서 Blackmagic RAW SDK를 설치했다면 기본 경로(`C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK`)를 자동으로 감지합니다. 다른 위치를 사용한다면 `-DBRAW_SDK_ROOT="D:/path/Blackmagic RAW SDK"` 옵션을 주면 됩니다. Visual Studio(또는 Build Tools)의 `midl.exe` 가 필요하며, CMake가 자동으로 IDL을 컴파일해 `BlackmagicRawAPI.h` 를 생성합니다.

EXR(DWAA) 내보내기를 사용하려면 OpenEXR/Imath 헤더와 라이브러리(`OpenEXR-3_x.lib`, `Imath-3_x.lib`, `Iex-3_x.lib`, `IlmThread-3_x.lib`)를 `third_party/OpenEXR` 또는 사용자 지정 경로에 배치한 뒤 `-DOPENEXR_ROOT="D:/path/OpenEXR"` 를 지정하세요. 구성 중에 `OpenEXR found` 메시지가 출력되면 성공적으로 감지된 것입니다.

## 사용 예시

```bash
build/Release/braw_cli D:/_DEV/Braw/A001_11051030_C001.braw frame0000.ppm 0        # 좌안(default)
build/Release/braw_cli D:/_DEV/Braw/A001_11051030_C001.braw frame0000.ppm 0 right  # 우안
build/Release/braw_cli D:/_DEV/Braw/A001_11051030_C001.braw frame0000.ppm 0 both   # 좌/우 모두
build/Release/braw_viewer
```

`braw_cli` 는 지정한 프레임을 16bit PPM으로 추출합니다. 마지막 인자로 `left`/`right`/`both` 를 넘기면 VR 스테레오 클립에서 원하는 시야를 선택할 수 있고, `both` 인 경우 `<output>_L`, `<output>_R` 두 파일이 생성됩니다. `braw_viewer` 는 Qt UI에서 BRAW 파일을 선택해 첫 프레임을 즉시 확인할 수 있는 미리보기입니다. SDK가 없는 상태에서는 가짜 그라디언트 이미지를 보여 주며, SDK가 정상적으로 로드되면 Blackmagic RAW 디코더를 통해 실 프레임을 GPU/CPU 경로로 처리합니다. DLL을 복사하지 않아도 설치 경로(예: `C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win\Libraries`)가 자동으로 사용됩니다.
