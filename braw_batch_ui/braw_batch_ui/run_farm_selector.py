#!/usr/bin/env python3
"""
BRAW Render Farm 버전 선택 스크립트
V1 (JSON 기반) 또는 V2 (SQLite DB 기반) 선택 실행
"""

import sys
import subprocess


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


def show_selector():
    """버전 선택 다이얼로그"""
    from PySide6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QLabel,
        QPushButton, QHBoxLayout, QGroupBox
    )
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)

    dialog = QDialog()
    dialog.setWindowTitle("BRAW Render Farm - 버전 선택")
    dialog.setFixedSize(400, 300)

    layout = QVBoxLayout(dialog)

    # 제목
    title = QLabel("BRAW Render Farm")
    title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
    title.setAlignment(Qt.AlignCenter)
    layout.addWidget(title)

    # V1 그룹
    v1_group = QGroupBox("V1 - JSON 파일 기반")
    v1_layout = QVBoxLayout(v1_group)
    v1_desc = QLabel("기존 방식: .json 파일로 작업 관리\n소규모 렌더팜에 적합 (워커 ~50개)")
    v1_desc.setWordWrap(True)
    v1_layout.addWidget(v1_desc)
    v1_btn = QPushButton("V1 실행")
    v1_btn.clicked.connect(lambda: (setattr(dialog, 'selected_version', 'v1'), dialog.accept()))
    v1_layout.addWidget(v1_btn)
    layout.addWidget(v1_group)

    # V2 그룹
    v2_group = QGroupBox("V2 - SQLite DB 기반 (권장)")
    v2_layout = QVBoxLayout(v2_group)
    v2_desc = QLabel("새 방식: SQLite DB로 작업 관리\n대규모 렌더팜에 적합 (워커 200개+)\nPool 시스템으로 워커 그룹 분리 지원")
    v2_desc.setWordWrap(True)
    v2_layout.addWidget(v2_desc)
    v2_btn = QPushButton("V2 실행 (권장)")
    v2_btn.setStyleSheet("font-weight: bold;")
    v2_btn.clicked.connect(lambda: (setattr(dialog, 'selected_version', 'v2'), dialog.accept()))
    v2_layout.addWidget(v2_btn)
    layout.addWidget(v2_group)

    # 취소 버튼
    cancel_btn = QPushButton("취소")
    cancel_btn.clicked.connect(dialog.reject)
    layout.addWidget(cancel_btn)

    dialog.selected_version = None

    if dialog.exec() == QDialog.Accepted:
        return dialog.selected_version
    return None


def main():
    # 명령줄 인수 확인
    if len(sys.argv) > 1:
        version = sys.argv[1].lower()
        if version in ('v1', '1'):
            run_v1()
            return
        elif version in ('v2', '2'):
            run_v2()
            return
        else:
            print(f"알 수 없는 버전: {version}")
            print("사용법: python run_farm_selector.py [v1|v2]")
            sys.exit(1)

    # PySide6 확인 및 설치
    if not check_pyside6():
        print("PySide6가 설치되어 있지 않습니다.")
        try:
            install_pyside6()
        except Exception as e:
            print(f"설치 실패: {e}")
            print("\n수동 설치: pip install PySide6")
            sys.exit(1)

    # 버전 선택 다이얼로그
    version = show_selector()

    if version == 'v1':
        run_v1()
    elif version == 'v2':
        run_v2()
    else:
        print("취소됨")
        sys.exit(0)


def run_v1():
    """V1 실행"""
    try:
        from farm_ui import main as farm_main
        farm_main()
    except Exception as e:
        print(f"V1 실행 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_v2():
    """V2 실행"""
    try:
        from farm_ui_v2 import main as farm_main
        farm_main()
    except Exception as e:
        print(f"V2 실행 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
