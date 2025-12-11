#!/usr/bin/env python3
"""
BRAW Render Farm Configuration
설정 파일 관리
"""

import json
import threading
from pathlib import Path
from typing import Optional


# ===== 상수 정의 =====

# 타임아웃 (초)
HEARTBEAT_INTERVAL_SEC = 30  # 하트비트 간격
WORKER_TIMEOUT_SEC = 120  # 워커 활성 판정 타임아웃 (2분)
SUBPROCESS_TIMEOUT_DEFAULT_SEC = 60  # 기본 서브프로세스 타임아웃
SUBPROCESS_TIMEOUT_ACES_SEC = 90  # ACES 색공간 변환 시 타임아웃
# 클레임 타임아웃은 반드시 서브프로세스 타임아웃보다 커야 함 (15대 동시 운영 고려)
# CLAIM_TIMEOUT_SEC > SUBPROCESS_TIMEOUT_ACES_SEC + 여유시간(30초)
CLAIM_TIMEOUT_SEC = 120  # 프레임 클레임 타임아웃 (90초 → 120초)
CLIP_INFO_TIMEOUT_SEC = 10  # 클립 정보 조회 타임아웃

# 로그 관련
LOG_MAX_LINES = 5000  # 로그 위젯 최대 라인 수

# 파일 검증
MIN_FILE_SIZE_RATIO = 0.7  # 평균 대비 최소 파일 크기 비율 (70%)

# ===== 15대 동시 운영 최적화 설정 =====

# 파일 I/O 재시도 설정
FILE_IO_MAX_RETRIES = 3  # 파일 읽기/쓰기 최대 재시도 횟수
FILE_IO_RETRY_DELAY_BASE = 0.1  # 재시도 기본 딜레이 (초)
FILE_IO_RETRY_DELAY_MAX = 1.0  # 재시도 최대 딜레이 (초)

# 클레임 충돌 방지 설정
CLAIM_RANDOM_DELAY_MIN = 0.01  # 클레임 시 최소 랜덤 딜레이 (초)
CLAIM_RANDOM_DELAY_MAX = 0.05  # 클레임 시 최대 랜덤 딜레이 (초)
CLAIM_VERIFY_DELAY = 0.02  # 클레임 검증 딜레이 (초)

# 작업 분산 설정 (15대가 같은 프레임으로 몰리지 않도록)
FRAME_SEARCH_RANDOM_START = False  # 프레임 검색 시 순차 시작 (True: 랜덤 분산)
FRAME_SEARCH_BATCH_SIZE = 50  # 한 번에 검색할 프레임 범위

# 범위 기반 배치 처리 설정 (새 CLI 인터페이스)
BATCH_FRAME_SIZE = 10  # 한 번에 처리할 프레임 수 (5프레임 단위 - 12워커 시 60프레임/1초)
BATCH_CLAIM_TIMEOUT_SEC = 600  # 배치 클레임 타임아웃 (12워커 동시 실행 시 I/O 경쟁 고려, 10분)

# 네트워크 파일시스템 안정성
NFS_WRITE_SYNC_DELAY = 0.01  # 쓰기 후 동기화 대기 (초)
NFS_READ_RETRY_ON_EMPTY = True  # 빈 파일 읽기 시 재시도


