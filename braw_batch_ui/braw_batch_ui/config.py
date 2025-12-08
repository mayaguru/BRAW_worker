#!/usr/bin/env python3
"""
BRAW Render Farm Configuration
설정 파일 관리
"""

import json
from pathlib import Path
from typing import Optional


class FarmSettings:
    """렌더팜 설정"""

    def __init__(self):
        # 기본 설정
        self.farm_root = "P:/00-GIGA/BRAW_CLI"  # 공용 렌더팜 저장소
        self.cli_path = "P:/00-GIGA/BRAW_CLI/build/bin/braw_cli.exe"  # CLI 실행 파일 경로
        self.parallel_workers = 16
        self.last_output_folder = ""  # 마지막으로 사용한 출력 폴더

        # OCIO 설정
        self.ocio_config_path = ""  # OCIO config 파일 경로
        self.color_input_space = "BMDFilm WideGamut Gen5"  # 입력 색공간
        self.color_output_space = "ACEScg"  # 출력 색공간
        self.color_presets = {}  # 색공간 프리셋 저장 {"프리셋이름": {"input": "...", "output": "..."}}

        # 설정 파일 경로 (로컬 - 내 문서)
        from pathlib import Path
        import os

        # Windows: C:\Users\사용자명\Documents\BRAW Farm\config.json
        # 다른 OS: ~/Documents/BRAW Farm/config.json
        documents = Path.home() / "Documents"
        self.config_file = documents / "BRAW Farm" / "config.json"

        # 설정 로드
        self.load()

    def load(self):
        """설정 파일 로드"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.farm_root = data.get("farm_root", self.farm_root)
                    self.cli_path = data.get("cli_path", self.cli_path)
                    self.parallel_workers = data.get("parallel_workers", self.parallel_workers)
                    self.last_output_folder = data.get("last_output_folder", self.last_output_folder)
                    # OCIO 설정
                    self.ocio_config_path = data.get("ocio_config_path", self.ocio_config_path)
                    self.color_input_space = data.get("color_input_space", self.color_input_space)
                    self.color_output_space = data.get("color_output_space", self.color_output_space)
                    self.color_presets = data.get("color_presets", self.color_presets)
            except Exception as e:
                print(f"설정 로드 실패: {e}")

    def save(self):
        """설정 파일 저장"""
        try:
            # 설정 디렉토리 생성
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # 설정 저장
            data = {
                "farm_root": self.farm_root,
                "cli_path": self.cli_path,
                "parallel_workers": self.parallel_workers,
                "last_output_folder": self.last_output_folder,
                "ocio_config_path": self.ocio_config_path,
                "color_input_space": self.color_input_space,
                "color_output_space": self.color_output_space,
                "color_presets": self.color_presets
            }

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"설정 저장 실패: {e}")

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            "farm_root": self.farm_root,
            "cli_path": self.cli_path,
            "parallel_workers": self.parallel_workers,
            "last_output_folder": self.last_output_folder
        }


# 전역 설정 인스턴스
settings = FarmSettings()
