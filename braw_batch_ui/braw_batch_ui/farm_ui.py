#!/usr/bin/env python3
"""
BRAW Render Farm UI (PySide6)
분산 렌더링 시스템 UI
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QTextEdit, QGroupBox, QRadioButton, QCheckBox,
                               QFileDialog, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QProgressBar, QMessageBox, QMenu, QDialog)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QUrl
from PySide6.QtGui import QFont, QColor, QAction, QDesktopServices

from farm_core import FarmManager, RenderJob, WorkerInfo
from config import settings


class SettingsDialog(QDialog):
    """설정 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("렌더팜 설정")
        self.setMinimumWidth(500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 공용 저장소 경로
        farm_root_layout = QHBoxLayout()
        farm_root_layout.addWidget(QLabel("공용 저장소:"))
        self.farm_root_input = QLineEdit(settings.farm_root)
        browse_btn = QPushButton("📁")
        browse_btn.setMaximumWidth(40)
        browse_btn.clicked.connect(self.browse_farm_root)
        farm_root_layout.addWidget(self.farm_root_input)
        farm_root_layout.addWidget(browse_btn)
        layout.addLayout(farm_root_layout)

        # 병렬 처리 수
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel("기본 병렬 처리:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(settings.parallel_workers)
        parallel_layout.addWidget(self.parallel_spin)
        parallel_layout.addStretch()
        layout.addLayout(parallel_layout)

        # 버튼
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def browse_farm_root(self):
        """공용 저장소 폴더 선택"""
        folder = QFileDialog.getExistingDirectory(self, "공용 저장소 선택")
        if folder:
            self.farm_root_input.setText(folder)

    def save_settings(self):
        """설정 저장"""
        settings.farm_root = self.farm_root_input.text()
        settings.parallel_workers = self.parallel_spin.value()
        settings.save()
        QMessageBox.information(self, "완료", "설정이 저장되었습니다.\n재시작 후 적용됩니다.")
        self.accept()


class StatusUpdateThread(QThread):
    """상태 업데이트 스레드 (UI 블로킹 방지)"""
    workers_signal = Signal(list)
    jobs_signal = Signal(list)

    def __init__(self, farm_manager):
        super().__init__()
        self.farm_manager = farm_manager
        self.is_running = False

    def run(self):
        self.is_running = True
        while self.is_running:
            try:
                workers = self.farm_manager.get_active_workers()
                jobs = self.farm_manager.get_pending_jobs()
                self.workers_signal.emit(workers)
                self.jobs_signal.emit(jobs)
            except:
                pass
            time.sleep(1)

    def stop(self):
        self.is_running = False


class WorkerThread(QThread):
    """워커 스레드 (폴더 감시 + 자동 처리)"""
    log_signal = Signal(str)
    progress_signal = Signal(int, int)  # completed, total
    network_status_signal = Signal(bool)  # network connected

    def __init__(self, farm_manager, cli_path, parallel_workers=10):
        super().__init__()
        self.farm_manager = farm_manager
        self.cli_path = Path(cli_path)
        self.parallel_workers = parallel_workers
        self.is_running = False

        # 작업 통계
        self.total_processed = 0
        self.total_success = 0
        self.total_failed = 0
        self.current_job_stats = {"success": 0, "failed": 0, "retried": 0}

    def run(self):
        """워커 메인 루프"""
        self.is_running = True
        self.log_signal.emit("=== 워커 시작 ===")
        self.log_signal.emit(f"워커 ID: {self.farm_manager.worker.worker_id}")
        self.log_signal.emit(f"병렬 처리: {self.parallel_workers}")
        self.log_signal.emit("")

        network_error_count = 0
        max_network_errors = 3

        while self.is_running:
            try:
                # 네트워크 연결 확인
                if not self.farm_manager.check_network_connection():
                    network_error_count += 1
                    if network_error_count == 1:
                        self.log_signal.emit("⚠️ 네트워크 연결 끊김 - 재연결 대기 중...")
                        self.network_status_signal.emit(False)
                    elif network_error_count % 6 == 0:  # 30초마다 로그
                        self.log_signal.emit(f"⏳ 네트워크 재연결 시도 중... ({network_error_count * 5}초 경과)")
                    time.sleep(5)
                    continue

                # 네트워크 복구됨
                if network_error_count > 0:
                    self.log_signal.emit("✅ 네트워크 연결 복구됨")
                    self.network_status_signal.emit(True)
                    self.log_signal.emit("🔄 내 클레임 해제 및 마지막 작업 복구 시도...")

                    # 내 클레임 해제
                    self.farm_manager.release_my_claims()

                    # 마지막 작업 이어서 처리
                    last_job = self.farm_manager.get_last_job()
                    if last_job:
                        self.log_signal.emit(f"📥 마지막 작업 복구: {last_job.job_id}")
                        self.process_job(last_job)

                    network_error_count = 0

                # 만료된 클레임 정리
                self.farm_manager.cleanup_expired_claims()

                # 대기중인 작업 찾기
                jobs = self.farm_manager.get_pending_jobs()

                if jobs:
                    for job in jobs:
                        if not self.is_running:
                            break
                        self.farm_manager.last_job_id = job.job_id  # 마지막 작업 ID 저장
                        self.process_job(job)
                else:
                    time.sleep(5)  # 작업 없으면 5초 대기

            except (OSError, PermissionError) as e:
                # 네트워크 오류로 처리
                network_error_count += 1
                if network_error_count == 1:
                    self.log_signal.emit(f"⚠️ 네트워크 오류: {str(e)}")
                time.sleep(5)
            except Exception as e:
                self.log_signal.emit(f"❌ 오류: {str(e)}")
                time.sleep(5)

        self.log_signal.emit("=== 워커 종료 ===")

    def stop(self):
        """워커 종료"""
        self.is_running = False

    def process_job(self, job: RenderJob):
        """작업 처리"""
        # 현재 작업 통계 초기화
        self.current_job_stats = {"success": 0, "failed": 0, "retried": 0}

        self.log_signal.emit(f"\n작업 발견: {job.job_id}")
        self.log_signal.emit(f"  파일: {Path(job.clip_path).name}")
        self.log_signal.emit(f"  범위: {job.start_frame}-{job.end_frame}")

        # 워커 상태 및 현재 작업 정보 업데이트
        self.farm_manager.worker.status = "active"
        self.farm_manager.worker.current_job_id = job.job_id
        self.farm_manager.worker.current_clip_name = Path(job.clip_path).name
        self.farm_manager.worker.current_processed = 0
        self.farm_manager.update_worker()

        # 프레임 찾아서 처리
        tasks = []
        for _ in range(self.parallel_workers):
            if not self.is_running:
                break

            result = self.farm_manager.find_next_frame(job)
            if result:
                tasks.append(result)

        if not tasks:
            # 처리할 프레임이 없으면 idle로 변경
            self.farm_manager.worker.status = "idle"
            self.farm_manager.update_worker()
            return

        self.log_signal.emit(f"  {len(tasks)}개 프레임 처리 시작...")

        # 병렬 처리
        with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
            futures = {}
            retry_tasks = {}  # 재시도할 작업 추적

            for frame_idx, eye in tasks:
                future = executor.submit(self.process_frame, job, frame_idx, eye)
                futures[future] = (frame_idx, eye)
                retry_tasks[(frame_idx, eye)] = 0  # 재시도 카운트 초기화

            for future in as_completed(futures):
                if not self.is_running:
                    break

                frame_idx, eye = futures[future]
                success = future.result()

                if success:
                    self.farm_manager.mark_completed(job.job_id, frame_idx, eye)
                    self.farm_manager.worker.frames_completed += 1
                    self.farm_manager.worker.current_processed += 1
                    self.current_job_stats["success"] += 1
                    self.total_success += 1
                    self.total_processed += 1
                    self.farm_manager.update_worker()
                    self.log_signal.emit(f"  ✓ [{frame_idx}] {eye.upper()}")
                else:
                    # 재시도 로직
                    retry_count = retry_tasks[(frame_idx, eye)]
                    if retry_count < 2:  # 최대 2번 재시도
                        retry_tasks[(frame_idx, eye)] += 1
                        self.current_job_stats["retried"] += 1
                        self.log_signal.emit(f"  ⟳ [{frame_idx}] {eye.upper()} 재시도 ({retry_count + 1}/2)")
                        # 재시도 작업 제출
                        new_future = executor.submit(self.process_frame, job, frame_idx, eye)
                        futures[new_future] = (frame_idx, eye)
                    else:
                        # 최종 실패
                        self.farm_manager.release_claim(job.job_id, frame_idx, eye)
                        self.farm_manager.worker.total_errors += 1
                        self.current_job_stats["failed"] += 1
                        self.total_failed += 1
                        self.total_processed += 1
                        self.farm_manager.update_worker()
                        self.log_signal.emit(f"  ✗ [{frame_idx}] {eye.upper()} 최종 실패")

                # 진행률 업데이트
                progress = self.farm_manager.get_job_progress(job.job_id)
                total = job.get_total_tasks()
                self.progress_signal.emit(progress["completed"], total)

        # 작업 완료 후 통계 출력
        self.log_signal.emit(f"\n작업 처리 완료: {job.job_id}")
        self.log_signal.emit(f"  ✓ 성공: {self.current_job_stats['success']}")
        self.log_signal.emit(f"  ⟳ 재시도: {self.current_job_stats['retried']}")
        self.log_signal.emit(f"  ✗ 실패: {self.current_job_stats['failed']}")
        self.log_signal.emit(f"  전체 누적 - 성공: {self.total_success}, 실패: {self.total_failed}")

        # 작업 완료 후 워커 정보 초기화
        self.farm_manager.worker.status = "idle"
        self.farm_manager.worker.current_job_id = ""
        self.farm_manager.worker.current_clip_name = ""
        self.farm_manager.worker.current_processed = 0
        self.farm_manager.update_worker()

    def process_frame(self, job: RenderJob, frame_idx: int, eye: str) -> bool:
        """단일 프레임 처리"""
        clip = Path(job.clip_path)
        output_dir = Path(job.output_dir)
        clip_basename = clip.stem

        # 출력 파일 경로 생성
        ext = ".exr" if job.format == "exr" else ".ppm"
        frame_num = f"{frame_idx:06d}"

        if job.separate_folders:
            folder = "L" if eye == "left" else "R"
            (output_dir / folder).mkdir(parents=True, exist_ok=True)
            output_file = output_dir / folder / f"{clip_basename}_{frame_num}{ext}"
        else:
            suffix = "_L" if eye == "left" else "_R"
            output_file = output_dir / f"{clip_basename}{suffix}_{frame_num}{ext}"

        # CLI 실행
        cmd = [
            str(self.cli_path),
            str(clip),
            str(output_file),
            str(frame_idx),
            eye
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )

            return result.returncode == 0 and output_file.exists()

        except Exception as e:
            return False


class FarmUI(QMainWindow):
    """렌더팜 메인 UI"""

    def __init__(self):
        super().__init__()
        # 설정에서 farm_root 가져오기
        self.farm_manager = FarmManager(farm_root=settings.farm_root)
        self.worker_thread = None
        self.status_thread = None

        # CLI 경로 찾기 (여러 위치 시도)
        possible_paths = [
            Path(__file__).parent.parent.parent / "build" / "bin" / "braw_cli.exe",
            Path(__file__).parent.parent.parent / "build" / "src" / "app" / "Release" / "braw_cli.exe",
            Path(__file__).parent.parent / "build" / "bin" / "braw_cli.exe",  # 공유 폴더 build/bin
            Path(__file__).parent.parent / "braw_cli.exe",  # 공유 폴더 루트
            Path(__file__).parent.parent.parent / "braw_cli.exe",  # 상위 폴더
        ]

        self.cli_path = None
        for path in possible_paths:
            if path.exists():
                self.cli_path = path
                break

        if not self.cli_path:
            QMessageBox.critical(None, "오류",
                "braw_cli.exe를 찾을 수 없습니다.\n\n"
                "다음 위치 중 하나에 배치하세요:\n"
                "1. braw_batch_ui/braw_cli.exe\n"
                "2. P:/00-GIGA/BRAW_CLI/braw_cli.exe")
            sys.exit(1)

        self.init_ui()

        # 상태 업데이트 스레드 시작
        self.status_thread = StatusUpdateThread(self.farm_manager)
        self.status_thread.workers_signal.connect(self.update_workers_table)
        self.status_thread.jobs_signal.connect(self.update_jobs_table)
        self.status_thread.start()

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("BRAW Render Farm")
        self.setGeometry(100, 100, 1400, 900)

        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # 왼쪽 패널: 작업 제출 + 워커 제어
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.create_submit_section())
        left_layout.addWidget(self.create_worker_section())
        left_panel.setMaximumWidth(500)

        # 오른쪽 패널: 모니터링 + 로그
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(self.create_monitor_section())
        right_layout.addWidget(self.create_log_section())

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, stretch=1)

    def create_submit_section(self):
        """작업 제출 섹션"""
        widget = QGroupBox("📤 작업 제출")
        layout = QVBoxLayout(widget)

        # 파일 경로
        path_layout = QHBoxLayout()
        self.clip_input = QLineEdit()
        self.clip_input.setPlaceholderText("BRAW 파일 선택...")
        browse_btn = QPushButton("📁")
        browse_btn.setMaximumWidth(40)
        browse_btn.clicked.connect(self.browse_clip)
        path_layout.addWidget(QLabel("파일:"))
        path_layout.addWidget(self.clip_input)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 파일 정보
        self.file_info_label = QLabel("파일을 선택하면 정보가 표시됩니다")
        self.file_info_label.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        layout.addWidget(self.file_info_label)

        # 출력 폴더
        output_path_layout = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("출력 폴더 선택...")
        output_browse_btn = QPushButton("📁")
        output_browse_btn.setMaximumWidth(40)
        output_browse_btn.clicked.connect(self.browse_output)
        output_path_layout.addWidget(QLabel("출력:"))
        output_path_layout.addWidget(self.output_input)
        output_path_layout.addWidget(output_browse_btn)
        layout.addLayout(output_path_layout)

        # 프레임 범위
        frame_layout = QHBoxLayout()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 100000)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(0, 100000)
        self.end_spin.setValue(29)
        frame_layout.addWidget(QLabel("프레임:"))
        frame_layout.addWidget(self.start_spin)
        frame_layout.addWidget(QLabel("~"))
        frame_layout.addWidget(self.end_spin)
        layout.addLayout(frame_layout)

        # 옵션 - 한 줄로
        options_layout = QHBoxLayout()
        self.left_check = QCheckBox("L")
        self.left_check.setChecked(True)
        self.right_check = QCheckBox("R")
        self.right_check.setChecked(True)
        self.exr_radio = QRadioButton("EXR")
        self.exr_radio.setChecked(True)
        self.ppm_radio = QRadioButton("PPM")
        self.separate_check = QCheckBox("폴더분리")
        self.separate_check.setChecked(True)  # 폴더분리 기본값을 True로 설정
        options_layout.addWidget(self.left_check)
        options_layout.addWidget(self.right_check)
        options_layout.addWidget(QLabel("|"))
        options_layout.addWidget(self.exr_radio)
        options_layout.addWidget(self.ppm_radio)
        options_layout.addWidget(QLabel("|"))
        options_layout.addWidget(self.separate_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 제출 버튼
        submit_btn = QPushButton("✅ 작업 제출")
        submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
                color: white;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
                color: white;
            }
        """)
        submit_btn.clicked.connect(self.submit_job)
        layout.addWidget(submit_btn)

        return widget

    def create_worker_section(self):
        """워커 제어 섹션"""
        widget = QGroupBox("⚙️ 워커 제어")
        layout = QVBoxLayout(widget)

        # 워커 정보 - 컴팩트하게
        info_layout = QVBoxLayout()
        self.worker_id_label = QLabel(f"🖥️ {self.farm_manager.worker.worker_id} ({self.farm_manager.worker.ip})")
        self.worker_id_label.setStyleSheet("font-weight: bold;")
        self.network_status_label = QLabel("🟢 네트워크: 연결됨")
        self.network_status_label.setStyleSheet("color: green; font-weight: bold;")
        info_layout.addWidget(self.worker_id_label)
        info_layout.addWidget(self.network_status_label)
        layout.addLayout(info_layout)

        # 설정
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("병렬:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(settings.parallel_workers)  # 설정에서 기본값 가져오기
        settings_layout.addWidget(self.parallel_spin)
        settings_layout.addStretch()

        # 설정 버튼
        settings_btn = QPushButton("⚙️")
        settings_btn.setMaximumWidth(40)
        settings_btn.setToolTip("렌더팜 설정")
        settings_btn.clicked.connect(self.show_settings)
        settings_layout.addWidget(settings_btn)

        layout.addLayout(settings_layout)

        # 시작/중지 버튼
        btn_layout = QHBoxLayout()
        self.start_worker_btn = QPushButton("▶️ 시작")
        self.start_worker_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
                color: white;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
                color: white;
            }
        """)
        self.start_worker_btn.clicked.connect(self.start_worker)

        self.stop_worker_btn = QPushButton("⏹️ 중지")
        self.stop_worker_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
                color: white;
            }
            QPushButton:pressed {
                background-color: #c1160a;
                color: white;
            }
        """)
        self.stop_worker_btn.clicked.connect(self.stop_worker)
        self.stop_worker_btn.setEnabled(False)

        btn_layout.addWidget(self.start_worker_btn)
        btn_layout.addWidget(self.stop_worker_btn)
        layout.addLayout(btn_layout)

        # 진행률
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(20)
        layout.addWidget(self.progress_bar)

        return widget

    def create_monitor_section(self):
        """모니터링 섹션"""
        widget = QGroupBox("📊 실시간 모니터링")
        layout = QVBoxLayout(widget)

        # 활성 워커 목록
        self.workers_table = QTableWidget()
        self.workers_table.setColumnCount(8)
        self.workers_table.setHorizontalHeaderLabels(["워커 ID", "IP", "상태", "CPU", "작업 ID", "영상", "처리", "에러"])
        self.workers_table.setMaximumHeight(150)
        self.workers_table.verticalHeader().setVisible(False)
        layout.addWidget(QLabel("👷 활성 워커"))
        layout.addWidget(self.workers_table)

        # 작업 목록
        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(5)
        self.jobs_table.setHorizontalHeaderLabels(["작업 ID", "파일", "범위", "진행률", "제출자"])
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.jobs_table.customContextMenuRequested.connect(self.show_job_context_menu)
        layout.addWidget(QLabel("📋 작업 목록"))
        layout.addWidget(self.jobs_table)

        return widget

    def create_log_section(self):
        """로그 섹션"""
        widget = QGroupBox("📝 작업 로그")
        layout = QVBoxLayout(widget)

        self.worker_log = QTextEdit()
        self.worker_log.setReadOnly(True)
        self.worker_log.setFont(QFont("Consolas", 9))
        # 최대 높이 제한 제거하여 창에 맞춰 늘어나도록 함
        layout.addWidget(self.worker_log)

        return widget

    def browse_clip(self):
        """클립 파일 선택"""
        filename, _ = QFileDialog.getOpenFileName(self, "BRAW 파일 선택", "", "BRAW Files (*.braw)")
        if filename:
            self.clip_input.setText(filename)
            # 자동으로 정보 가져오기
            self.probe_clip()

    def probe_clip(self):
        """클립 정보 가져오기"""
        clip_path = self.clip_input.text()
        if not clip_path:
            QMessageBox.warning(self, "경고", "먼저 BRAW 파일을 선택하세요.")
            return

        try:
            # CLI로 정보 가져오기
            result = subprocess.run(
                [str(self.cli_path), clip_path, "--info"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )

            if result.returncode != 0:
                # SDK 에러인 경우 경고만 표시하고 계속 진행
                error_msg = result.stderr if result.stderr else result.stdout
                if "IBlackmagicRawFactory" in error_msg:
                    QMessageBox.warning(self, "경고",
                        "Blackmagic RAW SDK를 찾을 수 없습니다.\n"
                        "프레임 범위를 수동으로 설정하세요.\n\n"
                        "렌더팜 워커 PC에서는 SDK가 설치되어 있어야 합니다.")
                    self.file_info_label.setText("⚠️ SDK 없음 - 수동 설정 필요")
                    self.file_info_label.setStyleSheet("color: orange;")
                else:
                    QMessageBox.warning(self, "오류", f"파일 정보를 가져올 수 없습니다.\n{error_msg}")
                return

            # 출력 파싱
            info = {}
            for line in result.stdout.splitlines():
                if "=" in line and not line.startswith("[DEBUG]"):
                    key, value = line.strip().split("=", 1)
                    info[key] = value

            # UI 업데이트
            if "FRAME_COUNT" in info:
                frame_count = int(info["FRAME_COUNT"])
                self.end_spin.setValue(frame_count - 1)  # 0-based index

                # 정보 표시
                width = info.get("WIDTH", "?")
                height = info.get("HEIGHT", "?")
                fps = info.get("FRAME_RATE", "?")
                stereo = "스테레오" if info.get("STEREO") == "true" else "모노"

                info_text = f"📹 {width}x{height} @ {fps}fps | 프레임: {frame_count} | {stereo}"
                self.file_info_label.setText(info_text)
                self.file_info_label.setStyleSheet("color: green; font-weight: bold;")

                # 스테레오가 아니면 Right 체크 해제
                if info.get("STEREO") != "true":
                    self.right_check.setChecked(False)
                    self.right_check.setEnabled(False)
                else:
                    self.right_check.setEnabled(True)

            else:
                QMessageBox.warning(self, "오류", "파일 정보를 파싱할 수 없습니다.")

        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "오류", "정보 가져오기 시간 초과")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"오류 발생: {e}")

    def browse_output(self):
        """출력 폴더 선택"""
        directory = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if directory:
            self.output_input.setText(directory)

    def submit_job(self):
        """작업 제출"""
        clip_path = self.clip_input.text()
        output_dir = self.output_input.text()

        if not clip_path or not output_dir:
            QMessageBox.warning(self, "경고", "파일과 출력 폴더를 선택하세요.")
            return

        # 작업 생성
        job = RenderJob(f"job_{int(time.time())}")
        job.clip_path = clip_path
        job.output_dir = output_dir
        job.start_frame = self.start_spin.value()
        job.end_frame = self.end_spin.value()

        eyes = []
        if self.left_check.isChecked():
            eyes.append("left")
        if self.right_check.isChecked():
            eyes.append("right")
        job.eyes = eyes

        job.format = "exr" if self.exr_radio.isChecked() else "ppm"
        job.separate_folders = self.separate_check.isChecked()

        # 제출
        self.farm_manager.submit_job(job)

        QMessageBox.information(self, "성공", f"작업이 제출되었습니다.\n작업 ID: {job.job_id}")

    def start_worker(self):
        """워커 시작"""
        self.farm_manager.start()

        parallel = self.parallel_spin.value()
        self.worker_thread = WorkerThread(self.farm_manager, self.cli_path, parallel)
        self.worker_thread.log_signal.connect(self.append_worker_log)
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.network_status_signal.connect(self.update_network_status)
        self.worker_thread.start()

        self.start_worker_btn.setEnabled(False)
        self.stop_worker_btn.setEnabled(True)

    def stop_worker(self):
        """워커 중지"""
        if self.worker_thread:
            self.worker_thread.stop()
            self.worker_thread.wait()

        self.farm_manager.stop()

        self.start_worker_btn.setEnabled(True)
        self.stop_worker_btn.setEnabled(False)

    def show_settings(self):
        """설정 다이얼로그 표시"""
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # 설정이 변경되었으므로 병렬 처리 수 업데이트
            self.parallel_spin.setValue(settings.parallel_workers)
            # farm_root가 변경된 경우 알림
            QMessageBox.information(
                self,
                "설정 저장됨",
                f"설정이 저장되었습니다.\n공용 저장소: {settings.farm_root}\n병렬 처리: {settings.parallel_workers}"
            )

    def append_worker_log(self, text):
        """워커 로그 추가"""
        self.worker_log.append(text)

    def update_progress(self, completed, total):
        """진행률 업데이트"""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)

    def update_network_status(self, connected):
        """네트워크 상태 업데이트"""
        if connected:
            self.network_status_label.setText("🟢 네트워크: 연결됨")
            self.network_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.network_status_label.setText("🔴 네트워크: 끊김 (재연결 중...)")
            self.network_status_label.setStyleSheet("color: red; font-weight: bold;")

    def update_workers_table(self, workers):
        """워커 테이블 업데이트"""
        self.workers_table.setRowCount(len(workers))
        for i, worker in enumerate(workers):
            self.workers_table.setItem(i, 0, QTableWidgetItem(worker.worker_id))
            self.workers_table.setItem(i, 1, QTableWidgetItem(worker.ip))

            # 상태에 따라 색상 및 아이콘 변경
            status_item = QTableWidgetItem(worker.status)
            if worker.status == "active":
                status_item.setText("🔄 작업중")
                status_item.setForeground(QColor(76, 175, 80))  # 녹색
            else:
                status_item.setText("⏸️ 대기중")
                status_item.setForeground(QColor(158, 158, 158))  # 회색
            self.workers_table.setItem(i, 2, status_item)

            # CPU 사용률
            cpu_item = QTableWidgetItem(f"{worker.cpu_usage:.1f}%")
            if worker.cpu_usage > 80:
                cpu_item.setForeground(QColor(244, 67, 54))  # 빨간색
            elif worker.cpu_usage > 50:
                cpu_item.setForeground(QColor(255, 152, 0))  # 주황색
            else:
                cpu_item.setForeground(QColor(76, 175, 80))  # 녹색
            self.workers_table.setItem(i, 3, cpu_item)

            # 현재 작업 ID
            job_id_item = QTableWidgetItem(worker.current_job_id if worker.current_job_id else "-")
            if worker.current_job_id:
                job_id_item.setForeground(QColor(33, 150, 243))  # 파란색
            self.workers_table.setItem(i, 4, job_id_item)

            # 영상 이름
            self.workers_table.setItem(i, 5, QTableWidgetItem(worker.current_clip_name if worker.current_clip_name else "-"))

            # 처리 프레임 수
            processed_item = QTableWidgetItem(str(worker.current_processed) if worker.current_processed > 0 else "-")
            if worker.current_processed > 0:
                processed_item.setForeground(QColor(76, 175, 80))  # 녹색
            self.workers_table.setItem(i, 6, processed_item)

            # 에러 수
            error_item = QTableWidgetItem(str(worker.total_errors) if worker.total_errors > 0 else "0")
            if worker.total_errors > 0:
                error_item.setForeground(QColor(244, 67, 54))  # 빨간색
            else:
                error_item.setForeground(QColor(76, 175, 80))  # 녹색
            self.workers_table.setItem(i, 7, error_item)

    def update_jobs_table(self, jobs):
        """작업 목록 테이블 업데이트"""
        self.jobs_table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            try:
                progress = self.farm_manager.get_job_progress(job.job_id)
                total = job.get_total_tasks()
                completed = progress['completed']
                progress_percent = (completed / total * 100) if total > 0 else 0

                # 작업 ID - 진행 상태에 따라 색상 변경
                job_id_item = QTableWidgetItem(job.job_id)
                if completed == 0:
                    # 대기중 - 파란색
                    job_id_item.setForeground(QColor(33, 150, 243))
                elif completed < total:
                    # 진행중 - 주황색
                    job_id_item.setForeground(QColor(255, 152, 0))
                else:
                    # 완료 - 녹색
                    job_id_item.setForeground(QColor(76, 175, 80))
                self.jobs_table.setItem(i, 0, job_id_item)

                # 파일명
                self.jobs_table.setItem(i, 1, QTableWidgetItem(Path(job.clip_path).name))

                # 범위
                self.jobs_table.setItem(i, 2, QTableWidgetItem(f"{job.start_frame}-{job.end_frame}"))

                # 진행률 - 퍼센트와 프레임 수
                progress_text = f"{progress_percent:.1f}% ({completed}/{total})"
                progress_item = QTableWidgetItem(progress_text)
                if completed == 0:
                    progress_item.setForeground(QColor(158, 158, 158))  # 회색
                elif completed < total:
                    progress_item.setForeground(QColor(255, 152, 0))  # 주황색
                else:
                    progress_item.setForeground(QColor(76, 175, 80))  # 녹색
                self.jobs_table.setItem(i, 3, progress_item)

                # 제출자
                self.jobs_table.setItem(i, 4, QTableWidgetItem(job.created_by))
            except:
                pass

    def show_job_context_menu(self, position):
        """작업 목록 컨텍스트 메뉴 표시"""
        # 선택된 행 확인
        row = self.jobs_table.rowAt(position.y())
        if row < 0:
            return

        # 작업 ID 가져오기
        job_id_item = self.jobs_table.item(row, 0)
        if not job_id_item:
            return

        job_id = job_id_item.text()

        # 컨텍스트 메뉴 생성
        menu = QMenu(self)

        # 출력 폴더 열기 액션
        open_folder_action = QAction("📁 출력 폴더 열기", self)
        open_folder_action.triggered.connect(lambda: self.open_output_folder(job_id))
        menu.addAction(open_folder_action)

        menu.addSeparator()

        # 리셋 액션
        reset_action = QAction("🔄 작업 리셋 (진행 상태 초기화)", self)
        reset_action.triggered.connect(lambda: self.reset_job(job_id))
        menu.addAction(reset_action)

        # 완료 표시 액션
        complete_action = QAction("✅ 완료로 표시", self)
        complete_action.triggered.connect(lambda: self.mark_job_complete(job_id))
        menu.addAction(complete_action)

        menu.addSeparator()

        # 삭제 액션
        delete_action = QAction("🗑️ 작업 삭제", self)
        delete_action.triggered.connect(lambda: self.delete_job(job_id))
        menu.addAction(delete_action)

        # 메뉴 표시
        menu.exec(self.jobs_table.viewport().mapToGlobal(position))

    def reset_job(self, job_id: str):
        """작업 리셋"""
        reply = QMessageBox.question(
            self, "작업 리셋",
            f"작업 '{job_id}'의 진행 상태를 초기화하시겠습니까?\n"
            "모든 완료 및 클레임 정보가 삭제되고 처음부터 다시 시작됩니다.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.farm_manager.reset_job(job_id)
            QMessageBox.information(self, "완료", f"작업 '{job_id}'이(가) 리셋되었습니다.")

    def mark_job_complete(self, job_id: str):
        """작업을 완료로 표시"""
        reply = QMessageBox.question(
            self, "완료로 표시",
            f"작업 '{job_id}'을(를) 완료로 표시하시겠습니까?\n"
            "모든 프레임이 완료된 것으로 처리됩니다.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.farm_manager.mark_job_completed(job_id)
            QMessageBox.information(self, "완료", f"작업 '{job_id}'이(가) 완료로 표시되었습니다.")

    def delete_job(self, job_id: str):
        """작업 삭제"""
        reply = QMessageBox.question(
            self, "작업 삭제",
            f"작업 '{job_id}'을(를) 삭제하시겠습니까?\n"
            "작업 정보, 클레임, 완료 정보가 모두 삭제됩니다.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.farm_manager.delete_job(job_id)
            QMessageBox.information(self, "완료", f"작업 '{job_id}'이(가) 삭제되었습니다.")

    def open_output_folder(self, job_id: str):
        """작업의 출력 폴더 열기"""
        try:
            # 작업 정보 가져오기
            job_file = self.farm_manager.config.jobs_dir / f"{job_id}.json"
            if not job_file.exists():
                QMessageBox.warning(self, "오류", "작업 정보를 찾을 수 없습니다.")
                return

            with open(job_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                job = RenderJob.from_dict(data)

            # 출력 폴더 열기
            output_path = Path(job.output_dir)
            if output_path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path)))
            else:
                QMessageBox.warning(self, "경고", f"출력 폴더가 존재하지 않습니다:\n{output_path}")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"폴더를 열 수 없습니다:\n{str(e)}")

    def closeEvent(self, event):
        """창 닫기 이벤트"""
        if self.status_thread:
            self.status_thread.stop()
            self.status_thread.wait()
        if self.worker_thread:
            self.worker_thread.stop()
            self.worker_thread.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = FarmUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