class FarmSettings:
    """렌더팜 설정 (스레드 안전)"""

    def __init__(self):
        self._lock = threading.RLock()  # 재진입 가능 락

        # 기본 설정
        self.farm_root = "P:/99-Pipeline/Blackmagic/Braw_convert_Project"  # 공용 렌더팜 저장소
        self.db_path = "P:/99-Pipeline/Blackmagic/Braw_convert_Project/farm.db"  # DB 경로
        self.cli_path = "P:/00-GIGA/BRAW_CLI/build/bin/braw_cli.exe"  # CLI 실행 파일 경로
        self.parallel_workers = 16
        self.max_retries = 5  # 최대 재시도 횟수
        self.last_output_folder = ""  # 마지막으로 사용한 출력 폴더

        # OCIO 설정
        self.ocio_config_path = ""  # OCIO config 파일 경로
        self.color_input_space = "BMDFilm WideGamut Gen5"  # 입력 색공간
        self.color_output_space = "ACEScg"  # 출력 색공간
        self.color_presets = {}  # 색공간 프리셋 저장 {"프리셋이름": {"input": "...", "output": "..."}}
        self.last_preset = ""  # 마지막 선택한 프리셋

        # 렌더링 옵션 저장
        self.render_left = True  # L 체크
        self.render_right = True  # R 체크
        self.render_sbs = False  # SBS 체크
        self.render_format_exr = True  # EXR 포맷 (False면 PPM)
        self.render_clip_folder = True  # 영상별폴더
        self.render_separate_lr = True  # L/R분리
        self.render_use_aces = True  # 색변환
        self.render_use_stmap = False  # STMAP 적용
        self.stmap_path = ""  # STMAP EXR 파일 경로

        # 배치 처리 설정
        self.batch_frame_size = 10  # 연속 처리 프레임 수 (5프레임 * 12워커 = 60프레임/1초)

        # SeqChecker 설정
        self.seqchecker_path = "P:/00-GIGA/BRAW_CLI/tool/SeqChecker/seqchecker.exe"
        self.seqchecker_auto_scan = True  # 작업 완료 후 자동 스캔
        self.seqchecker_auto_rerender = True  # 오류 프레임 자동 재렌더 잡 생성

        # 설정 파일 경로 (로컬 - 내 문서)
        # Windows: C:\Users\사용자명\Documents\BRAW Farm\config.json
        # 다른 OS: ~/Documents/BRAW Farm/config.json
        documents = Path.home() / "Documents"
        self.config_file = documents / "BRAW Farm" / "config.json"

        # 설정 로드
        self.load()

    def load(self):
        """설정 파일 로드 (스레드 안전)"""
        with self._lock:
            if self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.farm_root = data.get("farm_root", self.farm_root)
                        self.db_path = data.get("db_path", self.db_path)
                        self.cli_path = data.get("cli_path", self.cli_path)
                        self.parallel_workers = data.get("parallel_workers", self.parallel_workers)
                        self.max_retries = data.get("max_retries", self.max_retries)
                        self.last_output_folder = data.get("last_output_folder", self.last_output_folder)
                        # OCIO 설정
                        self.ocio_config_path = data.get("ocio_config_path", self.ocio_config_path)
                        self.color_input_space = data.get("color_input_space", self.color_input_space)
                        self.color_output_space = data.get("color_output_space", self.color_output_space)
                        self.color_presets = data.get("color_presets", self.color_presets)
                        self.last_preset = data.get("last_preset", self.last_preset)
                        # 렌더링 옵션
                        self.render_left = data.get("render_left", self.render_left)
                        self.render_right = data.get("render_right", self.render_right)
                        self.render_sbs = data.get("render_sbs", self.render_sbs)
                        self.render_format_exr = data.get("render_format_exr", self.render_format_exr)
                        self.render_clip_folder = data.get("render_clip_folder", self.render_clip_folder)
                        self.render_separate_lr = data.get("render_separate_lr", self.render_separate_lr)
                        self.render_use_aces = data.get("render_use_aces", self.render_use_aces)
                        self.render_use_stmap = data.get("render_use_stmap", self.render_use_stmap)
                        self.stmap_path = data.get("stmap_path", self.stmap_path)
                        # 배치 처리 설정
                        self.batch_frame_size = data.get("batch_frame_size", self.batch_frame_size)
                        # SeqChecker 설정
                        self.seqchecker_path = data.get("seqchecker_path", self.seqchecker_path)
                        self.seqchecker_auto_scan = data.get("seqchecker_auto_scan", self.seqchecker_auto_scan)
                        self.seqchecker_auto_rerender = data.get("seqchecker_auto_rerender", self.seqchecker_auto_rerender)
                except (json.JSONDecodeError, OSError) as e:
                    print(f"설정 로드 실패: {e}")

    def save(self):
        """설정 파일 저장 (스레드 안전)"""
        with self._lock:
            try:
                # 설정 디렉토리 생성
                self.config_file.parent.mkdir(parents=True, exist_ok=True)

                # 설정 저장
                data = {
                    "farm_root": self.farm_root,
                    "db_path": self.db_path,
                    "cli_path": self.cli_path,
                    "parallel_workers": self.parallel_workers,
                    "max_retries": self.max_retries,
                    "last_output_folder": self.last_output_folder,
                    "ocio_config_path": self.ocio_config_path,
                    "color_input_space": self.color_input_space,
                    "color_output_space": self.color_output_space,
                    "color_presets": self.color_presets,
                    "last_preset": self.last_preset,
                    "render_left": self.render_left,
                    "render_right": self.render_right,
                    "render_sbs": self.render_sbs,
                    "render_format_exr": self.render_format_exr,
                    "render_clip_folder": self.render_clip_folder,
                    "render_separate_lr": self.render_separate_lr,
                    "render_use_aces": self.render_use_aces,
                    "render_use_stmap": self.render_use_stmap,
                    "stmap_path": self.stmap_path,
                    "batch_frame_size": self.batch_frame_size,
                    "seqchecker_path": self.seqchecker_path,
                    "seqchecker_auto_scan": self.seqchecker_auto_scan,
                    "seqchecker_auto_rerender": self.seqchecker_auto_rerender
                }

                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except (OSError, IOError) as e:
                print(f"설정 저장 실패: {e}")

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            "farm_root": self.farm_root,
            "db_path": self.db_path,
            "cli_path": self.cli_path,
            "parallel_workers": self.parallel_workers,
            "last_output_folder": self.last_output_folder
        }


# 전역 설정 인스턴스
settings = FarmSettings()
