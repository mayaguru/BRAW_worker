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
                "parallel_workers": self.parallel_workers
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
            "parallel_workers": self.parallel_workers
        }


# 전역 설정 인스턴스
settings = FarmSettings()
