#!/usr/bin/env python3
"""
BRAW-Brew UI V2 (PySide6)
SQLite DB 기반 분산 렌더링 시스템 - Pool 지원
"""

import sys
import subprocess
import platform
import re
from typing import Optional, List, Tuple

SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
import json
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QTextEdit, QGroupBox, QRadioButton, QCheckBox,
                               QFileDialog, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QProgressBar, QMessageBox, QMenu, QDialog,
                               QListWidget, QListWidgetItem, QComboBox, QInputDialog,
                               QHeaderView, QAbstractItemView, QScrollBar, QSplitter,
                               QFormLayout, QDialogButtonBox)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QUrl, QSettings
from PySide6.QtGui import QFont, QColor, QAction, QDesktopServices, QIcon

from .farm_core_v2 import FarmManagerV2, create_farm_manager
from .farm_db import Pool, Job, Worker, JobStatus
from .config import (
    settings,
    SUBPROCESS_TIMEOUT_DEFAULT_SEC,
    SUBPROCESS_TIMEOUT_ACES_SEC,
    CLIP_INFO_TIMEOUT_SEC,
    LOG_MAX_LINES,
    BATCH_CLAIM_TIMEOUT_SEC,
    FRAME_BASE_TIMEOUT_SEC,
    FRAME_PER_FRAME_TIMEOUT_SEC,
    FRAME_SBS_MULTIPLIER,
)


