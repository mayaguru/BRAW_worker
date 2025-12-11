#!/usr/bin/env python3
"""
BRAW Render Farm V2 실행 스크립트
SQLite DB 기반 + Pool 시스템
"""

import sys
import subprocess
from pathlib import Path


def check_pyside6():
    """PySide6 설치 확인"""
    try:
        import PySide6
        return True
    except ImportError:
        return False


def install_pyside6():
    """PySide6 설치"""
    print("PySide6를 설치하는 중...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PySide6"])


def main():
    # PySide6 확인 및 설치
    if not check_pyside6():
        print("PySide6가 설치되어 있지 않습니다.")
        try:
            install_pyside6()
        except Exception as e:
            print(f"설치 실패: {e}")
            print("\n수동 설치: pip install PySide6")
            sys.exit(1)

    # Farm UI V2 실행
    try:
        from farm_ui_v2 import main as farm_main
        farm_main()
    except Exception as e:
        print(f"실행 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
