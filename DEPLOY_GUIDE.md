# BRAW-Brew 배포 가이드

공유 폴더에 배포하여 여러 PC에서 실행하는 방법

## 📦 배포 순서

### 1. 자동 배포 (권장)

```batch
# 프로젝트 루트에서
DEPLOY.bat
```

이 명령으로 자동으로:
1. 프로그램 파일 → `P:\00-GIGA\BRAW_CLI\braw_batch_ui\`
2. CLI 실행 파일 → `P:\00-GIGA\BRAW_CLI\braw_cli.exe`
3. **BRAW SDK DLL** → `P:\00-GIGA\BRAW_CLI\*.dll`

### 2. 수동 배포 (자동 배포 실패 시)

**A. 프로그램 파일**
```
복사: d:\_DEV\Braw\braw_batch_ui\
대상: P:\00-GIGA\BRAW_CLI\braw_batch_ui\
```

**B. CLI 실행 파일**
```
복사: d:\_DEV\Braw\build\bin\braw_cli.exe
대상: P:\00-GIGA\BRAW_CLI\braw_cli.exe
```

**C. BRAW SDK DLL (중요!)**
```
복사: C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win\Libraries\*.dll
대상: P:\00-GIGA\BRAW_CLI\

필요한 DLL:
- BlackmagicRawAPI.dll
- DecoderCUDA.dll
- DecoderOpenCL.dll
- InstructionSetServicesAVX.dll
- InstructionSetServicesAVX2.dll
```

**최종 구조 (방법 A - 루트에 배치):**
```
P:\00-GIGA\BRAW_CLI\
├─ braw_cli.exe                      ← CLI 실행 파일
├─ BlackmagicRawAPI.dll              ← SDK DLL (필수!)
├─ DecoderCUDA.dll                   ← 디코더 DLL
├─ DecoderOpenCL.dll                 ← 디코더 DLL
├─ InstructionSetServicesAVX.dll     ← 최적화 DLL
├─ InstructionSetServicesAVX2.dll    ← 최적화 DLL
├─ braw_batch_ui\                    ← 프로그램 폴더
│   ├─ braw_batch_ui\
│   │   ├─ farm_ui.py
│   │   ├─ farm_core.py
│   │   └─ run_farm.py
│   ├─ run_farm.bat                  ← 실행 파일
│   └─ pyproject.toml
├─ workers\                          ← 자동 생성
├─ jobs\                             ← 자동 생성
├─ claims\                           ← 자동 생성
└─ completed\                        ← 자동 생성
```

**최종 구조 (방법 B - build/bin에 배치, 더 간단!):**
```
P:\00-GIGA\BRAW_CLI\
├─ build\
│   └─ bin\
│       ├─ braw_cli.exe              ← CLI 실행 파일
│       ├─ BlackmagicRawAPI.dll      ← SDK DLL (필수!)
│       ├─ DecoderCUDA.dll           ← 디코더 DLL
│       ├─ DecoderOpenCL.dll         ← 디코더 DLL
│       ├─ InstructionSetServicesAVX.dll
│       └─ InstructionSetServicesAVX2.dll
├─ braw_batch_ui\                    ← 프로그램 폴더
│   ├─ braw_batch_ui\
│   │   ├─ farm_ui.py
│   │   ├─ farm_core.py
│   │   └─ run_farm.py
│   ├─ run_farm.bat                  ← 실행 파일
│   └─ pyproject.toml
├─ workers\                          ← 자동 생성
├─ jobs\                             ← 자동 생성
├─ claims\                           ← 자동 생성
└─ completed\                        ← 자동 생성
```

**참고**: 방법 B를 사용하면 개발 환경과 동일한 구조로 배포할 수 있어 더 간단합니다!

## 🖥️ 각 PC에서 실행

### 초기 설정 (PC마다 1회만)

1. **Python 설치 확인**
   ```
   python --version
   ```
   Python 3.8 이상 필요

2. **PySide6 설치** (자동 설치됨)
   - 처음 실행 시 자동으로 설치

### 실행 방법

**각 PC에서:**
```
P:\00-GIGA\BRAW_CLI\braw_batch_ui\run_farm.bat
```

또는 직접 실행:
```
cd P:\00-GIGA\BRAW_CLI\braw_batch_ui
python braw_batch_ui\run_farm.py
```

## 🎯 사용 흐름

### 작업 제출 PC (1대)

1. BRAW-Brew UI 실행
2. **"작업 제출" 탭**으로 이동
3. BRAW 파일 선택
4. 출력 폴더 선택
5. 프레임 범위 설정
6. **"작업 제출"** 클릭

### 워커 PC들 (모든 PC)

1. BRAW-Brew UI 실행
2. **"워커" 탭**으로 이동
3. 병렬 작업 수 설정 (기본: 10)
4. **"워커 시작"** 클릭
5. 자동으로 작업 처리 시작

### 모니터링 PC (선택)

1. BRAW-Brew UI 실행
2. **"모니터링" 탭**으로 이동
3. 실시간 진행 상황 확인

## ⚙️ 설정

### CLI 경로 자동 탐지

프로그램이 자동으로 다음 위치에서 CLI를 찾습니다:
1. `P:\00-GIGA\BRAW_CLI\braw_cli.exe`
2. `P:\00-GIGA\BRAW_CLI\braw_batch_ui\braw_cli.exe`
3. 개발 환경의 build 폴더

### 공유 폴더 경로 변경

`farm_core.py` 파일 수정:
```python
class FarmConfig:
    def __init__(self, farm_root: str = "P:/00-GIGA/BRAW_CLI"):
        # 여기서 경로 변경