class SettingsDialog(QDialog):
    """설정 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("렌더팜 설정")
        self.setMinimumWidth(550)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 공용 저장소 경로
        farm_root_layout = QHBoxLayout()
        farm_root_layout.addWidget(QLabel("공용 저장소:"))
        self.farm_root_input = QLineEdit(settings.farm_root)
        browse_btn = QPushButton("...")
        browse_btn.setMaximumWidth(40)
        browse_btn.clicked.connect(self.browse_farm_root)
        farm_root_layout.addWidget(self.farm_root_input)
        farm_root_layout.addWidget(browse_btn)
        layout.addLayout(farm_root_layout)

        # CLI 실행 파일 경로
        cli_path_layout = QHBoxLayout()
        cli_path_layout.addWidget(QLabel("CLI 실행 파일:"))
        self.cli_path_input = QLineEdit(settings.cli_path)
        cli_browse_btn = QPushButton("...")
        cli_browse_btn.setMaximumWidth(40)
        cli_browse_btn.clicked.connect(self.browse_cli_path)
        cli_path_layout.addWidget(self.cli_path_input)
        cli_path_layout.addWidget(cli_browse_btn)
        layout.addLayout(cli_path_layout)

        # OCIO config 경로
        ocio_layout = QHBoxLayout()
        ocio_layout.addWidget(QLabel("OCIO Config:"))
        self.ocio_input = QLineEdit(settings.ocio_config_path)
        ocio_browse_btn = QPushButton("...")
        ocio_browse_btn.setMaximumWidth(40)
        ocio_browse_btn.clicked.connect(self.browse_ocio)
        ocio_layout.addWidget(self.ocio_input)
        ocio_layout.addWidget(ocio_browse_btn)
        layout.addLayout(ocio_layout)

        # 색공간 설정
        color_group = QGroupBox("색공간 설정")
        color_layout = QFormLayout(color_group)
        self.input_cs_input = QLineEdit(settings.color_input_space)
        self.output_cs_input = QLineEdit(settings.color_output_space)
        color_layout.addRow("입력 색공간:", self.input_cs_input)
        color_layout.addRow("출력 색공간:", self.output_cs_input)
        layout.addWidget(color_group)

        # 처리 설정
        process_group = QGroupBox("처리 설정")
        process_layout = QFormLayout(process_group)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 64)
        self.parallel_spin.setValue(settings.parallel_workers)
        self.parallel_spin.setToolTip("동시 실행할 워커 스레드 수")
        process_layout.addRow("병렬 처리:", self.parallel_spin)

        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 100)
        self.batch_spin.setValue(settings.batch_frame_size)
        self.batch_spin.setToolTip("한 번에 처리할 프레임 수")
        process_layout.addRow("연속 처리:", self.batch_spin)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 20)
        self.retry_spin.setValue(settings.max_retries)
        self.retry_spin.setToolTip("프레임 처리 실패 시 재시도 횟수")
        process_layout.addRow("최대 재시도:", self.retry_spin)

        layout.addWidget(process_group)

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
        folder = QFileDialog.getExistingDirectory(self, "공용 저장소 선택")
        if folder:
            self.farm_root_input.setText(folder)

    def browse_cli_path(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "CLI 실행 파일 선택", "", "실행 파일 (*.exe);;모든 파일 (*.*)")
        if file_path:
            self.cli_path_input.setText(file_path)

    def browse_ocio(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "OCIO Config 선택", "", "OCIO Config (*.ocio);;모든 파일 (*.*)")
        if file_path:
            self.ocio_input.setText(file_path)

    def save_settings(self):
        settings.farm_root = self.farm_root_input.text()
        settings.cli_path = self.cli_path_input.text()
        settings.ocio_config_path = self.ocio_input.text()
        settings.color_input_space = self.input_cs_input.text()
        settings.color_output_space = self.output_cs_input.text()
        settings.parallel_workers = self.parallel_spin.value()
        settings.batch_frame_size = self.batch_spin.value()
        settings.max_retries = self.retry_spin.value()
        settings.save()
        self.accept()


class PoolDialog(QDialog):
    """풀 관리 다이얼로그"""

    def __init__(self, farm_manager: FarmManagerV2, parent=None):
        super().__init__(parent)
        self.farm_manager = farm_manager
        self.parent_window = parent  # FarmUIV2 참조 저장
        self.setWindowTitle("풀 관리")
        self.setMinimumSize(500, 400)
        self.init_ui()
        self.load_pools()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 풀 목록
        self.pool_list = QListWidget()
        self.pool_list.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(QLabel("작업 풀 목록:"))
        layout.addWidget(self.pool_list)

        # 버튼들
        btn_layout = QHBoxLayout()

        self.add_btn = QPushButton("➕ 추가")
        self.add_btn.clicked.connect(self.add_pool)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ 수정")
        self.edit_btn.clicked.connect(self.edit_pool)
        self.edit_btn.setEnabled(False)
        btn_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("🗑️ 삭제")
        self.delete_btn.clicked.connect(self.delete_pool)
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def load_pools(self):
        """풀 목록 로드"""
        self.pool_list.clear()
        pools = self.farm_manager.get_pools()
        for pool in pools:
            stats = self.farm_manager.get_pool_stats(pool.pool_id)
            workers_active = stats['workers']['active']
            workers_total = stats['workers']['total']
            jobs_pending = stats['jobs'].get('pending', 0) + stats['jobs'].get('in_progress', 0)

            item = QListWidgetItem(
                f"{pool.name} [{pool.pool_id}] - 워커: {workers_active}/{workers_total}, 작업: {jobs_pending}"
            )
            item.setData(Qt.UserRole, pool.pool_id)
            if pool.pool_id == 'default':
                item.setForeground(QColor("#4db8c4"))
            self.pool_list.addItem(item)

    def on_selection_changed(self):
        """선택 변경"""
        selected = self.pool_list.currentItem()
        if selected:
            pool_id = selected.data(Qt.UserRole)
            # default 풀은 삭제 불가
            self.delete_btn.setEnabled(pool_id != 'default')
            self.edit_btn.setEnabled(True)
        else:
            self.delete_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)

    def add_pool(self):
        """풀 추가"""
        dialog = PoolEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            pool_id = dialog.pool_id_input.text().strip()
            name = dialog.name_input.text().strip()
            desc = dialog.desc_input.text().strip()
            priority = dialog.priority_spin.value()

            if pool_id and name:
                if self.farm_manager.create_pool(pool_id, name, desc, priority):
                    self.load_pools()
                else:
                    QMessageBox.warning(self, "풀 생성 실패", "풀 생성에 실패했습니다. (ID 중복?)")

    def edit_pool(self):
        """풀 수정 (TODO)"""
        QMessageBox.information(self, "알림", "풀 수정은 아직 구현되지 않았습니다.")

    def delete_pool(self):
        """풀 삭제"""
        selected = self.pool_list.currentItem()
        if not selected:
            return

        pool_id = selected.data(Qt.UserRole)
        if pool_id == 'default':
            QMessageBox.warning(self, "삭제 불가", "기본 풀은 삭제할 수 없습니다.")
            return

        # 확인 없이 바로 삭제
        self.farm_manager.delete_pool(pool_id)
        self.load_pools()


class PoolEditDialog(QDialog):
    """풀 생성/수정 다이얼로그"""

    def __init__(self, parent=None, pool: Pool = None):
        super().__init__(parent)
        self.setWindowTitle("풀 추가" if pool is None else "풀 수정")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self.pool_id_input = QLineEdit()
        self.pool_id_input.setPlaceholderText("영문, 숫자, 언더스코어만")
        layout.addRow("풀 ID:", self.pool_id_input)

        self.name_input = QLineEdit()
        layout.addRow("이름:", self.name_input)

        self.desc_input = QLineEdit()
        layout.addRow("설명:", self.desc_input)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 100)
        self.priority_spin.setValue(50)
        layout.addRow("우선순위:", self.priority_spin)

        if pool:
            self.pool_id_input.setText(pool.pool_id)
            self.pool_id_input.setEnabled(False)
            self.name_input.setText(pool.name)
            self.desc_input.setText(pool.description)
            self.priority_spin.setValue(pool.priority)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class WorkerThreadV2(QThread):
    """워커 스레드 V2 - DB 기반"""

    log_signal = Signal(str)
    progress_signal = Signal(int, int)  # completed, total
    job_completed_signal = Signal(str)  # job_id - 작업 완료 시 시그널

    def __init__(self, farm_manager: FarmManagerV2, cli_path: Path,
                 parallel_workers: int = 10, watchdog_mode: bool = True):
        super().__init__()
        self.farm_manager = farm_manager
        self.cli_path = cli_path
        self.parallel_workers = parallel_workers
        self.watchdog_mode = watchdog_mode
        self.is_running = False

        # 통계
        self.total_processed = 0
        self.total_success = 0
        self.total_failed = 0


    def get_pending_frame_count(self) -> int:
        """대기 중인 프레임 수 조회"""
        try:
            return self.farm_manager.db.get_pending_frame_count(self.farm_manager.current_pool_id)
        except Exception:
            return 9999  # 오류시 기본값 (제한 없음)

    def run(self):
        """워커 실행 - 병렬 처리"""
        self.is_running = True
        self.farm_manager.start()

        self.log_signal.emit("=== 워커 V2 시작 ===")
        self.log_signal.emit(f"워커 ID: {self.farm_manager.worker_id}")
        self.log_signal.emit(f"풀: {self.farm_manager.current_pool_id}")
        self.log_signal.emit(f"병렬 처리: {self.parallel_workers}")
        self.log_signal.emit("")

        idle_logged = False

        with ThreadPoolExecutor(max_workers=self.parallel_workers) as executor:
            futures = {}

            while self.is_running:
                try:
                    # 오프라인 워커 정리 (가끔만)
                    if len(futures) == 0:
                        self.farm_manager.cleanup_offline_workers()

                    # 남은 프레임 수에 따라 동적 병렬 수 조절
                    pending_frames = self.get_pending_frame_count()
                    batch_size = settings.batch_frame_size

                    # 남은 프레임이 적으면 병렬 수 제한
                    # 예: 120프레임 남음, batch=10 -> 최대 12개 병렬
                    # 예: 30프레임 남음, batch=10 -> 최대 3개 병렬
                    if pending_frames > 0:
                        max_effective_workers = max(1, (pending_frames + batch_size - 1) // batch_size)
                        effective_workers = min(self.parallel_workers, max_effective_workers)
                    else:
                        effective_workers = self.parallel_workers

                    # 빈 슬롯만큼 작업 클레임
                    while len(futures) < effective_workers and self.is_running:
                        claimed = self.farm_manager.claim_frames(batch_size)

                        if claimed:
                            idle_logged = False
                            job_id, start_frame, end_frame, eye = claimed

                            job = self.farm_manager.get_job(job_id)
                            if not job:
                                continue

                            self.log_signal.emit(f"🚀 시작: {job_id} [{start_frame}-{end_frame}] ({eye.upper()})")

                            # 하트비트 업데이트
                            self.farm_manager.update_heartbeat("active", job_id, self.total_success)

                            # 병렬 실행 제출
                            future = executor.submit(
                                self.process_frame_range, job, start_frame, end_frame, eye
                            )
                            futures[future] = (job_id, start_frame, end_frame, eye, job)
                        else:
                            break

                    # 주기적 하트비트 업데이트 (작업 중에도)
                    if futures:
                        self.farm_manager.update_heartbeat("active", None, self.total_success)

                    # 완료된 작업 처리
                    if futures:
                        done_futures = [f for f in futures if f.done()]

                        for future in done_futures:
                            job_id, start_frame, end_frame, eye, job = futures.pop(future)
                            frame_count = end_frame - start_frame + 1

                            try:
                                success = future.result()
                                if success:
                                    self.farm_manager.complete_frames(job_id, start_frame, end_frame, eye)
                                    self.total_success += frame_count
                                    self.log_signal.emit(f"  ✅ 완료: {start_frame}-{end_frame} ({eye.upper()})")
                                else:
                                    self.farm_manager.release_frames(job_id, start_frame, end_frame, eye)
                                    self.total_failed += frame_count
                                    self.log_signal.emit(f"  ❌ 실패: {start_frame}-{end_frame} ({eye.upper()})")
                            except Exception as e:
                                self.farm_manager.release_frames(job_id, start_frame, end_frame, eye)
                                self.total_failed += frame_count
                                self.log_signal.emit(f"  ❌ 오류: {start_frame}-{end_frame} - {str(e)}")

                            self.total_processed += frame_count

                            # 진행률 업데이트
                            progress = self.farm_manager.get_job_progress(job_id)
                            self.progress_signal.emit(progress['completed'], progress['total'])

                            # 작업 완료 확인 및 신호 발송
                            if progress['completed'] >= progress['total'] and progress['total'] > 0:
                                self.job_completed_signal.emit(job_id)

                    # 작업이 없고 대기 중인 것도 없으면
                    if not futures:
                        if self.watchdog_mode:
                            if not idle_logged:
                                self.log_signal.emit("🔍 대기 중 - 새 작업 감시 중...")
                                idle_logged = True
                            self.farm_manager.update_heartbeat("idle")
                            time.sleep(3)
                        else:
                            self.log_signal.emit("✅ 모든 작업 완료")
                            break
                    else:
                        time.sleep(0.1)  # CPU 부하 감소

                except Exception as e:
                    self.log_signal.emit(f"❌ 오류: {str(e)}")
                    time.sleep(3)

        self.farm_manager.stop()
        self.log_signal.emit("\n=== 워커 중지됨 ===")

    def stop(self):
        """워커 중지"""
        self.is_running = False

    def process_frame_range(self, job: Job, start_frame: int, end_frame: int, eye: str) -> bool:
        """프레임 범위 처리 (실시간 진행률 포함)"""
        import threading
        output_dir = Path(job.output_dir)

        # 출력 디렉토리 생성
        if job.separate_folders:
            if eye == "sbs":
                (output_dir / "SBS").mkdir(parents=True, exist_ok=True)
            else:
                (output_dir / "L").mkdir(parents=True, exist_ok=True)
                (output_dir / "R").mkdir(parents=True, exist_ok=True)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        # CLI 명령 구성
        cmd = [
            str(self.cli_path),
            job.clip_path,
            str(output_dir),
            f"{start_frame}-{end_frame}",
            eye
        ]

        # 옵션 추가
        if job.format == "exr":
            cmd.append("--format=exr")
        if job.use_aces:
            cmd.append("--aces")
            if job.color_input_space:
                cmd.append(f"--input-cs={job.color_input_space}")
            if job.color_output_space:
                cmd.append(f"--output-cs={job.color_output_space}")
        if job.separate_folders:
            cmd.append("--separate-folders")
        if job.use_stmap and job.stmap_path:
            cmd.append(f"--stmap={job.stmap_path}")

        frame_count = end_frame - start_frame + 1
        stop_monitor = threading.Event()
        last_progress = [0]  # mutable for closure

        def monitor_progress():
            """출력 파일 감시하여 진행률 표시"""
            import time
            while not stop_monitor.is_set():
                completed = 0
                for frame_idx in range(start_frame, end_frame + 1):
                    check_path = self.farm_manager.get_output_file_path(job, frame_idx, eye)
                    if check_path.exists():
                        completed += 1

                if completed > last_progress[0]:
                    last_progress[0] = completed
                    pct = (completed / frame_count) * 100

                    # 전체 작업 진행률도 조회
                    try:
                        total_progress = self.farm_manager.get_job_progress(job.job_id)
                        total_done = total_progress['completed'] + completed
                        total_all = total_progress['total']
                        total_pct = (total_done / total_all * 100) if total_all > 0 else 0
                        self.log_signal.emit(f"  📊 [{start_frame}-{end_frame}] {eye.upper()}: {completed}/{frame_count} ({pct:.2f}%) | 전체: {total_done}/{total_all} ({total_pct:.2f}%)")
                    except Exception:
                        self.log_signal.emit(f"  📊 [{start_frame}-{end_frame}] {eye.upper()}: {completed}/{frame_count} ({pct:.2f}%)")

                if completed >= frame_count:
                    break
                time.sleep(2)  # 2초마다 체크

        # 진행률 모니터 스레드 시작
        monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
        monitor_thread.start()

        try:
            # 프레임당 타임아웃 + 기본 타임아웃 (SBS는 배수 적용)
            base_timeout = FRAME_BASE_TIMEOUT_SEC + (frame_count * FRAME_PER_FRAME_TIMEOUT_SEC)
            if eye == "sbs":
                base_timeout *= FRAME_SBS_MULTIPLIER
            timeout_sec = max(BATCH_CLAIM_TIMEOUT_SEC, base_timeout)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout_sec,
                creationflags=SUBPROCESS_FLAGS
            )

            # CLI 실행 결과 확인
            if result.returncode != 0:
                err_msg = result.stderr[:200] if result.stderr else "no stderr"
                self.log_signal.emit(f"  ⚠️ CLI 오류 (code={result.returncode}): {err_msg}")

            # 첫 프레임 파일 존재 확인
            check_file = self.farm_manager.get_output_file_path(job, start_frame, eye)
            if check_file.exists():
                return True
            else:
                self.log_signal.emit(f"  ⚠️ 출력 파일 없음: {check_file}")
                return False

        except subprocess.TimeoutExpired:
            self.log_signal.emit(f"  ⏰ 타임아웃")
            return False
        except Exception as e:
            self.log_signal.emit(f"  ❌ 오류: {str(e)}")
            return False
        finally:
            stop_monitor.set()
            monitor_thread.join(timeout=1)


class FarmUIV2(QMainWindow):
    """렌더팜 UI V2 메인 윈도우"""

    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(1600, 1000)
        self.resize(1800, 1100)

        # DB 경로 (환경변수 우선)
        # DB 경로는 settings에서
        db_path = settings.db_path
        self.farm_manager = create_farm_manager(db_path)

        # 윈도우 제목에 DB 경로 표시
        self.setWindowTitle(f"BRAW-Brew V2 (DB: {db_path})")
        self.cli_path = Path(settings.cli_path)

        self.worker_thread = None
        self.status_timer = None

        self.init_ui()
        self.setup_timers()

        self.log_signal.connect(self.append_worker_log)

        # 창 상태 복원
        self.restore_window_state()

    def init_ui(self):
        """UI 초기화"""
        self.setStyleSheet("""
            QMainWindow { background-color: #2d2d2d; }
            QWidget { color: #ffffff; font-family: 'Malgun Gothic', sans-serif; }
            QGroupBox {
                border: 1px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #404040;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton:pressed { background-color: #353535; }
            QPushButton:disabled { background-color: #303030; color: #666; }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #3a3a3a;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 3px;
            }
            QTableWidget {
                background-color: #353535;
                gridline-color: #454545;
                border: none;
            }
            QTableWidget::item { padding: 5px; }
            QTableWidget::item:selected { background-color: #0d7377; }
            QHeaderView::section {
                background-color: #404040;
                padding: 5px;
                border: none;
                font-weight: bold;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #555;
                font-family: 'Consolas', 'D2Coding', monospace;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                background-color: #353535;
            }
            QProgressBar::chunk { background-color: #0d7377; }
            QListWidget { background-color: #353535; border: 1px solid #555; color: #ffffff; }
            QListWidget::item { padding: 5px; color: #ffffff; }
            QListWidget::item:selected { background-color: #0d7377; }
            QMenu { background-color: #353535; border: 1px solid #555; color: #ffffff; padding: 5px; }
            QMenu::item { padding: 8px 25px; color: #ffffff; }
            QMenu::item:selected { background-color: #0d7377; }
            QDialog { background-color: #2d2d2d; color: #ffffff; }
            QLabel { color: #ffffff; }
            QDialogButtonBox { background-color: #2d2d2d; }
            QMessageBox { background-color: #2d2d2d; color: #ffffff; }
            QInputDialog QLineEdit { background-color: #3a3a3a; color: #ffffff; }
        """)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 상단 툴바
        toolbar = QWidget()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet("background-color: #2a2a2a; border-bottom: 2px solid #505050;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(15, 8, 15, 8)

        title_label = QLabel("🎬 BRAW-Brew V2")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #4db8c4;")
        toolbar_layout.addWidget(title_label)

        # 풀 선택
        toolbar_layout.addWidget(QLabel("풀:"))
        self.pool_combo = QComboBox()
        self.pool_combo.setMinimumWidth(150)
        self.pool_combo.currentIndexChanged.connect(self.on_pool_changed)
        toolbar_layout.addWidget(self.pool_combo)

        pool_manage_btn = QPushButton("⚙️")
        pool_manage_btn.setToolTip("풀 관리")
        pool_manage_btn.setMaximumWidth(40)
        pool_manage_btn.clicked.connect(self.show_pool_dialog)
        toolbar_layout.addWidget(pool_manage_btn)

        toolbar_layout.addStretch()

        # DB 경로 표시
        self.db_label = QPushButton(f"DB: {settings.db_path}")
        self.db_label.setStyleSheet("color: #888; font-size: 9pt;")
        self.db_label.setToolTip("클릭하여 DB 경로 변경")
        self.db_label.clicked.connect(self.change_db_path)
        toolbar_layout.addWidget(self.db_label)

        settings_btn = QPushButton("⚙️ 설정")
        settings_btn.clicked.connect(self.show_settings)
        toolbar_layout.addWidget(settings_btn)

        main_layout.addWidget(toolbar)

        # 메인 스플리터
        splitter = QSplitter(Qt.Horizontal)

        # 왼쪽: 작업 제출 + 워커 제어
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(self.create_submit_section())
        left_layout.addWidget(self.create_worker_section())
        splitter.addWidget(left_widget)

        # 오른쪽: 작업 목록 + 로그
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(self.create_jobs_section())
        right_splitter.addWidget(self.create_log_section())
        right_splitter.setSizes([400, 300])
        splitter.addWidget(right_splitter)

        splitter.setSizes([650, 1150])
        main_layout.addWidget(splitter)

        # 풀 목록 로드
        self.refresh_pools()

    def create_submit_section(self) -> QWidget:
        """작업 제출 섹션"""
        group = QGroupBox("📤 작업 제출")
        layout = QVBoxLayout(group)

        # 파일 선택 (드래그앤드롭 지원)
        file_layout = QHBoxLayout()
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(250)
        self.file_list.setAcceptDrops(True)
        self.file_list.setDragDropMode(QListWidget.DropOnly)
        file_layout.addWidget(self.file_list)
        self.file_list.currentItemChanged.connect(self.on_file_selected)

        # 드래그앤드롭 이벤트
        self.file_list.dragEnterEvent = self.file_list_drag_enter
        self.file_list.dragMoveEvent = self.file_list_drag_move
        self.file_list.dropEvent = self.file_list_drop
        self.clip_frame_cache = {}  # 클립별 프레임 수 캐시

        file_btn_layout = QVBoxLayout()
        add_btn = QPushButton("➕ 추가")
        add_btn.clicked.connect(self.add_files)
        clear_btn = QPushButton("🗑️ 지우기")
        clear_btn.clicked.connect(self.on_clear_files)
        file_btn_layout.addWidget(add_btn)
        file_btn_layout.addWidget(clear_btn)
        file_btn_layout.addStretch()
        file_layout.addLayout(file_btn_layout)
        layout.addLayout(file_layout)

        # 출력 경로
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("출력:"))
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("출력 폴더 선택...")
        output_browse = QPushButton("📁")
        output_browse.setMaximumWidth(40)
        output_browse.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(output_browse)
        layout.addLayout(output_layout)

        # 옵션
        opt_layout = QHBoxLayout()
        self.left_check = QCheckBox("L")
        self.left_check.setChecked(False)
        self.right_check = QCheckBox("R")
        self.right_check.setChecked(False)
        self.sbs_check = QCheckBox("SBS")
        self.sbs_check.setChecked(True)  # 디폴트 ON
        self.sbs_check.toggled.connect(self.on_sbs_toggled)
        self.aces_check = QCheckBox("ACES")
        self.aces_check.setChecked(True)  # 디폴트 ON
        self.separate_check = QCheckBox("폴더분리")
        self.separate_check.setChecked(False)
        self.separate_check.setEnabled(False)  # SBS 켜져있으면 비활성화

        opt_layout.addWidget(self.left_check)
        opt_layout.addWidget(self.right_check)
        opt_layout.addWidget(self.sbs_check)
        opt_layout.addWidget(self.aces_check)
        opt_layout.addWidget(self.separate_check)
        opt_layout.addStretch()
        layout.addLayout(opt_layout)

        # 프레임 범위
        frame_layout = QHBoxLayout()
        frame_layout.addWidget(QLabel("프레임:"))
        self.start_frame_spin = QSpinBox()
        self.start_frame_spin.setRange(0, 999999)
        self.start_frame_spin.setValue(0)
        self.start_frame_spin.setToolTip("시작 프레임 (0=처음부터)")
        frame_layout.addWidget(self.start_frame_spin)
        frame_layout.addWidget(QLabel("-"))
        self.end_frame_spin = QSpinBox()
        self.end_frame_spin.setRange(0, 999999)
        self.end_frame_spin.setValue(0)
        self.end_frame_spin.setToolTip("종료 프레임 (0=끝까지)")
        frame_layout.addWidget(self.end_frame_spin)
        self.frame_info_label = QLabel("(0=전체)")
        frame_layout.addWidget(self.frame_info_label)
        frame_layout.addStretch()
        layout.addLayout(frame_layout)

        # SpinBox 값 변경시 라벨 즉시 업데이트
        self.start_frame_spin.valueChanged.connect(self.update_frame_range_label)
        self.end_frame_spin.valueChanged.connect(self.update_frame_range_label)

        # 커스텀 프레임 (빠진 프레임 채우기)
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("커스텀:"))
        self.custom_frames_input = QLineEdit()
        self.custom_frames_input.setPlaceholderText("예: 509, 540, 602, 1675-1679, 1707")
        self.custom_frames_input.setToolTip("개별 프레임 또는 범위 입력 (쉼표로 구분)")
        custom_layout.addWidget(self.custom_frames_input)
        layout.addLayout(custom_layout)

        # 우선순위
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("우선순위:"))
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 100)
        self.priority_spin.setValue(50)
        priority_layout.addWidget(self.priority_spin)
        priority_layout.addStretch()
        layout.addLayout(priority_layout)

        # 제출 버튼
        submit_btn = QPushButton("🚀 작업 제출")
        submit_btn.setStyleSheet("background-color: #0d7377; font-weight: bold; padding: 12px;")
        submit_btn.clicked.connect(self.submit_job)
        layout.addWidget(submit_btn)

        return group

    def create_worker_section(self) -> QWidget:
        """워커 제어 섹션"""
        group = QGroupBox("🖥️ 워커 제어")
        layout = QVBoxLayout(group)

        # 병렬 수
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel("병렬:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(settings.parallel_workers)
        parallel_layout.addWidget(self.parallel_spin)

        self.watchdog_check = QCheckBox("Watchdog")
        self.watchdog_check.setChecked(True)
        self.watchdog_check.setToolTip("새 작업 자동 감지")
        parallel_layout.addWidget(self.watchdog_check)
        parallel_layout.addStretch()
        layout.addLayout(parallel_layout)

        # 시작/중지 버튼
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶️ 시작")
        self.start_btn.setStyleSheet("background-color: #0d7377;")
        self.start_btn.clicked.connect(self.start_worker)

        self.soft_stop_btn = QPushButton("⏸️ 소프트")
        self.soft_stop_btn.setStyleSheet("background-color: #f0ad4e;")
        self.soft_stop_btn.setToolTip("현재 작업 완료 후 중지")
        self.soft_stop_btn.clicked.connect(self.soft_stop_worker)
        self.soft_stop_btn.setEnabled(False)

        self.hard_stop_btn = QPushButton("⛔ 하드")
        self.hard_stop_btn.setStyleSheet("background-color: #d9534f;")
        self.hard_stop_btn.setToolTip("모든 프로세스 즉시 종료")
        self.hard_stop_btn.clicked.connect(self.hard_stop_worker)
        self.hard_stop_btn.setEnabled(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.soft_stop_btn)
        btn_layout.addWidget(self.hard_stop_btn)
        layout.addLayout(btn_layout)

        # 진행률
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # 통계
        self.stats_label = QLabel("대기 중")
        self.stats_label.setStyleSheet("color: #888;")
        layout.addWidget(self.stats_label)

        return group

    def create_jobs_section(self) -> QWidget:
        """작업 목록 섹션"""
        group = QGroupBox("📋 작업 목록")
        layout = QVBoxLayout(group)

        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(12)
        self.jobs_table.setHorizontalHeaderLabels([
            "작업 ID", "클립", "프레임", "풀", "상태", "L", "R", "SBS", "진행률", "우선순위", "생성", "경과"
        ])
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.jobs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in [3, 4, 5, 6, 7, 8, 9, 10, 11]:
            self.jobs_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.jobs_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.jobs_table.customContextMenuRequested.connect(self.show_job_context_menu)
        layout.addWidget(self.jobs_table)

        # 워커 현황
        worker_group = QGroupBox("🖥️ 활성 워커")
        worker_layout = QVBoxLayout(worker_group)
        self.worker_table = QTableWidget()
        self.worker_table.setColumnCount(5)
        self.worker_table.setHorizontalHeaderLabels([
            "워커 ID", "상태", "현재 작업", "완료 수", "마지막 활동"
        ])
        self.worker_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.worker_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.worker_table.setMaximumHeight(150)
        worker_layout.addWidget(self.worker_table)
        layout.addWidget(worker_group)

        # 새로고침 버튼
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.clicked.connect(self.refresh_jobs)
        layout.addWidget(refresh_btn)

        return group

    def create_log_section(self) -> QWidget:
        """로그 섹션"""
        group = QGroupBox("📜 로그")
        layout = QVBoxLayout(group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        # self.log_text.setMaximumHeight(200)  # 제거: 창 크기에 맞춤
        layout.addWidget(self.log_text)

        return group

    def setup_timers(self):
        """타이머 설정"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.refresh_jobs)
        self.status_timer.start(5000)  # 5초마다

    # ===== 이벤트 핸들러 =====

    def refresh_pools(self):
        """풀 목록 새로고침"""
        current = self.pool_combo.currentData()
        self.pool_combo.clear()

        pools = self.farm_manager.get_pools()
        for pool in pools:
            self.pool_combo.addItem(f"{pool.name} ({pool.pool_id})", pool.pool_id)

        # 이전 선택 복원
        if current:
            idx = self.pool_combo.findData(current)
            if idx >= 0:
                self.pool_combo.setCurrentIndex(idx)

    def on_pool_changed(self, index):
        """풀 변경"""
        pool_id = self.pool_combo.currentData()
        if pool_id:
            self.farm_manager.set_pool(pool_id)
            self.refresh_jobs()

    def show_pool_dialog(self):
        """풀 관리 다이얼로그"""
        dialog = PoolDialog(self.farm_manager, self)
        dialog.exec()
        self.refresh_pools()


    def change_db_path(self):
        """DB 경로 변경"""
        from PySide6.QtWidgets import QFileDialog
        new_path, _ = QFileDialog.getSaveFileName(
            self, "DB 파일 선택",
            settings.db_path,
            "SQLite DB (*.db);;All Files (*.*)"
        )
        if new_path:
            settings.db_path = new_path
            settings.save()
            self.db_label.setText(f"DB: {new_path}")
            self.append_worker_log(f"ℹ️ DB 경로 변경됨: {new_path} (재시작 필요)")

    def show_settings(self):
        """설정 다이얼로그"""
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # 설정 변경 후 UI 업데이트
            self.cli_path = Path(settings.cli_path)
            self.parallel_spin.setValue(settings.parallel_workers)

    def on_sbs_toggled(self, checked: bool):
        """SBS 토글 시 폴더분리 비활성화"""
        if checked:
            self.separate_check.setChecked(False)
            self.separate_check.setEnabled(False)
        else:
            self.separate_check.setEnabled(True)


    def file_list_drag_enter(self, event):
        """드래그 진입"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def file_list_drag_move(self, event):
        """드래그 이동"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def file_list_drop(self, event):
        """파일 드롭"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            added = 0
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.braw'):
                    self.add_file_to_list(file_path)
                    added += 1
                elif Path(file_path).is_dir():
                    # 폴더면 내부 .braw 파일 검색
                    for braw_file in Path(file_path).rglob("*.braw"):
                        self.add_file_to_list(str(braw_file))
                        added += 1
            if added > 0:
                self.append_worker_log(f"📁 {added}개 파일 추가됨")
            event.acceptProposedAction()
        else:
            event.ignore()

    def add_file_to_list(self, file_path: str):
        """파일 목록에 추가 (중복 체크, 프레임 정보 포함)"""
        # 중복 체크
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == file_path:
                return  # 이미 있음

        # 프레임 수 조회
        frame_count = self.get_clip_frame_count(file_path)
        clip_name = Path(file_path).name
        if frame_count > 0:
            display_text = f"{clip_name} (0-{frame_count - 1})"
            self.clip_frame_cache[file_path] = frame_count
        else:
            display_text = f"{clip_name} (프레임 정보 없음)"
            self.clip_frame_cache[file_path] = 0

        item = QListWidgetItem(display_text)
        item.setData(Qt.UserRole, file_path)
        item.setToolTip(file_path)
        self.file_list.addItem(item)

    def add_files(self):
        """파일 추가 버튼"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "BRAW 파일 선택", "", "BRAW Files (*.braw)"
        )
        for f in files:
            self.add_file_to_list(f)

        # 첫 파일 선택
        if self.file_list.count() > 0 and not self.file_list.currentItem():
            self.file_list.setCurrentRow(0)

    def on_file_selected(self, current, previous):
        """파일 선택 시 프레임 범위 업데이트"""
        if not current:
            self.frame_info_label.setText("(0=전체)")
            return

        clip_path = current.data(Qt.UserRole)
        if clip_path and clip_path in self.clip_frame_cache:
            frame_count = self.clip_frame_cache[clip_path]
            if frame_count > 0:
                # 최대값 설정
                self.end_frame_spin.setMaximum(frame_count - 1)
                self.start_frame_spin.setMaximum(frame_count - 1)
                # 라벨 업데이트
                self.update_frame_range_label()
            else:
                self.frame_info_label.setText("(정보 없음)")

    def update_frame_range_label(self):
        """SpinBox 값 변경시 프레임 범위 라벨 즉시 업데이트"""
        start = self.start_frame_spin.value()
        end = self.end_frame_spin.value()

        # 현재 선택된 파일의 전체 프레임 수 확인
        current = self.file_list.currentItem()
        if current:
            clip_path = current.data(Qt.UserRole)
            if clip_path and clip_path in self.clip_frame_cache:
                max_frame = self.clip_frame_cache[clip_path] - 1

                # 0-0이면 전체 범위 표시
                if start == 0 and end == 0:
                    self.frame_info_label.setText(f"(0-{max_frame})")
                else:
                    # 사용자 지정 범위 표시
                    actual_end = end if end > 0 else max_frame
                    self.frame_info_label.setText(f"({start}-{actual_end})")
                return

        # 파일 미선택시 또는 캐시 없을 때
        if start == 0 and end == 0:
            self.frame_info_label.setText("(0=전체)")
        else:
            actual_end = end if end > 0 else "끝"
            self.frame_info_label.setText(f"({start}-{actual_end})")

    def on_clear_files(self):
        """파일 목록 지우기"""
        self.file_list.clear()
        self.clip_frame_cache.clear()
        self.frame_info_label.setText("(0=전체)")

    def browse_output(self):
        """출력 폴더 선택"""
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if folder:
            self.output_input.setText(folder)


    def parse_custom_frames(self, input_text: str) -> list:
        """커스텀 프레임 문자열 파싱

        입력 예: "509, 540, 602, 1675-1679, 1707"
        출력: [(509, 509), (540, 540), (602, 602), (1675, 1679), (1707, 1707)]
        """
        if not input_text.strip():
            return []

        # 다양한 하이픈/대시 문자를 일반 하이픈으로 정규화
        # 엔 대시, 엠 대시, 전각 하이픈, 마이너스, 틸드 등
        normalized = re.sub(r'[\u2013\u2014\uFF0D\u2010\u2011\u2012\u2015\u2212~]', '-', input_text)
        # 전각 쉼표, 세미콜론도 쉼표로
        normalized = re.sub(r'[\uFF0C;\uFF1B]', ',', normalized)

        result = []
        parts = normalized.replace(" ", "").split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if "-" in part:
                # 범위: 1675-1679
                try:
                    start, end = part.split("-", 1)
                    start_frame = int(start)
                    end_frame = int(end)
                    if start_frame <= end_frame:
                        result.append((start_frame, end_frame))
                    else:
                        # 역순이면 자동 수정
                        result.append((end_frame, start_frame))
                except ValueError:
                    self.append_worker_log(f"\u26a0\ufe0f \uc798\ubabb\ub41c \ubc94\uc704: {part}")
            else:
                # 개별 프레임: 509
                try:
                    frame = int(part)
                    result.append((frame, frame))
                except ValueError:
                    self.append_worker_log(f"\u26a0\ufe0f \uc798\ubabb\ub41c \ud504\ub808\uc784: {part}")

        return result

    def submit_job(self):
        """작업 제출"""
        if self.file_list.count() == 0:
            self.append_worker_log("⚠️ 파일을 선택하세요.")
            return

        output_dir = self.output_input.text().strip()
        if not output_dir:
            self.append_worker_log("⚠️ 출력 폴더를 선택하세요.")
            return

        # 눈 선택
        eyes = []
        if self.left_check.isChecked():
            eyes.append("left")
        if self.right_check.isChecked():
            eyes.append("right")
        if self.sbs_check.isChecked():
            eyes.append("sbs")

        if not eyes:
            self.append_worker_log("⚠️ L, R, SBS 중 하나 이상 선택하세요.")
            return

        # 작업 제출
        submitted = 0
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            clip_path = item.data(Qt.UserRole) or item.text()
            clip_name = Path(clip_path).stem

            # 프레임 수 가져오기 (캐시 사용)
            frame_count = self.clip_frame_cache.get(clip_path, 0)
            if frame_count <= 0:
                frame_count = self.get_clip_frame_count(clip_path)
            if frame_count <= 0:
                self.append_worker_log(f"⚠️ 프레임 수 확인 실패: {clip_name}")
                continue

            # 커스텀 프레임 확인
            custom_text = self.custom_frames_input.text().strip()
            custom_ranges = self.parse_custom_frames(custom_text) if custom_text else []

            # 커스텀 프레임이 있으면 각 범위별로 작업 제출
            if custom_ranges:
                clip_output = str(Path(output_dir) / clip_name) if settings.render_clip_folder else output_dir

                for start_frame, end_frame in custom_ranges:
                    # 범위 검증
                    if start_frame >= frame_count or end_frame >= frame_count:
                        self.append_worker_log(f"⚠️ 프레임 범위 초과: {start_frame}-{end_frame} (최대: {frame_count-1})")
                        continue

                    job_id = self.farm_manager.submit_job(
                        clip_path=clip_path,
                        output_dir=clip_output,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        eyes=eyes,
                        format="exr" if settings.render_format_exr else "ppm",
                        separate_folders=self.separate_check.isChecked(),
                        use_aces=self.aces_check.isChecked(),
                        color_input_space=settings.color_input_space,
                        color_output_space=settings.color_output_space,
                        use_stmap=settings.render_use_stmap,
                        stmap_path=settings.stmap_path,
                        priority=self.priority_spin.value()
                    )
                    if job_id:
                        submitted += 1
                        self.append_worker_log(f"📤 커스텀 제출: {clip_name} [{start_frame}-{end_frame}]")
                continue  # 다음 클립으로

            # 일반 프레임 범위 결정 (0이면 전체)
            user_start = self.start_frame_spin.value()
            user_end = self.end_frame_spin.value()
            start_frame = user_start  # 0이면 처음부터
            end_frame = user_end if user_end > 0 else (frame_count - 1)  # 0이면 끝까지

            # 범위 검증
            if start_frame >= frame_count:
                self.append_worker_log(f"⚠️ 시작 프레임이 범위 초과: {clip_name}")
                continue
            if end_frame >= frame_count:
                end_frame = frame_count - 1

            # 클립별 출력 폴더
            clip_output = str(Path(output_dir) / clip_name) if settings.render_clip_folder else output_dir

            job_id = self.farm_manager.submit_job(
                clip_path=clip_path,
                output_dir=clip_output,
                start_frame=start_frame,
                end_frame=end_frame,
                eyes=eyes,
                format="exr" if settings.render_format_exr else "ppm",
                separate_folders=self.separate_check.isChecked(),
                use_aces=self.aces_check.isChecked(),
                color_input_space=settings.color_input_space,
                color_output_space=settings.color_output_space,
                use_stmap=settings.render_use_stmap,
                stmap_path=settings.stmap_path,
                priority=self.priority_spin.value()
            )

            self.append_worker_log(f"✅ 작업 제출: {job_id}")
            submitted += 1

        self.refresh_jobs()
        self.append_worker_log(f"✅ {submitted}개 작업이 제출되었습니다.")

    def get_clip_frame_count(self, clip_path: str) -> int:
        """클립 프레임 수 조회"""
        try:
            result = subprocess.run(
                [str(self.cli_path), clip_path, "--info"],
                capture_output=True,
                text=True,
                timeout=CLIP_INFO_TIMEOUT_SEC,
                creationflags=SUBPROCESS_FLAGS
            )
            for line in result.stdout.split('\n'):
                if 'frame' in line.lower() and 'count' in line.lower():
                    match = re.search(r'(\d+)', line)
                    if match:
                        return int(match.group(1))
        except Exception:
            pass
        return 0

    def refresh_jobs(self):
        """작업 목록 새로고침"""
        jobs_with_status = self.farm_manager.get_all_jobs_with_status()

        self.jobs_table.setRowCount(len(jobs_with_status))
        for row, (job, status, completed, total) in enumerate(jobs_with_status):
            # 작업 ID
            self.jobs_table.setItem(row, 0, QTableWidgetItem(job.job_id))

            # 클립
            clip_name = Path(job.clip_path).stem
            self.jobs_table.setItem(row, 1, QTableWidgetItem(clip_name))

            # 프레임 범위
            frame_range = f"{job.start_frame}-{job.end_frame}"
            self.jobs_table.setItem(row, 2, QTableWidgetItem(frame_range))

            # 풀
            self.jobs_table.setItem(row, 3, QTableWidgetItem(job.pool_id))

            # 상태
            status_text = {
                'pending': '⏳ 대기',
                'in_progress': '🔄 진행중',
                'completed': '✅ 완료',
                'excluded': '⏸️ 제외',
                'paused': '⏯️ 일시정지',
                'failed': '❌ 실패'
            }.get(status, status)
            self.jobs_table.setItem(row, 4, QTableWidgetItem(status_text))

            # 눈별 진행률 (L, R, SBS)
            eye_progress = self.farm_manager.get_job_eye_progress(job.job_id)
            for col, eye in [(5, 'left'), (6, 'right'), (7, 'sbs')]:
                if eye in eye_progress:
                    ep = eye_progress[eye]
                    pct = (ep['completed'] / ep['total'] * 100) if ep['total'] > 0 else 0
                    self.jobs_table.setItem(row, col, QTableWidgetItem(f"{ep['completed']}/{ep['total']}"))
                else:
                    self.jobs_table.setItem(row, col, QTableWidgetItem("-"))

            # 전체 진행률
            pct = (completed / total * 100) if total > 0 else 0
            self.jobs_table.setItem(row, 8, QTableWidgetItem(f"{completed}/{total} ({pct:.2f}%)"))

            # 우선순위
            self.jobs_table.setItem(row, 9, QTableWidgetItem(str(job.priority)))

            # 생성일
            self.jobs_table.setItem(row, 10, QTableWidgetItem(
                job.created_at.strftime("%m/%d %H:%M")
            ))

            # 경과 시간 (완료된 프레임이 있으면 시작된 것으로 간주)
            if completed > 0 or status == 'in_progress':
                elapsed = datetime.now() - job.created_at
                hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    elapsed_str = f"{hours}시간 {minutes}분"
                else:
                    elapsed_str = f"{minutes}분 {seconds}초"
                self.jobs_table.setItem(row, 11, QTableWidgetItem(elapsed_str))
            else:
                self.jobs_table.setItem(row, 11, QTableWidgetItem("-"))

        # 워커 현황 업데이트
        self.refresh_workers()

    def refresh_workers(self):
        """워커 현황 새로고침"""
        workers = self.farm_manager.get_active_workers()
        self.worker_table.setRowCount(len(workers))
        for row, worker in enumerate(workers):
            self.worker_table.setItem(row, 0, QTableWidgetItem(worker.worker_id))

            status_icon = {'active': '🟢', 'idle': '🟡', 'offline': '🔴'}.get(worker.status, '⚪')
            self.worker_table.setItem(row, 1, QTableWidgetItem(f"{status_icon} {worker.status}"))

            self.worker_table.setItem(row, 2, QTableWidgetItem(worker.current_job_id or "-"))
            self.worker_table.setItem(row, 3, QTableWidgetItem(str(worker.frames_completed)))

            if worker.last_heartbeat:
                time_str = worker.last_heartbeat.strftime("%H:%M:%S")
            else:
                time_str = "-"
            self.worker_table.setItem(row, 4, QTableWidgetItem(time_str))

    def show_job_context_menu(self, position):
        """작업 컨텍스트 메뉴"""
        selected = self.jobs_table.selectedItems()
        if not selected:
            return

        rows = set(item.row() for item in selected)
        job_ids = [self.jobs_table.item(row, 0).text() for row in rows]

        menu = QMenu(self)

        # 출력 폴더 열기 (단일 선택시)
        if len(job_ids) == 1:
            open_folder_action = QAction("📂 출력 폴더 열기", self)
            open_folder_action.triggered.connect(lambda: self.open_job_output_folder(job_ids[0]))
            menu.addAction(open_folder_action)

            # SeqChecker 스캔
            scan_action = QAction("🔍 SeqChecker 스캔", self)
            scan_action.triggered.connect(lambda: self.scan_and_rerender_job(job_ids[0]))
            menu.addAction(scan_action)
            menu.addSeparator()

        # 상태 변경
        exclude_action = QAction("⏸️ 제외", self)
        exclude_action.triggered.connect(lambda: self.batch_job_action(job_ids, 'exclude'))
        menu.addAction(exclude_action)

        activate_action = QAction("▶️ 활성화", self)
        activate_action.triggered.connect(lambda: self.batch_job_action(job_ids, 'activate'))
        menu.addAction(activate_action)

        pause_action = QAction("⏯️ 일시정지", self)
        pause_action.triggered.connect(lambda: self.batch_job_action(job_ids, 'pause'))
        menu.addAction(pause_action)

        menu.addSeparator()

        # 풀 이동
        move_menu = menu.addMenu("📦 풀 이동")
        for pool in self.farm_manager.get_pools():
            action = QAction(pool.name, self)
            action.triggered.connect(lambda checked, p=pool.pool_id: self.move_jobs_to_pool(job_ids, p))
            move_menu.addAction(action)

        menu.addSeparator()

        # 우선순위 변경
        priority_action = QAction("🔢 우선순위 변경", self)
        priority_action.triggered.connect(lambda: self.change_jobs_priority(job_ids))
        menu.addAction(priority_action)

        menu.addSeparator()

        # 리셋
        reset_action = QAction("🔄 리셋", self)
        reset_action.triggered.connect(lambda: self.batch_job_action(job_ids, 'reset'))
        menu.addAction(reset_action)

        # 삭제
        delete_action = QAction("🗑️ 삭제", self)
        delete_action.triggered.connect(lambda: self.batch_job_action(job_ids, 'delete'))
        menu.addAction(delete_action)

        menu.exec(self.jobs_table.viewport().mapToGlobal(position))


    def open_job_output_folder(self, job_id: str):
        """작업의 출력 폴더 열기"""
        job = self.farm_manager.get_job(job_id)
        if job:
            output_path = Path(job.output_dir)
            if output_path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_path)))
                self.append_worker_log(f"📂 폴더 열기: {output_path}")
            else:
                # 상위 폴더 시도
                parent = output_path.parent
                if parent.exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
                    self.append_worker_log(f"📂 상위 폴더 열기: {parent}")
                else:
                    self.append_worker_log(f"⚠️ 폴더가 존재하지 않습니다: {output_path}")
        else:
            self.append_worker_log(f"⚠️ 작업을 찾을 수 없습니다: {job_id}")

    def batch_job_action(self, job_ids: list, action: str):
        """배치 작업 처리"""
        for job_id in job_ids:
            if action == 'exclude':
                self.farm_manager.exclude_job(job_id)
            elif action == 'activate':
                self.farm_manager.activate_job(job_id)
            elif action == 'pause':
                self.farm_manager.pause_job(job_id)
            elif action == 'reset':
                self.farm_manager.reset_job(job_id)
            elif action == 'delete':
                self.farm_manager.delete_job(job_id)

        self.refresh_jobs()
        self.append_worker_log(f"✅ {len(job_ids)}개 작업 {action} 완료")

    def move_jobs_to_pool(self, job_ids: list, pool_id: str):
        """작업 풀 이동"""
        for job_id in job_ids:
            self.farm_manager.move_job_to_pool(job_id, pool_id)
        self.refresh_jobs()
        self.append_worker_log(f"✅ {len(job_ids)}개 작업을 '{pool_id}' 풀로 이동")

    def change_jobs_priority(self, job_ids: list):
        """작업 우선순위 변경"""
        priority, ok = QInputDialog.getInt(
            self, "우선순위 변경", "새 우선순위 (0-100):",
            50, 0, 100
        )
        if ok:
            for job_id in job_ids:
                self.farm_manager.set_job_priority(job_id, priority)
            self.refresh_jobs()

    def start_worker(self):
        """워커 시작"""
        self.worker_thread = WorkerThreadV2(
            self.farm_manager,
            self.cli_path,
            self.parallel_spin.value(),
            self.watchdog_check.isChecked()
        )
        self.worker_thread.log_signal.connect(self.append_worker_log)
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.job_completed_signal.connect(self.on_job_completed)
        self.worker_thread.start()

        self.start_btn.setEnabled(False)
        self.soft_stop_btn.setEnabled(True)
        self.hard_stop_btn.setEnabled(True)

    def soft_stop_worker(self):
        """소프트 중지 - 현재 작업 완료 후 중지"""
        if self.worker_thread:
            self.worker_thread.stop()
            self.append_worker_log("⏸️ 소프트 중지 요청 - 현재 작업 완료 후 중지...")
            self.soft_stop_btn.setEnabled(False)
            self.soft_stop_btn.setText("⏳ 대기...")
            QTimer.singleShot(1000, self.check_worker_stopped)

    def hard_stop_worker(self):
        """하드 중지 - 모든 프로세스 즉시 종료"""
        if self.worker_thread:
            self.worker_thread.stop()
            self.append_worker_log("⛔ 하드 중지 - 모든 프로세스 강제 종료...")

            # braw_cli 프로세스 강제 종료
            self.kill_braw_processes()

            self.soft_stop_btn.setEnabled(False)
            self.hard_stop_btn.setEnabled(False)
            self.hard_stop_btn.setText("⏳ 종료중...")

            # 워커 스레드 강제 종료
            if self.worker_thread.isRunning():
                self.worker_thread.terminate()
                self.worker_thread.wait(3000)

            self.reset_stop_buttons()
            self.append_worker_log("⛔ 하드 중지 완료")

    def kill_braw_processes(self):
        """braw_cli 관련 프로세스 강제 종료"""
        import subprocess
        import time

        targets = ["braw_cli.exe", "cli_cuda.exe"]
        killed_count = 0

        for target in targets:
            for attempt in range(3):  # 최대 3번 시도
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/IM", target],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        killed_count += 1
                        self.append_worker_log(f"  - {target} 종료됨")
                    elif "not found" in result.stderr.lower() or "찾을 수 없습니다" in result.stderr:
                        break  # 프로세스 없음
                    time.sleep(0.3)
                except Exception as e:
                    self.append_worker_log(f"  - {target} 종료 시도 {attempt+1} 실패: {e}")

        if killed_count > 0:
            self.append_worker_log(f"  - 총 {killed_count}개 프로세스 종료됨")

    def check_worker_stopped(self):
        """워커 종료 확인"""
        if self.worker_thread and self.worker_thread.isRunning():
            QTimer.singleShot(1000, self.check_worker_stopped)
        else:
            self.reset_stop_buttons()

    def reset_stop_buttons(self):
        """중지 버튼 상태 리셋"""
        self.start_btn.setEnabled(True)
        self.soft_stop_btn.setText("⏸️ 소프트")
        self.soft_stop_btn.setEnabled(False)
        self.hard_stop_btn.setText("⛔ 하드")
        self.hard_stop_btn.setEnabled(False)

    def update_progress(self, completed: int, total: int):
        """진행률 업데이트"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)
        pct = (completed / total * 100) if total > 0 else 0
        self.stats_label.setText(f"진행: {completed}/{total} ({pct:.2f}%)")

    def append_worker_log(self, text: str):
        """로그 추가"""
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        # 스크롤 맨 아래로
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """종료 이벤트"""
        # 창 상태 저장
        self.save_window_state()

        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self.worker_thread.wait(5000)

        if self.status_timer:
            self.status_timer.stop()

        self.farm_manager.close()
        event.accept()

    def save_window_state(self):
        """창 상태 저장"""
        qsettings = QSettings("BRAW-Brew", "FarmV2")
        qsettings.setValue("geometry", self.saveGeometry())
        qsettings.setValue("windowState", self.saveState())

    def restore_window_state(self):
        """창 상태 복원"""
        qsettings = QSettings("BRAW-Brew", "FarmV2")
        geometry = qsettings.value("geometry")
        state = qsettings.value("windowState")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    # ===== SeqChecker Integration =====

    def run_seqchecker(self, job_id: str) -> Optional[List[int]]:
        """SeqChecker 실행 및 오류 프레임 반환"""
        job = self.farm_manager.get_job(job_id)
        if not job:
            self.append_worker_log(f"⚠️ 작업을 찾을 수 없습니다: {job_id}")
            return None

        output_path = Path(job.output_dir)

        if not output_path.exists():
            self.append_worker_log(f"⚠️ 출력 폴더가 없습니다: {output_path}")
            return None

        seqchecker_path = Path(settings.seqchecker_path)
        if not seqchecker_path.exists():
            self.append_worker_log(f"⚠️ SeqChecker를 찾을 수 없습니다: {seqchecker_path}")
            return None

        # 스캔할 폴더 결정 (SBS, L, R 순서)
        scan_folders = []
        eyes = job.eyes if job.eyes else ['sbs']
        if 'sbs' in eyes:
            sbs_path = output_path / "SBS"
            if sbs_path.exists():
                scan_folders.append(sbs_path)
        if 'left' in eyes:
            l_path = output_path / "L"
            if l_path.exists():
                scan_folders.append(l_path)
        if 'right' in eyes:
            r_path = output_path / "R"
            if r_path.exists():
                scan_folders.append(r_path)

        if not scan_folders:
            # 폴더 분리 안 된 경우 출력 폴더 직접 스캔
            scan_folders = [output_path]

        all_error_frames = set()

        for folder in scan_folders:
            self.append_worker_log(f"🔍 SeqChecker 스캔: {folder}")
            try:
                # 리포트 파일 경로 지정
                report_path = folder.parent / f"{folder.name}_report.txt"

                result = subprocess.run(
                    [str(seqchecker_path), str(folder), "-q", "-o", str(report_path)],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5분 타임아웃
                )

                if report_path.exists():
                    error_frames = self.parse_seqchecker_report(report_path)
                    if error_frames:
                        all_error_frames.update(error_frames)
                        self.append_worker_log(f"  ❌ 오류 프레임 {len(error_frames)}개: {error_frames[:10]}{'...' if len(error_frames) > 10 else ''}")
                    else:
                        self.append_worker_log(f"  ✅ 오류 없음")
                else:
                    if result.returncode != 0:
                        self.append_worker_log(f"  ⚠️ SeqChecker 오류 (code={result.returncode})")
                    else:
                        self.append_worker_log(f"  ✅ 오류 없음")

            except subprocess.TimeoutExpired:
                self.append_worker_log(f"  ⚠️ SeqChecker 타임아웃")
            except Exception as e:
                self.append_worker_log(f"  ⚠️ SeqChecker 오류: {e}")

        return sorted(all_error_frames) if all_error_frames else None

    def parse_seqchecker_report(self, report_path: Path) -> List[int]:
        """SeqChecker 리포트에서 오류 프레임 파싱"""
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # RE-RENDER_FRAMES: 라인 찾기
            match = re.search(r'RE-RENDER_FRAMES:\s*\n([\d,\s]+)', content)
            if match:
                frames_str = match.group(1).strip()
                if frames_str:
                    return [int(x.strip()) for x in frames_str.split(',') if x.strip().isdigit()]
            return []
        except Exception as e:
            self.append_worker_log(f"  ⚠️ 리포트 파싱 오류: {e}")
            return []

    def create_rerender_job(self, original_job_id: str, error_frames: List[int]) -> Optional[str]:
        """오류 프레임에 대한 재렌더 작업 생성"""
        original_job = self.farm_manager.get_job(original_job_id)
        if not original_job:
            return None

        # 프레임 범위를 연속 구간으로 그룹화
        ranges = self.group_frames_to_ranges(error_frames)

        # 프레임 범위 문자열 생성 (start_frame, end_frame 갱신)
        if ranges:
            start_frame = ranges[0][0]
            end_frame = ranges[-1][1]
        else:
            return None

        # 새 작업 생성 (V2 API 사용)
        new_job_id = self.farm_manager.submit_job(
            clip_path=original_job.clip_path,
            output_dir=original_job.output_dir,
            start_frame=start_frame,
            end_frame=end_frame,
            eyes=original_job.eyes,
            pool_id=original_job.pool_id,
            format=original_job.format,
            separate_folders=original_job.separate_folders,
            use_aces=original_job.use_aces,
            color_input_space=original_job.color_input_space,
            color_output_space=original_job.color_output_space,
            use_stmap=original_job.use_stmap,
            stmap_path=original_job.stmap_path,
            priority=min(original_job.priority + 10, 100)  # 우선순위 높임 (max 100)
        )

        self.append_worker_log(f"🔄 재렌더 작업 생성: {new_job_id} ({len(error_frames)}프레임)")

        return new_job_id

    def group_frames_to_ranges(self, frames: List[int]) -> List[Tuple[int, int]]:
        """프레임 목록을 연속 구간으로 그룹화"""
        if not frames:
            return []

        frames = sorted(frames)
        ranges = []
        start = frames[0]
        end = frames[0]

        for frame in frames[1:]:
            if frame == end + 1:
                end = frame
            else:
                ranges.append((start, end))
                start = frame
                end = frame

        ranges.append((start, end))
        return ranges

    def scan_and_rerender_job(self, job_id: str):
        """작업 스캔 후 오류 프레임 재렌더"""
        error_frames = self.run_seqchecker(job_id)
        if error_frames and settings.seqchecker_auto_rerender:
            new_job_id = self.create_rerender_job(job_id, error_frames)
            if new_job_id:
                self.refresh_jobs()
        elif error_frames:
            self.append_worker_log(f"ℹ️ 오류 프레임 {len(error_frames)}개 발견 (자동 재렌더 비활성화)")

    def on_job_completed(self, job_id: str):
        """작업 완료 시 자동 SeqChecker 스캔"""
        if settings.seqchecker_auto_scan:
            self.append_worker_log(f"🔍 작업 완료 - 자동 SeqChecker 스캔: {job_id}")
            # 별도 스레드에서 실행 (UI 블로킹 방지)
            import threading
            threading.Thread(
                target=self._run_seqchecker_async,
                args=(job_id,),
                daemon=True
            ).start()

    def _run_seqchecker_async(self, job_id: str):
        """비동기 SeqChecker 실행"""
        try:
            error_frames = self.run_seqchecker(job_id)
            if error_frames and settings.seqchecker_auto_rerender:
                new_job_id = self.create_rerender_job(job_id, error_frames)
                if new_job_id:
                    # UI 스레드에서 새로고침
                    QTimer.singleShot(0, self.refresh_jobs)
        except Exception as e:
            self.append_worker_log(f"⚠️ SeqChecker 오류: {e}")


def main():
    app = QApplication(sys.argv)
    window = FarmUIV2()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
