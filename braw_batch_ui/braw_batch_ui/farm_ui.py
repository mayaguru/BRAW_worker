#!/usr/bin/env python3
"""
BRAW Render Farm UI (PySide6)
분산 렌더링 시스템 UI
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QTextEdit, QGroupBox, QRadioButton, QCheckBox,
                               QFileDialog, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QProgressBar, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor

from farm_core import FarmManager, RenderJob, WorkerInfo


class WorkerThread(QThread):
    """워커 스레드 (폴더 감시 + 자동 처리)"""
    log_signal = Signal(str)
    progress_signal = Signal(int, int)  # completed, total

    def __init__(self, farm_manager, cli_path, parallel_workers=10):
        super().__init__()
        self.farm_manager = farm_manager
        self.cli_path = Path(cli_path)
        self.parallel_workers = parallel_workers
        self.is_running = False

    def run(self):
        """워커 메인 루프"""
        self.is_running = True
        self.log_signal.emit("=== 워커 시작 ===")
        self.log_signal.emit(f"워커 ID: {self.farm_manager.worker.worker_id}")
        self.log_signal.emit(f"병렬 처리: {self.parallel_workers}")
        self.log_signal.emit("")

        while self.is_running:
            try:
                # 만료된 클레임 정리
                self.farm_manager.cleanup_expired_claims()

                # 대기중인 작업 찾기
                jobs = self.farm_manager.get_pending_jobs()

                if jobs:
                    for job in jobs:
                        if not self.is_running:
                            break
                        self.process_job(job)
                else:
                    time.sleep(5)  # 작업 없으면 5초 대기

            except Exception as e:
                self.log_signal.emit(f"오류: {str(e)}")
                time.sleep(5)

        self.log_signal.emit("=== 워커 종료 ===")

    def stop(self):
        """워커 종료"""
        self.is_running = False

    def process_job(self, job: RenderJob):
        """작업 처리"""
        self.log_signal.emit(f"\n작업 발견: {job.job_id}")
        self.log_signal.emit(f"  파일: {Path(job.clip_path).name}")
        self.log_signal.emit(f"  범위: {job.start_frame}-{job.end_frame}")

        # 프레임 찾아서 처리
        tasks = []
        for _ in range(self.parallel_workers):
            if not self.is_running:
                break

            result = self.farm_manager.find_next_frame(job)
            if result:
                tasks.append(result)

        if not tasks:
            return

        self.log_signal.emit(f"  {len(tasks)}개 프레임 처리 시작...")

        # 병렬 처리
        with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
            futures = {}
            for frame_idx, eye in tasks:
                future = executor.submit(self.process_frame, job, frame_idx, eye)
                futures[future] = (frame_idx, eye)

            for future in as_completed(futures):
                if not self.is_running:
                    break

                frame_idx, eye = futures[future]
                success = future.result()

                if success:
                    self.farm_manager.mark_completed(job.job_id, frame_idx, eye)
                    self.farm_manager.worker.frames_completed += 1
                    self.log_signal.emit(f"  ✓ [{frame_idx}] {eye.upper()}")
                else:
                    self.farm_manager.release_claim(job.job_id, frame_idx, eye)
                    self.log_signal.emit(f"  ✗ [{frame_idx}] {eye.upper()} 실패")

                # 진행률 업데이트
                progress = self.farm_manager.get_job_progress(job.job_id)
                total = job.get_total_tasks()
                self.progress_signal.emit(progress["completed"], total)

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
        self.farm_manager = FarmManager()
        self.worker_thread = None

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

        # 타이머 (상태 업데이트용)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)  # 1초마다

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("BRAW Render Farm")
        self.setGeometry(100, 100, 1000, 700)

        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 탭
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # 탭 1: 작업 제출
        tabs.addTab(self.create_submit_tab(), "작업 제출")

        # 탭 2: 워커 모드
        tabs.addTab(self.create_worker_tab(), "워커")

        # 탭 3: 모니터링
        tabs.addTab(self.create_monitor_tab(), "모니터링")

    def create_submit_tab(self):
        """작업 제출 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 파일 선택
        file_group = QGroupBox("BRAW 파일")
        file_layout = QVBoxLayout()

        # 파일 경로
        path_layout = QHBoxLayout()
        self.clip_input = QLineEdit()
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self.browse_clip)
        path_layout.addWidget(QLabel("클립:"))
        path_layout.addWidget(self.clip_input)
        path_layout.addWidget(browse_btn)
        file_layout.addLayout(path_layout)

        # 파일 정보
        info_layout = QHBoxLayout()
        self.file_info_label = QLabel("파일을 선택하면 정보가 표시됩니다")
        self.file_info_label.setStyleSheet("color: gray; font-style: italic; padding: 5px;")
        self.file_info_label.setMinimumHeight(30)
        probe_btn = QPushButton("정보 가져오기")
        probe_btn.setMaximumWidth(120)
        probe_btn.clicked.connect(self.probe_clip)
        info_layout.addWidget(self.file_info_label, 1)  # stretch factor 1
        info_layout.addWidget(probe_btn)
        file_layout.addLayout(info_layout)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # 출력 폴더
        output_group = QGroupBox("출력")
        output_layout = QVBoxLayout()

        output_path_layout = QHBoxLayout()
        self.output_input = QLineEdit()
        output_browse_btn = QPushButton("찾아보기")
        output_browse_btn.clicked.connect(self.browse_output)
        output_path_layout.addWidget(QLabel("폴더:"))
        output_path_layout.addWidget(self.output_input)
        output_path_layout.addWidget(output_browse_btn)
        output_layout.addLayout(output_path_layout)

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
        frame_layout.addStretch()
        output_layout.addLayout(frame_layout)

        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # 옵션
        options_group = QGroupBox("옵션")
        options_layout = QVBoxLayout()

        # 눈 선택
        eye_layout = QHBoxLayout()
        self.left_check = QCheckBox("왼쪽 (L)")
        self.left_check.setChecked(True)
        self.right_check = QCheckBox("오른쪽 (R)")
        self.right_check.setChecked(True)
        eye_layout.addWidget(QLabel("스테레오:"))
        eye_layout.addWidget(self.left_check)
        eye_layout.addWidget(self.right_check)
        eye_layout.addStretch()
        options_layout.addLayout(eye_layout)

        # 포맷
        format_layout = QHBoxLayout()
        self.exr_radio = QRadioButton("EXR (Half/DWAA)")
        self.exr_radio.setChecked(True)
        self.ppm_radio = QRadioButton("PPM")
        format_layout.addWidget(QLabel("포맷:"))
        format_layout.addWidget(self.exr_radio)
        format_layout.addWidget(self.ppm_radio)
        format_layout.addStretch()
        options_layout.addLayout(format_layout)

        # L/R 폴더 분리
        self.separate_check = QCheckBox("L/R 폴더 분리")
        options_layout.addWidget(self.separate_check)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # 제출 버튼
        submit_btn = QPushButton("작업 제출")
        submit_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 10px; font-size: 14px; }")
        submit_btn.clicked.connect(self.submit_job)
        layout.addWidget(submit_btn)

        layout.addStretch()
        return widget

    def create_worker_tab(self):
        """워커 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 워커 정보
        info_group = QGroupBox("워커 정보")
        info_layout = QVBoxLayout()
        self.worker_id_label = QLabel(f"워커 ID: {self.farm_manager.worker.worker_id}")
        self.worker_ip_label = QLabel(f"IP: {self.farm_manager.worker.ip}")
        info_layout.addWidget(self.worker_id_label)
        info_layout.addWidget(self.worker_ip_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # 설정
        settings_group = QGroupBox("워커 설정")
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("병렬 작업 수:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(10)
        settings_layout.addWidget(self.parallel_spin)
        settings_layout.addStretch()
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # 시작/중지 버튼
        btn_layout = QHBoxLayout()
        self.start_worker_btn = QPushButton("워커 시작")
        self.start_worker_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 10px; }")
        self.start_worker_btn.clicked.connect(self.start_worker)

        self.stop_worker_btn = QPushButton("워커 중지")
        self.stop_worker_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; padding: 10px; }")
        self.stop_worker_btn.clicked.connect(self.stop_worker)
        self.stop_worker_btn.setEnabled(False)

        btn_layout.addWidget(self.start_worker_btn)
        btn_layout.addWidget(self.stop_worker_btn)
        layout.addLayout(btn_layout)

        # 진행률
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # 로그
        log_group = QGroupBox("작업 로그")
        log_layout = QVBoxLayout()
        self.worker_log = QTextEdit()
        self.worker_log.setReadOnly(True)
        self.worker_log.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.worker_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        return widget

    def create_monitor_tab(self):
        """모니터링 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 활성 워커 목록
        workers_group = QGroupBox("활성 워커")
        workers_layout = QVBoxLayout()
        self.workers_table = QTableWidget()
        self.workers_table.setColumnCount(4)
        self.workers_table.setHorizontalHeaderLabels(["워커 ID", "IP", "상태", "완료 프레임"])
        workers_layout.addWidget(self.workers_table)
        workers_group.setLayout(workers_layout)
        layout.addWidget(workers_group)

        # 작업 목록
        jobs_group = QGroupBox("대기 작업")
        jobs_layout = QVBoxLayout()
        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(5)
        self.jobs_table.setHorizontalHeaderLabels(["작업 ID", "파일", "범위", "진행률", "제출자"])
        jobs_layout.addWidget(self.jobs_table)
        jobs_group.setLayout(jobs_layout)
        layout.addWidget(jobs_group)

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

    def append_worker_log(self, text):
        """워커 로그 추가"""
        self.worker_log.append(text)

    def update_progress(self, completed, total):
        """진행률 업데이트"""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)

    def update_status(self):
        """상태 업데이트 (1초마다)"""
        # 활성 워커 업데이트
        workers = self.farm_manager.get_active_workers()
        self.workers_table.setRowCount(len(workers))
        for i, worker in enumerate(workers):
            self.workers_table.setItem(i, 0, QTableWidgetItem(worker.worker_id))
            self.workers_table.setItem(i, 1, QTableWidgetItem(worker.ip))
            self.workers_table.setItem(i, 2, QTableWidgetItem(worker.status))
            self.workers_table.setItem(i, 3, QTableWidgetItem(str(worker.frames_completed)))

        # 작업 목록 업데이트
        jobs = self.farm_manager.get_pending_jobs()
        self.jobs_table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            progress = self.farm_manager.get_job_progress(job.job_id)
            total = job.get_total_tasks()
            progress_text = f"{progress['completed']}/{total}"

            self.jobs_table.setItem(i, 0, QTableWidgetItem(job.job_id))
            self.jobs_table.setItem(i, 1, QTableWidgetItem(Path(job.clip_path).name))
            self.jobs_table.setItem(i, 2, QTableWidgetItem(f"{job.start_frame}-{job.end_frame}"))
            self.jobs_table.setItem(i, 3, QTableWidgetItem(progress_text))
            self.jobs_table.setItem(i, 4, QTableWidgetItem(job.created_by))


def main():
    app = QApplication(sys.argv)
    window = FarmUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