```

## 🔧 문제 해결

### ⚠️ 워커가 프레임 처리를 못함 (가장 중요!)

**증상:**
- 워커가 작업을 찾지만 프레임 처리가 실패 (✗ 표시)
- 개발 PC에서는 되는데 다른 PC에서는 안됨

**원인:**
- BRAW SDK DLL이 없음

**해결:**
1. **자동 배포 재실행** (개발 PC에서):
   ```batch
   DEPLOY.bat
   ```

2. **수동 복사** (자동 배포 실패 시):
   ```
   복사: C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win\Libraries\*.dll
   대상: P:\00-GIGA\BRAW_CLI\
   ```

3. **확인:**
   ```
   P:\00-GIGA\BRAW_CLI\ 폴더에 다음 파일들이 있는지 확인:
   - BlackmagicRawAPI.dll
   - DecoderCUDA.dll
   - DecoderOpenCL.dll
   - InstructionSetServicesAVX.dll
   - InstructionSetServicesAVX2.dll
   ```

### "braw_cli.exe를 찾을 수 없습니다"

**해결:**
1. `braw_cli.exe`를 `P:\00-GIGA\BRAW_CLI\` 폴더에 복사
2. 또는 `P:\00-GIGA\BRAW_CLI\braw_batch_ui\` 폴더에 복사

### "PySide6가 설치되지 않았습니다"

**해결:**
```
pip install PySide6
```

### "공유 폴더에 접근할 수 없습니다"

**해결:**
1. 네트워크 드라이브 연결 확인
2. `P:` 드라이브가 `\\00-GIGA\...`에 매핑되어 있는지 확인
3. 읽기/쓰기 권한 확인

### 워커가 작업을 못 찾음

**해결:**
1. `P:\00-GIGA\BRAW_CLI\jobs\` 폴더 확인
2. 작업 제출이 제대로 되었는지 확인
3. 네트워크 공유 설정 확인

## 📊 성능 최적화

### 병렬 작업 수 조정

**권장 설정:**
- 일반 PC: 5-10개
- 고성능 PC: 10-20개
- 서버급 PC: 20-50개

**주의:**
- CPU 코어 수보다 많이 설정해도 됨 (I/O 대기 시간 활용)
- 너무 많으면 메모리 부족 가능

### 네트워크 최적화

- 기가비트 이더넷 사용 권장
- Wi-Fi보다 유선 연결 권장
- 공유 폴더가 SSD에 있으면 더 빠름

## 🔄 업데이트

프로그램 업데이트 시:

1. 모든 워커 중지
2. `DEPLOY.bat` 재실행
3. 필요시 `braw_cli.exe`도 다시 복사
4. 워커 재시작

## 📝 로그 위치

- 워커 로그: UI의 "워커" 탭에서 실시간 확인
- 작업 상태: `P:\00-GIGA\BRAW_CLI\` 폴더의 서브 폴더들
  - `workers\`: 워커 하트비트
  - `jobs\`: 작업 정보
  - `claims\`: 진행중인 프레임
  - `completed\`: 완료된 프레임

## ✅ 체크리스트

배포 전:
- [ ] `DEPLOY.bat` 실행
- [ ] `braw_cli.exe` 복사
- [ ] 공유 폴더 접근 권한 확인

각 PC에서:
- [ ] Python 설치 확인
- [ ] 네트워크 드라이브 연결 확인
- [ ] BRAW-Brew UI 실행 테스트

작업 제출 시:
- [ ] BRAW 파일 경로 확인
- [ ] 출력 폴더 경로 확인 (모든 PC에서 접근 가능한지)
- [ ] 프레임 범위 확인
