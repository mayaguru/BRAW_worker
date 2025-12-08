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
                               QTabWidget, QProgressBar, QMessageBox, QMenu, QDialog,
                               QListWidget, QListWidgetItem, QComboBox, QInputDialog)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QUrl
from PySide6.QtGui import QFont, QColor, QAction, QDesktopServices

from farm_core import FarmManager, RenderJob, WorkerInfo
from config import (
    settings,
    SUBPROCESS_TIMEOUT_DEFAULT_SEC,
    SUBPROCESS_TIMEOUT_ACES_SEC,
    CLIP_INFO_TIMEOUT_SEC,
    LOG_MAX_LINES,
)


def parse_ocio_colorspaces(config_path: str) -> list:
    """OCIO config 파일에서 색공간 목록 파싱"""
    colorspaces = []
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # colorspaces 섹션에서 name 추출
        import re
        # "- !<ColorSpace>" 블록에서 name: 추출
        pattern = r'- !<ColorSpace>\s*\n(?:.*\n)*?\s*name:\s*([^\n]+)'
        matches = re.findall(pattern, content)
        for match in matches:
            name = match.strip().strip('"').strip("'")
            if name:
                colorspaces.append(name)
    except Exception as e:
        print(f"OCIO 파싱 오류: {e}")

    return sorted(set(colorspaces))


class ColorSpaceDialog(QDialog):
    """색공간 설정 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("색공간 설정")
        self.setMinimumWidth(600)
        self.colorspaces = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # OCIO Config 파일 선택
        config_layout = QHBoxLayout()
        config_layout.addWidget(QLabel("OCIO Config:"))
        self.config_input = QLineEdit(settings.ocio_config_path)
        self.config_input.setPlaceholderText("OCIO config 파일 선택...")
        browse_btn = QPushButton("📁")
        browse_btn.setMaximumWidth(40)
        browse_btn.clicked.connect(self.browse_config)
        load_btn = QPushButton("로드")
        load_btn.clicked.connect(self.load_colorspaces)
        config_layout.addWidget(self.config_input)
        config_layout.addWidget(browse_btn)
        config_layout.addWidget(load_btn)
        layout.addLayout(config_layout)

        # 입력 색공간
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("입력 색공간:"))
        self.input_combo = QComboBox()
        self.input_combo.setEditable(True)
        self.input_combo.setMinimumWidth(300)
        self.input_combo.currentTextChanged.connect(self.on_colorspace_changed)
        input_layout.addWidget(self.input_combo)
        input_layout.addStretch()
        layout.addLayout(input_layout)

        # 출력 색공간
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("출력 색공간:"))
        self.output_combo = QComboBox()
        self.output_combo.setEditable(True)
        self.output_combo.setMinimumWidth(300)
        self.output_combo.currentTextChanged.connect(self.on_colorspace_changed)
        output_layout.addWidget(self.output_combo)
        output_layout.addStretch()
        layout.addLayout(output_layout)

        # 프리셋 관리
        preset_group = QGroupBox("프리셋")
        preset_layout = QVBoxLayout(preset_group)

        preset_btn_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(200)
        self.update_preset_combo()
        self.preset_combo.currentTextChanged.connect(self.load_preset)

        save_preset_btn = QPushButton("💾 저장")
        save_preset_btn.clicked.connect(self.save_preset)
        delete_preset_btn = QPushButton("🗑️ 삭제")
        delete_preset_btn.clicked.connect(self.delete_preset)

        preset_btn_layout.addWidget(QLabel("프리셋:"))
        preset_btn_layout.addWidget(self.preset_combo)
        preset_btn_layout.addWidget(save_preset_btn)
        preset_btn_layout.addWidget(delete_preset_btn)
        preset_btn_layout.addStretch()
        preset_layout.addLayout(preset_btn_layout)

        layout.addWidget(preset_group)

        # 버튼
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("확인")
        ok_btn.clicked.connect(self.accept_settings)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # 초기 로드
        if settings.ocio_config_path:
            self.load_colorspaces()
        else:
            # 기본값 설정
            self.input_combo.addItem(settings.color_input_space)
            self.output_combo.addItem(settings.color_output_space)

        # 현재 설정 선택
        self.input_combo.setCurrentText(settings.color_input_space)
        self.output_combo.setCurrentText(settings.color_output_space)

    def browse_config(self):
        """OCIO config 파일 선택"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "OCIO Config 파일 선택", "",
            "OCIO Config (*.ocio);;모든 파일 (*.*)"
        )
        if file_path:
            self.config_input.setText(file_path)
            self.load_colorspaces()

    def load_colorspaces(self):
        """OCIO config에서 색공간 목록 로드"""
        config_path = self.config_input.text()
        if not config_path or not Path(config_path).exists():
            QMessageBox.warning(self, "경고", "유효한 OCIO config 파일을 선택하세요.")
            return

        self.colorspaces = parse_ocio_colorspaces(config_path)

        if not self.colorspaces:
            QMessageBox.warning(self, "경고", "색공간을 찾을 수 없습니다.")
            return

        # 현재 선택 저장
        current_input = self.input_combo.currentText()
        current_output = self.output_combo.currentText()

        # 콤보박스 업데이트
        self.input_combo.clear()
        self.output_combo.clear()
        self.input_combo.addItems(self.colorspaces)
        self.output_combo.addItems(self.colorspaces)

        # 이전 선택 복원
        if current_input in self.colorspaces:
            self.input_combo.setCurrentText(current_input)
        if current_output in self.colorspaces:
            self.output_combo.setCurrentText(current_output)

        QMessageBox.information(self, "로드 완료", f"{len(self.colorspaces)}개의 색공간을 로드했습니다.")

    def update_preset_combo(self):
        """프리셋 콤보박스 업데이트"""
        self.preset_combo.blockSignals(True)  # 시그널 차단 (불필요한 load_preset 호출 방지)
        self.preset_combo.clear()
        self.preset_combo.addItem("(프리셋 선택)")
        for name in settings.color_presets.keys():
            self.preset_combo.addItem(name)

        # 마지막 선택한 프리셋 복원
        if settings.last_preset and settings.last_preset in settings.color_presets:
            self.preset_combo.setCurrentText(settings.last_preset)
        self.preset_combo.blockSignals(False)

    def load_preset(self, name):
        """프리셋 로드"""
        if name == "(프리셋 선택)" or name not in settings.color_presets:
            return

        preset = settings.color_presets[name]
        input_space = preset.get("input", "")
        output_space = preset.get("output", "")

        # UI 업데이트
        self.input_combo.setCurrentText(input_space)
        self.output_combo.setCurrentText(output_space)

        # settings도 업데이트하고 저장 (마지막 선택한 프리셋 포함)
        settings.color_input_space = input_space
        settings.color_output_space = output_space
        settings.last_preset = name
        settings.save()
        print(f"[INFO] 프리셋 적용: {input_space} → {output_space}")

    def save_preset(self):
        """프리셋 저장"""
        name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋 이름:")
        if ok and name:
            settings.color_presets[name] = {
                "input": self.input_combo.currentText(),
                "output": self.output_combo.currentText()
            }
            settings.save()
            self.update_preset_combo()
            QMessageBox.information(self, "저장 완료", f"프리셋 '{name}'이(가) 저장되었습니다.")

    def delete_preset(self):
        """프리셋 삭제"""
        name = self.preset_combo.currentText()
        if name == "(프리셋 선택)":
            return

        if name in settings.color_presets:
            del settings.color_presets[name]
            settings.save()
            self.update_preset_combo()
            QMessageBox.information(self, "삭제 완료", f"프리셋 '{name}'이(가) 삭제되었습니다.")

    def on_colorspace_changed(self, text):
        """색공간 콤보박스 변경 시 settings 즉시 업데이트"""
        settings.color_input_space = self.input_combo.currentText()
        settings.color_output_space = self.output_combo.currentText()
        settings.save()

    def accept_settings(self):
        """설정 적용"""
        settings.ocio_config_path = self.config_input.text()
        settings.color_input_space = self.input_combo.currentText()
        settings.color_output_space = self.output_combo.currentText()
        settings.save()
        self.accept()


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

        # CLI 실행 파일 경로
        cli_path_layout = QHBoxLayout()
        cli_path_layout.addWidget(QLabel("CLI 실행 파일:"))
        self.cli_path_input = QLineEdit(settings.cli_path)
        cli_browse_btn = QPushButton("📁")
        cli_browse_btn.setMaximumWidth(40)
        cli_browse_btn.clicked.connect(self.browse_cli_path)
        cli_path_layout.addWidget(self.cli_path_input)
        cli_path_layout.addWidget(cli_browse_btn)
        layout.addLayout(cli_path_layout)

        # 병렬 처리 수
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel("기본 병렬 처리:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(settings.parallel_workers)
        parallel_layout.addWidget(self.parallel_spin)
        parallel_layout.addStretch()
        layout.addLayout(parallel_layout)

        # 최대 재시도 횟수
        retry_layout = QHBoxLayout()
        retry_layout.addWidget(QLabel("최대 재시도:"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 20)
        self.retry_spin.setValue(settings.max_retries)
        self.retry_spin.setToolTip("프레임 처리 실패 시 재시도 횟수 (기본: 5)")
        retry_layout.addWidget(self.retry_spin)
        retry_layout.addStretch()
        layout.addLayout(retry_layout)

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

    def browse_cli_path(self):
        """CLI 실행 파일 선택"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CLI 실행 파일 선택",
            "",
            "실행 파일 (*.exe);;모든 파일 (*.*)"
        )
        if file_path:
            self.cli_path_input.setText(file_path)

    def save_settings(self):
        """설정 저장"""
        settings.farm_root = self.farm_root_input.text()
        settings.cli_path = self.cli_path_input.text()
        settings.parallel_workers = self.parallel_spin.value()
        settings.max_retries = self.retry_spin.value()
        settings.save()
        self.accept()


class StatusUpdateThread(QThread):
    """상태 업데이트 스레드 (UI 블로킹 방지, 실시간 동기화)"""
    workers_signal = Signal(list)
    jobs_signal = Signal(list)  # List of (RenderJob, status, completed, total)

    def __init__(self, farm_manager):
        super().__init__()
        self.farm_manager = farm_manager
        self.is_running = False
        self._last_job_ids = set()  # 마지막으로 확인한 작업 ID 캐시

    def run(self):
        self.is_running = True
        while self.is_running:
            try:
                workers = self.farm_manager.get_active_workers()
                # 실시간 동기화: 모든 작업 + 상태 정보
                jobs_with_status = self.farm_manager.get_all_jobs_with_status()

                # 현재 작업 ID 세트
                current_job_ids = {job.job_id for job, _, _, _ in jobs_with_status}

                # 삭제된 작업 감지 (로그용)
                deleted_jobs = self._last_job_ids - current_job_ids
                if deleted_jobs:
                    pass  # 삭제된 작업은 자동으로 목록에서 제거됨

                self._last_job_ids = current_job_ids

                self.workers_signal.emit(workers)
                self.jobs_signal.emit(jobs_with_status)
            except (OSError, IOError):
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

                # 대기중인 작업 찾기 (완료되지 않은 것만)
                jobs = self.farm_manager.get_pending_jobs()

                # 완료되지 않은 작업만 필터링하고, 생성 시간순 정렬
                incomplete_jobs = [j for j in jobs if not self.farm_manager.is_job_complete(j)]
                incomplete_jobs.sort(key=lambda x: x.created_at)

                if incomplete_jobs:
                    # 첫 번째 미완료 작업만 처리 (한 파일 집중)
                    job = incomplete_jobs[0]
                    if self.is_running:
                        self.farm_manager.last_job_id = job.job_id
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
        # 만료된 클레임 정리 (배치 시작 전)
        self.farm_manager.cleanup_expired_claims()

        # 현재 작업 통계 초기화
        self.current_job_stats = {"success": 0, "failed": 0, "retried": 0}

        self.log_signal.emit(f"\n작업 발견: {job.job_id}")
        self.log_signal.emit(f"  파일: {Path(job.clip_path).name}")
        self.log_signal.emit(f"  범위: {job.start_frame}-{job.end_frame}")

        # 워커 상태 및 현재 작업 정보 업데이트
        self.farm_manager.worker.status = "active"
        # 작업이 바뀌면 카운터 리셋
        if self.farm_manager.worker.current_job_id != job.job_id:
            self.farm_manager.worker.current_processed = 0
            # 전체 프레임 수 계산 (프레임 범위 * eye 개수)
            frame_count = (job.end_frame - job.start_frame + 1) * len(job.eyes)
            self.farm_manager.worker.current_total_frames = frame_count
        self.farm_manager.worker.current_job_id = job.job_id
        self.farm_manager.worker.current_clip_name = Path(job.clip_path).name
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
            # 처리할 프레임이 없음 - 작업 완료 여부 확인
            if self.farm_manager.is_job_complete(job):
                # 완료된 작업이면 100%로 표시
                total = job.get_total_tasks()
                self.progress_signal.emit(total, total)
                self.farm_manager.worker.current_processed = total
                self.farm_manager.worker.current_total_frames = total
                self.log_signal.emit(f"  작업 완료됨 (다른 워커가 처리)")
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

                # 예외 처리 추가
                try:
                    success = future.result()
                except Exception as e:
                    self.log_signal.emit(f"  ⚠️ [{frame_idx}] {eye.upper()} 처리 중 예외: {str(e)}")
                    success = False

                if success:
                    # 파일 존재 확인 + 완료 표시 (원자적으로 처리)
                    if self.farm_manager.mark_completed_if_file_exists(job, frame_idx, eye):
                        self.farm_manager.increment_frames_completed()  # 스레드 안전
                        self.farm_manager.increment_current_processed()  # 스레드 안전
                        self.current_job_stats["success"] += 1
                        self.total_success += 1
                        self.total_processed += 1
                        self.farm_manager.update_worker()
                        self.log_signal.emit(f"  ✓ [{frame_idx}] {eye.upper()}")
                    else:
                        # 파일이 없으면 실패로 처리 (아래 재시도 로직으로)
                        success = False
                        self.log_signal.emit(f"  ⚠️ [{frame_idx}] {eye.upper()} 파일 생성 실패")

                if not success:
                    # 재시도 로직
                    retry_count = retry_tasks[(frame_idx, eye)]
                    max_retries = settings.max_retries
                    if retry_count < max_retries:
                        retry_tasks[(frame_idx, eye)] += 1
                        self.current_job_stats["retried"] += 1
                        self.log_signal.emit(f"  ⟳ [{frame_idx}] {eye.upper()} 재시도 ({retry_count + 1}/{max_retries})")
                        # 재시도 작업 제출
                        new_future = executor.submit(self.process_frame, job, frame_idx, eye)
                        futures[new_future] = (frame_idx, eye)
                    else:
                        # 최종 실패
                        self.farm_manager.release_claim(job.job_id, frame_idx, eye)
                        self.farm_manager.increment_total_errors()  # 스레드 안전
                        self.current_job_stats["failed"] += 1
                        self.total_failed += 1
                        self.total_processed += 1
                        self.farm_manager.update_worker()
                        self.log_signal.emit(f"  ✗ [{frame_idx}] {eye.upper()} 최종 실패")

                # 진행률 업데이트
                progress = self.farm_manager.get_job_progress(job.job_id)
                total = job.get_total_tasks()
                self.progress_signal.emit(progress["completed"], total)

        # 배치 처리 완료 통계 출력
        self.log_signal.emit(f"\n배치 처리 완료: {job.job_id}")
        self.log_signal.emit(f"  ✓ 성공: {self.current_job_stats['success']}")
        self.log_signal.emit(f"  ⟳ 재시도: {self.current_job_stats['retried']}")
        self.log_signal.emit(f"  ✗ 실패: {self.current_job_stats['failed']}")
        self.log_signal.emit(f"  전체 누적 - 성공: {self.total_success}, 실패: {self.total_failed}")

        # 작업이 완전히 끝났는지 확인 (모든 .done 파일 존재 여부)
        if self.farm_manager.is_job_complete(job):
            # 진행률 100%로 표시
            total = job.get_total_tasks()
            self.progress_signal.emit(total, total)
            # 워커 처리 수도 전체로 업데이트하고 즉시 반영
            self.farm_manager.worker.current_processed = total
            self.farm_manager.worker.current_total_frames = total
            self.farm_manager.update_worker()  # 완료 상태 즉시 반영

            # 검증 클레임 시도 (한 워커만 검증 수행)
            if self.farm_manager.claim_verification(job.job_id):
                self.log_signal.emit(f"\n📁 작업 완료 - 출력 파일 검증 시작...")
                try:
                    verify_result = self.farm_manager.verify_job_output_files(job)

                    # 이미 검증 완료된 작업이면 간단히 표시
                    if verify_result.get('already_verified'):
                        self.log_signal.emit(f"  이미 검증 완료됨 ✅")
                    else:
                        self.log_signal.emit(f"  예상: {verify_result['total_expected']}개")
                        self.log_signal.emit(f"  정상: {verify_result['total_existing']}개")
                        self.log_signal.emit(f"  미싱: {verify_result['total_missing']}개")
                        self.log_signal.emit(f"  손상: {verify_result['total_corrupted']}개")
                        if verify_result['avg_file_size'] > 0:
                            avg_mb = verify_result['avg_file_size'] / (1024 * 1024)
                            self.log_signal.emit(f"  평균 크기: {avg_mb:.1f}MB")

                        total_problems = verify_result['total_missing'] + verify_result['total_corrupted']
                        if total_problems > 0:
                            self.log_signal.emit(f"  ⚠️ 문제 프레임 {total_problems}개 발견! 자동 복구 시도...")
                            # 손상된 파일 번호 출력
                            for corrupted in verify_result['corrupted_files'][:5]:  # 최대 5개만 표시
                                size_kb = corrupted['size'] / 1024
                                avg_kb = corrupted.get('avg_size', 0) / 1024
                                self.log_signal.emit(f"    - 프레임 {corrupted['frame']} ({corrupted['eye']}): {size_kb:.1f}KB (평균 {avg_kb:.0f}KB의 {size_kb/avg_kb*100:.0f}%)")
                            if len(verify_result['corrupted_files']) > 5:
                                self.log_signal.emit(f"    ... 외 {len(verify_result['corrupted_files']) - 5}개")
                            repaired = self.farm_manager.repair_missing_frames(job)
                            self.log_signal.emit(f"  🔧 {repaired}개 프레임 재처리 예약됨")
                        else:
                            self.log_signal.emit(f"  ✅ 모든 파일 정상 확인 (검증 완료)")
                finally:
                    # 검증 클레임 해제
                    self.farm_manager.release_verification_claim(job.job_id)
            elif self.farm_manager.is_job_verified(job.job_id):
                self.log_signal.emit(f"\n📁 작업 완료 - 이미 검증됨 ✅")
            else:
                self.log_signal.emit(f"\n📁 작업 완료 - 다른 워커가 검증 중...")
        else:
            # 아직 처리할 프레임이 남아있음
            progress = self.farm_manager.get_job_progress(job.job_id)
            total = job.get_total_tasks()
            self.log_signal.emit(f"  진행 중: {progress['completed']}/{total} 완료")

        # 작업 완료 후 워커 정보 업데이트 (처리 수는 유지)
        self.farm_manager.worker.status = "idle"
        self.farm_manager.worker.current_job_id = ""
        self.farm_manager.worker.current_clip_name = ""
        # current_processed와 current_total_frames는 유지 (마지막 처리 결과 표시)
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

        # 색공간 변환 플래그 추가 (EXR 출력일 때만)
        if job.format == "exr" and job.use_aces:
            cmd.append("--aces")
            cmd.append(f"--input-cs={job.color_input_space}")
            cmd.append(f"--output-cs={job.color_output_space}")

        # 디버그: 실행 명령 출력
        print(f"[DEBUG] CMD: {' '.join(cmd)}")

        try:
            # EXR + ACES 변환은 시간이 오래 걸릴 수 있음
            timeout_sec = SUBPROCESS_TIMEOUT_ACES_SEC if job.format == "exr" and job.use_aces else SUBPROCESS_TIMEOUT_DEFAULT_SEC
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout_sec
            )

            return result.returncode == 0 and output_file.exists()

        except subprocess.TimeoutExpired:
            print(f"[TIMEOUT] 프레임 처리 타임아웃: {frame_idx}")
            return False
        except Exception as e:
            print(f"[ERROR] 프레임 처리 오류: {e}")
            return False


class FarmUI(QMainWindow):
    """렌더팜 메인 UI"""

    def __init__(self):
        super().__init__()
        # FarmManager는 자동으로 settings.farm_root 사용
        self.farm_manager = FarmManager()
        self.worker_thread = None
        self.status_thread = None

        # CLI 경로를 설정에서 가져오기
        self.cli_path = Path(settings.cli_path)

        # CLI 파일 존재 확인
        if not self.cli_path.exists():
            QMessageBox.warning(
                None,
                "경고",
                f"CLI 실행 파일을 찾을 수 없습니다:\n{self.cli_path}\n\n"
                "설정(⚙️)에서 올바른 경로를 지정하세요."
            )

        self.init_ui()

        # 상태 업데이트 스레드 시작
        self.status_thread = StatusUpdateThread(self.farm_manager)
        self.status_thread.workers_signal.connect(self.update_workers_table)
        self.status_thread.jobs_signal.connect(self.update_jobs_table)
        self.status_thread.start()

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("BRAW Render Farm")
        self.setGeometry(100, 100, 1400, 800)
        self.setMinimumSize(1200, 700)

        # 다크 테마 스타일시트 적용
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QWidget {
                background-color: #3a3a3a;
                color: #f0f0f0;
                font-size: 9pt;
            }
            QGroupBox {
                background-color: #323232;
                border: 2px solid #505050;
                border-radius: 8px;
                margin-top: 15px;
                padding: 15px;
                padding-top: 25px;
                font-weight: bold;
                color: #4db8c4;
                font-size: 10pt;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                top: 5px;
                padding: 0 8px;
                background-color: #323232;
            }
            QLabel {
                background-color: transparent;
                color: #f0f0f0;
            }
            QLineEdit, QSpinBox, QTextEdit {
                background-color: #4a4a4a;
                border: 1px solid #606060;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 1px solid #0d7377;
            }
            QPushButton {
                background-color: #505050;
                border: 1px solid #606060;
                border-radius: 3px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border: 1px solid #707070;
            }
            QPushButton:pressed {
                background-color: #454545;
            }
            QCheckBox, QRadioButton {
                background-color: transparent;
                color: #f0f0f0;
            }
            QCheckBox::indicator, QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #606060;
                border-radius: 3px;
                background-color: #4a4a4a;
            }
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {
                background-color: #0d7377;
                border: 1px solid #0d7377;
            }
            QTableWidget {
                background-color: #2e2e2e;
                alternate-background-color: #353535;
                gridline-color: #4a4a4a;
                border: 2px solid #505050;
                border-radius: 5px;
                color: #f0f0f0;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #404040;
            }
            QTableWidget::item:selected {
                background-color: #0d7377;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #282828;
                color: #4db8c4;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #0d7377;
                font-weight: bold;
                font-size: 9pt;
            }
            QTextEdit {
                background-color: #2a2a2a;
                border: 2px solid #505050;
                border-radius: 5px;
                color: #f0f0f0;
                font-family: Consolas, "Courier New", monospace;
                font-size: 9pt;
                padding: 5px;
            }
            QScrollBar:vertical {
                border: none;
                background: #3a3a3a;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #606060;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #707070;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #3a3a3a;
                height: 12px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #606060;
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #707070;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 상단 툴바 (고정 높이)
        toolbar = QWidget()
        toolbar.setFixedHeight(50)  # 타이틀 바 높이 고정
        toolbar.setStyleSheet("background-color: #2a2a2a; border-bottom: 2px solid #505050;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(15, 8, 15, 8)

        # 타이틀
        title_label = QLabel("🎬 BRAW Render Farm")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #4db8c4;")
        toolbar_layout.addWidget(title_label)
        toolbar_layout.addStretch()

        # 설정 버튼 (크고 눈에 띄게)
        settings_btn = QPushButton("⚙️ 설정")
        settings_btn.setToolTip("렌더팜 설정\n공용 저장소 경로, CLI 실행 파일 경로 지정")
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #505050;
                color: white;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #454545;
            }
        """)
        settings_btn.clicked.connect(self.show_settings)
        toolbar_layout.addWidget(settings_btn)

        main_layout.addWidget(toolbar)

        # 컨텐츠 영역 - 스플리터 사용
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt

        # 스플리터 공통 스타일
        splitter_style = """
            QSplitter::handle {
                background-color: #505050;
            }
            QSplitter::handle:hover {
                background-color: #0d7377;
            }
            QSplitter::handle:horizontal {
                width: 4px;
            }
            QSplitter::handle:vertical {
                height: 4px;
            }
        """

        # 메인 가로 스플리터 (왼쪽/오른쪽 패널)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setStyleSheet(splitter_style)

        # 왼쪽 패널: 작업 제출 + 워커 제어 (세로 스플리터)
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setStyleSheet(splitter_style)
        left_splitter.setContentsMargins(10, 10, 10, 10)
        left_splitter.addWidget(self.create_submit_section())
        left_splitter.addWidget(self.create_worker_section())
        left_splitter.setSizes([450, 250])  # 작업 제출 : 워커 제어 비율

        # 오른쪽 패널: 모니터링 + 로그 (세로 스플리터)
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setStyleSheet(splitter_style)
        right_splitter.setContentsMargins(10, 10, 10, 10)
        right_splitter.addWidget(self.create_monitor_section())
        right_splitter.addWidget(self.create_log_section())
        right_splitter.setSizes([500, 200])  # 모니터링 : 로그 비율

        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([500, 900])  # 왼쪽 : 오른쪽 비율

        main_layout.addWidget(main_splitter)

    def create_submit_section(self):
        """작업 제출 섹션"""
        widget = QGroupBox("📤 작업 제출")
        layout = QVBoxLayout(widget)

        # 파일 선택 영역 (드래그 앤 드롭 지원)
        file_area = QWidget()
        file_area.setAcceptDrops(True)
        file_area.dragEnterEvent = self.drag_enter_event
        file_area.dropEvent = self.drop_event
        file_area.setStyleSheet("""
            QWidget {
                border: 2px dashed #505050;
                border-radius: 8px;
                background-color: #323232;
                padding: 10px;
            }
        """)
        file_layout = QVBoxLayout(file_area)

        # 파일 선택 버튼
        path_layout = QHBoxLayout()
        browse_btn = QPushButton("📁 파일 선택 (다중 선택 가능)")
        browse_btn.setToolTip("BRAW 파일을 선택하세요 (Ctrl+클릭으로 여러 파일 선택)\n또는 파일을 드래그 앤 드롭하세요")
        browse_btn.clicked.connect(self.browse_clips)
        path_layout.addWidget(browse_btn)
        file_layout.addLayout(path_layout)

        # 선택된 파일 목록
        self.file_list_widget = QListWidget()
        self.file_list_widget.setMinimumHeight(100)  # 최소 높이만 설정
        self.file_list_widget.setSelectionMode(QListWidget.ExtendedSelection)  # Ctrl+클릭 다중 선택
        self.file_list_widget.setToolTip("선택된 BRAW 파일 목록\n클릭: 프레임 범위 표시\nCtrl+클릭: 다중 선택 후 프레임 일괄 적용\n더블클릭: 제거")
        self.file_list_widget.itemClicked.connect(self.on_file_selected)
        self.file_list_widget.itemDoubleClicked.connect(self.remove_file_from_list)
        self.file_list_widget.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:selected {
                background-color: #0d7377;
            }
        """)
        file_layout.addWidget(self.file_list_widget)

        # 파일 카운터
        self.file_count_label = QLabel("선택된 파일: 0개")
        self.file_count_label.setStyleSheet("color: #4db8c4; font-weight: bold; padding: 5px;")
        file_layout.addWidget(self.file_count_label)

        layout.addWidget(file_area)

        # 저장된 파일 정보 딕셔너리 {파일경로: {"start": 시작, "end": 끝, "total": 전체프레임수}}
        self.selected_files = []  # 순서 유지용 리스트
        self.file_frame_ranges = {}  # 파일별 프레임 범위
        self.current_selected_file = None  # 현재 선택된 파일

        # 출력 폴더
        output_path_layout = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setText(settings.last_output_folder)  # 마지막 사용 폴더 로드
        self.output_input.setPlaceholderText("출력 폴더 선택...")
        self.output_input.setToolTip("렌더링된 이미지 시퀀스가 저장될 폴더")
        output_browse_btn = QPushButton("📁")
        output_browse_btn.setMaximumWidth(40)
        output_browse_btn.setToolTip("출력 폴더 찾아보기")
        output_browse_btn.clicked.connect(self.browse_output)
        output_path_layout.addWidget(QLabel("출력:"))
        output_path_layout.addWidget(self.output_input)
        output_path_layout.addWidget(output_browse_btn)
        layout.addLayout(output_path_layout)

        # 프레임 범위
        frame_layout = QHBoxLayout()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 100000)
        self.start_spin.setToolTip("렌더링 시작 프레임 번호 (0부터 시작)\n선택된 파일에 개별 적용됨")
        self.start_spin.valueChanged.connect(self.on_frame_range_changed)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(0, 100000)
        self.end_spin.setValue(29)
        self.end_spin.setToolTip("렌더링 종료 프레임 번호\n선택된 파일에 개별 적용됨")
        self.end_spin.valueChanged.connect(self.on_frame_range_changed)
        frame_layout.addWidget(QLabel("프레임:"))
        frame_layout.addWidget(self.start_spin)
        frame_layout.addWidget(QLabel("~"))
        frame_layout.addWidget(self.end_spin)
        layout.addLayout(frame_layout)

        # 옵션 - 한 줄로
        options_layout = QHBoxLayout()
        self.left_check = QCheckBox("L")
        self.left_check.setChecked(True)
        self.left_check.setToolTip("왼쪽 눈 렌더링 (스테레오 영상)")
        self.right_check = QCheckBox("R")
        self.right_check.setChecked(True)
        self.right_check.setToolTip("오른쪽 눈 렌더링 (스테레오 영상)")
        self.exr_radio = QRadioButton("EXR")
        self.exr_radio.setChecked(True)
        self.exr_radio.setToolTip("OpenEXR 포맷 (32bit float, 고품질)\n대용량, 후반작업에 적합")
        self.ppm_radio = QRadioButton("PPM")
        self.ppm_radio.setToolTip("PPM 포맷 (8bit, 빠른 처리)\n용량 작음, 미리보기/테스트용")
        self.clip_folder_check = QCheckBox("영상별폴더")
        self.clip_folder_check.setChecked(True)
        self.clip_folder_check.setToolTip("각 영상 파일마다 별도 폴더 생성\n체크: 출력폴더/영상이름/ 에 저장\n해제: 출력폴더/ 에 바로 저장")

        self.separate_check = QCheckBox("L/R분리")
        self.separate_check.setChecked(True)  # 폴더분리 기본값을 True로 설정
        self.separate_check.setToolTip("L/R 이미지를 별도 폴더에 저장\n체크: L/, R/ 폴더로 분리\n해제: 한 폴더에 _L, _R 접미사로 저장")

        self.aces_check = QCheckBox("색변환")
        self.aces_check.setChecked(True)  # 색공간 변환 기본값 True
        self.aces_check.setToolTip("OCIO 색공간 변환 적용\n체크: 설정된 입력→출력 색공간 변환\n해제: 원본 색공간 유지")

        # 색공간 설정 버튼
        self.color_settings_btn = QPushButton("🎨")
        self.color_settings_btn.setMaximumWidth(30)
        self.color_settings_btn.setToolTip(f"색공간 설정\n현재: {settings.color_input_space} → {settings.color_output_space}")
        self.color_settings_btn.clicked.connect(self.show_color_settings)

        # 현재 색공간 라벨
        self.color_info_label = QLabel(f"({settings.color_output_space})")
        self.color_info_label.setStyleSheet("color: #4db8c4; font-size: 8pt;")

        options_layout.addWidget(self.left_check)
        options_layout.addWidget(self.right_check)
        options_layout.addWidget(QLabel("|"))
        options_layout.addWidget(self.exr_radio)
        options_layout.addWidget(self.ppm_radio)
        options_layout.addWidget(QLabel("|"))
        options_layout.addWidget(self.clip_folder_check)
        options_layout.addWidget(self.separate_check)
        options_layout.addWidget(self.aces_check)
        options_layout.addWidget(self.color_settings_btn)
        options_layout.addWidget(self.color_info_label)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 제출 버튼
        submit_btn = QPushButton("✅ 작업 제출")
        submit_btn.setToolTip("렌더팜에 작업을 제출합니다\n워커들이 자동으로 프레임을 분산 처리합니다")
        submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d7377;
                color: white;
                padding: 8px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #14a1a8;
                color: white;
            }
            QPushButton:pressed {
                background-color: #0a5c5f;
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
        self.worker_id_label.setStyleSheet("font-weight: bold; color: #14a1a8;")
        self.worker_id_label.setToolTip("현재 워커 PC의 컴퓨터 이름과 IP 주소")
        self.network_status_label = QLabel("🟢 네트워크: 연결됨")
        self.network_status_label.setStyleSheet("color: #66bb6a; font-weight: bold;")
        self.network_status_label.setToolTip("공유 저장소와의 네트워크 연결 상태")
        info_layout.addWidget(self.worker_id_label)
        info_layout.addWidget(self.network_status_label)
        layout.addLayout(info_layout)

        # 병렬 처리 설정
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("병렬:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 50)
        self.parallel_spin.setValue(settings.parallel_workers)  # 설정에서 기본값 가져오기
        self.parallel_spin.setToolTip("동시에 처리할 프레임 수\nCPU 코어 수에 맞춰 조정하세요")
        settings_layout.addWidget(self.parallel_spin)
        settings_layout.addStretch()
        layout.addLayout(settings_layout)

        # 시작/중지 버튼
        btn_layout = QHBoxLayout()
        self.start_worker_btn = QPushButton("▶️ 시작")
        self.start_worker_btn.setToolTip("워커를 시작합니다\n렌더팜 작업을 자동으로 가져와 처리합니다")
        self.start_worker_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d7377;
                color: white;
                padding: 8px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #14a1a8;
                color: white;
            }
            QPushButton:pressed {
                background-color: #0a5c5f;
                color: white;
            }
        """)
        self.start_worker_btn.clicked.connect(self.start_worker)

        self.stop_worker_btn = QPushButton("⏹️ 중지")
        self.stop_worker_btn.setToolTip("워커를 중지합니다\n현재 처리 중인 프레임은 완료됩니다")
        self.stop_worker_btn.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                padding: 8px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #e57373;
                color: white;
            }
            QPushButton:pressed {
                background-color: #c62828;
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
        """모니터링 섹션 (내부 스플리터로 워커/작업 목록 분리)"""
        from PySide6.QtWidgets import QSplitter

        widget = QGroupBox("📊 실시간 모니터링")
        layout = QVBoxLayout(widget)

        # 스플리터 스타일
        splitter_style = """
            QSplitter::handle {
                background-color: #505050;
            }
            QSplitter::handle:hover {
                background-color: #0d7377;
            }
            QSplitter::handle:vertical {
                height: 4px;
            }
        """

        # 내부 세로 스플리터 (워커 테이블 / 작업 목록)
        monitor_splitter = QSplitter(Qt.Vertical)
        monitor_splitter.setStyleSheet(splitter_style)

        # === 활성 워커 섹션 ===
        workers_widget = QWidget()
        workers_layout = QVBoxLayout(workers_widget)
        workers_layout.setContentsMargins(0, 0, 0, 0)

        self.workers_table = QTableWidget()
        self.workers_table.setColumnCount(8)
        self.workers_table.setHorizontalHeaderLabels(["워커 ID", "IP", "상태", "CPU", "작업 ID", "영상", "처리", "에러"])
        self.workers_table.verticalHeader().setVisible(False)
        # 컬럼 너비 설정 (이미지 참고)
        self.workers_table.setColumnWidth(0, 120)  # 워커 ID
        self.workers_table.setColumnWidth(1, 90)   # IP
        self.workers_table.setColumnWidth(2, 70)   # 상태
        self.workers_table.setColumnWidth(3, 60)   # CPU
        self.workers_table.setColumnWidth(4, 160)  # 작업 ID
        self.workers_table.setColumnWidth(5, 180)  # 영상
        self.workers_table.setColumnWidth(6, 70)   # 처리
        self.workers_table.setColumnWidth(7, 50)   # 에러
        self.workers_table.horizontalHeader().setStretchLastSection(True)
        workers_layout.addWidget(QLabel("👷 활성 워커"))
        workers_layout.addWidget(self.workers_table)

        # === 작업 목록 섹션 ===
        jobs_widget = QWidget()
        jobs_layout = QVBoxLayout(jobs_widget)
        jobs_layout.setContentsMargins(0, 0, 0, 0)

        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(5)
        self.jobs_table.setHorizontalHeaderLabels(["작업 ID", "파일", "범위", "진행률", "제출자"])
        self.jobs_table.verticalHeader().setVisible(False)
        # 컬럼 너비 설정 (이미지 참고)
        self.jobs_table.setColumnWidth(0, 180)  # 작업 ID
        self.jobs_table.setColumnWidth(1, 200)  # 파일
        self.jobs_table.setColumnWidth(2, 80)   # 범위
        self.jobs_table.setColumnWidth(3, 140)  # 진행률
        self.jobs_table.setColumnWidth(4, 100)  # 제출자
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)  # 행 단위 선택
        self.jobs_table.setSelectionMode(QTableWidget.ExtendedSelection)  # 다중 선택 허용
        self.jobs_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.jobs_table.customContextMenuRequested.connect(self.show_job_context_menu)
        self.jobs_table.cellDoubleClicked.connect(self.on_job_double_clicked)  # 더블클릭으로 프레임 수정

        # 작업 목록 헤더 (제목 + 완료 작업 표시 옵션)
        jobs_header_layout = QHBoxLayout()
        jobs_header_layout.addWidget(QLabel("📋 작업 목록 (더블클릭: 프레임 범위 수정)"))
        jobs_header_layout.addStretch()

        # 완료된 작업 표시 체크박스
        self.show_completed_jobs = True
        self.show_completed_checkbox = QCheckBox("완료된 작업 표시")
        self.show_completed_checkbox.setChecked(True)
        self.show_completed_checkbox.stateChanged.connect(self.on_show_completed_changed)
        jobs_header_layout.addWidget(self.show_completed_checkbox)

        jobs_layout.addLayout(jobs_header_layout)
        jobs_layout.addWidget(self.jobs_table)

        # 스플리터에 추가
        monitor_splitter.addWidget(workers_widget)
        monitor_splitter.addWidget(jobs_widget)
        monitor_splitter.setSizes([200, 250])  # 워커 : 작업목록 비율

        layout.addWidget(monitor_splitter)

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

    def browse_clips(self):
        """클립 파일 선택 (다중)"""
        filenames, _ = QFileDialog.getOpenFileNames(self, "BRAW 파일 선택 (다중 선택 가능)", "", "BRAW Files (*.braw)")
        if filenames:
            self.add_files_to_list(filenames)

    def drag_enter_event(self, event):
        """드래그 진입 이벤트"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def drop_event(self, event):
        """드롭 이벤트"""
        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.braw'):
                files.append(file_path)

        if files:
            self.add_files_to_list(files)
        else:
            QMessageBox.warning(self, "경고", "BRAW 파일만 추가할 수 있습니다.")

    def add_files_to_list(self, file_paths):
        """파일 목록에 추가"""
        added_count = 0
        first_added = None

        for file_path in file_paths:
            # 중복 체크
            if file_path not in self.selected_files:
                self.selected_files.append(file_path)

                # 프레임 범위 자동 감지하여 저장
                total_frames = self.get_clip_frame_count(file_path)
                self.file_frame_ranges[file_path] = {
                    "start": 0,
                    "end": total_frames - 1 if total_frames > 0 else 29,
                    "total": total_frames
                }

                # 파일 이름 + 프레임 범위 표시
                from pathlib import Path
                file_name = Path(file_path).name
                frame_info = self.file_frame_ranges[file_path]
                self.file_list_widget.addItem(f"{file_name} [{frame_info['start']}-{frame_info['end']}]")
                added_count += 1

                # 첫 번째로 추가된 파일 기억
                if first_added is None:
                    first_added = file_path

        self.update_file_count()

        # 첫 번째 파일 선택
        if first_added:
            self.current_selected_file = first_added
            frame_info = self.file_frame_ranges[first_added]
            self.start_spin.blockSignals(True)
            self.end_spin.blockSignals(True)
            self.start_spin.setValue(frame_info["start"])
            self.end_spin.setValue(frame_info["end"])
            self.start_spin.blockSignals(False)
            self.end_spin.blockSignals(False)
            # 첫 번째 아이템 선택
            self.file_list_widget.setCurrentRow(0)

    def on_file_selected(self, item):
        """파일 목록에서 항목 클릭 시 해당 파일의 저장된 프레임 범위 표시"""
        row = self.file_list_widget.row(item)
        if 0 <= row < len(self.selected_files):
            file_path = self.selected_files[row]
            self.current_selected_file = file_path

            if file_path in self.file_frame_ranges:
                frame_info = self.file_frame_ranges[file_path]
                # 시그널 차단하여 불필요한 저장 방지
                self.start_spin.blockSignals(True)
                self.end_spin.blockSignals(True)
                self.start_spin.setValue(frame_info["start"])
                self.end_spin.setValue(frame_info["end"])
                self.start_spin.blockSignals(False)
                self.end_spin.blockSignals(False)

    def on_frame_range_changed(self):
        """프레임 범위 변경 시 선택된 파일(들)에 저장"""
        start = self.start_spin.value()
        end = self.end_spin.value()

        # 선택된 항목들 가져오기
        selected_items = self.file_list_widget.selectedItems()

        if selected_items:
            # 선택된 모든 파일에 적용
            for item in selected_items:
                row = self.file_list_widget.row(item)
                if 0 <= row < len(self.selected_files):
                    file_path = self.selected_files[row]
                    if file_path in self.file_frame_ranges:
                        self.file_frame_ranges[file_path]["start"] = start
                        self.file_frame_ranges[file_path]["end"] = end
                        # 리스트 아이템 텍스트 업데이트
                        from pathlib import Path
                        file_name = Path(file_path).name
                        item.setText(f"{file_name} [{start}-{end}]")

    def remove_file_from_list(self, item):
        """목록에서 파일 제거"""
        row = self.file_list_widget.row(item)
        if 0 <= row < len(self.selected_files):
            file_path = self.selected_files[row]
            del self.selected_files[row]
            if file_path in self.file_frame_ranges:
                del self.file_frame_ranges[file_path]
            self.file_list_widget.takeItem(row)
            self.update_file_count()

            # 파일이 남아있으면 첫 번째 파일 선택
            if len(self.selected_files) > 0:
                self.file_list_widget.setCurrentRow(0)
                self.on_file_selected(self.file_list_widget.item(0))
            else:
                self.current_selected_file = None

    def update_file_count(self):
        """파일 카운트 업데이트"""
        count = len(self.selected_files)
        self.file_count_label.setText(f"선택된 파일: {count}개")
        if count > 0:
            self.file_count_label.setStyleSheet("color: #4db8c4; font-weight: bold; padding: 5px;")
        else:
            self.file_count_label.setStyleSheet("color: #888888; font-weight: bold; padding: 5px;")

    def get_clip_frame_count(self, clip_path) -> int:
        """클립의 총 프레임 수 반환 (실패 시 0)"""
        try:
            result = subprocess.run(
                [str(self.cli_path), clip_path, "--info"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=CLIP_INFO_TIMEOUT_SEC
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "FRAME_COUNT=" in line and not line.startswith("[DEBUG]"):
                        return int(line.split("=", 1)[1])
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, ValueError):
            pass
        return 0

    def auto_detect_frame_range(self, clip_path):
        """파일의 프레임 범위 자동 감지 (deprecated - get_clip_frame_count 사용)"""
        frame_count = self.get_clip_frame_count(clip_path)
        if frame_count > 0:
            self.start_spin.setValue(0)
            self.end_spin.setValue(frame_count - 1)

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
                timeout=CLIP_INFO_TIMEOUT_SEC
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
                    self.file_info_label.setStyleSheet("color: #ff9800;")
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
                self.file_info_label.setStyleSheet("color: #66bb6a; font-weight: bold;")

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
        """작업 제출 (다중 파일 지원)"""
        output_dir = self.output_input.text()

        # 파일 체크
        if len(self.selected_files) == 0:
            QMessageBox.warning(self, "경고", "렌더링할 파일을 선택하세요.")
            return

        if not output_dir:
            QMessageBox.warning(self, "경고", "출력 폴더를 선택하세요.")
            return

        # 옵션 수집
        eyes = []
        if self.left_check.isChecked():
            eyes.append("left")
        if self.right_check.isChecked():
            eyes.append("right")

        if len(eyes) == 0:
            QMessageBox.warning(self, "경고", "최소 하나의 Eye(L 또는 R)를 선택하세요.")
            return

        format_type = "exr" if self.exr_radio.isChecked() else "ppm"
        separate_folders = self.separate_check.isChecked()
        clip_folder = self.clip_folder_check.isChecked()
        use_aces = self.aces_check.isChecked()

        # 각 파일마다 작업 생성
        submitted_jobs = []
        from pathlib import Path

        for clip_path in self.selected_files:
            clip_name = Path(clip_path).stem  # 확장자 제외한 파일명

            # 파일별 저장된 프레임 범위 사용 (없으면 현재 UI 값)
            if clip_path in self.file_frame_ranges:
                start_frame = self.file_frame_ranges[clip_path]["start"]
                end_frame = self.file_frame_ranges[clip_path]["end"]
            else:
                start_frame = self.start_spin.value()
                end_frame = self.end_spin.value()

            # 영상별폴더 옵션에 따라 출력 경로 결정
            if clip_folder:
                job_output_dir = str(Path(output_dir) / clip_name)
            else:
                job_output_dir = output_dir

            # 작업 생성
            timestamp = int(time.time() * 1000)  # 밀리초 단위로 고유성 보장
            job = RenderJob(f"job_{timestamp}_{clip_name}")
            job.clip_path = clip_path
            job.output_dir = job_output_dir
            job.start_frame = start_frame
            job.end_frame = end_frame
            job.eyes = eyes
            job.format = format_type
            job.separate_folders = separate_folders
            job.use_aces = use_aces
            job.color_input_space = settings.color_input_space
            job.color_output_space = settings.color_output_space

            # 제출
            self.farm_manager.submit_job(job)
            submitted_jobs.append(job.job_id)
            time.sleep(0.01)  # 고유 ID 보장을 위한 작은 딜레이

        # 결과 메시지
        total = len(submitted_jobs)
        if clip_folder:
            output_info = f"각 파일은 '{output_dir}/(파일명)/' 폴더에 렌더링됩니다."
        else:
            output_info = f"모든 파일이 '{output_dir}/' 폴더에 렌더링됩니다."

        # 출력 폴더 저장
        settings.last_output_folder = output_dir
        settings.save()

        QMessageBox.information(
            self,
            "작업 제출 완료",
            f"{total}개의 작업이 렌더팜에 제출되었습니다.\n\n{output_info}"
        )

        # 제출 후 파일 목록 초기화
        self.selected_files.clear()
        self.file_frame_ranges.clear()
        self.current_selected_file = None
        self.file_list_widget.clear()
        self.update_file_count()

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
            # 설정 즉시 적용
            self.parallel_spin.setValue(settings.parallel_workers)
            self.cli_path = Path(settings.cli_path)

            # FarmManager의 경로도 업데이트
            self.farm_manager = FarmManager()

            QMessageBox.information(
                self,
                "설정 적용됨",
                f"설정이 저장되고 적용되었습니다.\n\n"
                f"공용 저장소: {settings.farm_root}\n"
                f"CLI 경로: {settings.cli_path}\n"
                f"병렬 처리: {settings.parallel_workers}"
            )

    def show_color_settings(self):
        """색공간 설정 다이얼로그 표시"""
        dialog = ColorSpaceDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # 색공간 라벨 업데이트
            self.color_info_label.setText(f"({settings.color_output_space})")
            self.color_settings_btn.setToolTip(
                f"색공간 설정\n현재: {settings.color_input_space} → {settings.color_output_space}"
            )

    def append_worker_log(self, text):
        """워커 로그 추가 (메모리 누수 방지: 최대 LOG_MAX_LINES줄)"""
        self.worker_log.append(text)
        # 로그 줄 수 제한 (메모리 누수 방지)
        doc = self.worker_log.document()
        if doc.blockCount() > LOG_MAX_LINES:
            cursor = self.worker_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, doc.blockCount() - LOG_MAX_LINES)
            cursor.removeSelectedText()

    def update_progress(self, completed, total):
        """진행률 업데이트"""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)

    def update_network_status(self, connected):
        """네트워크 상태 업데이트"""
        if connected:
            self.network_status_label.setText("🟢 네트워크: 연결됨")
            self.network_status_label.setStyleSheet("color: #66bb6a; font-weight: bold;")
        else:
            self.network_status_label.setText("🔴 네트워크: 끊김 (재연결 중...)")
            self.network_status_label.setStyleSheet("color: #ef5350; font-weight: bold;")

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

            # 처리 프레임 수 (현재/전체)
            if worker.current_total_frames > 0:
                processed_text = f"{worker.current_processed}/{worker.current_total_frames}"
                processed_item = QTableWidgetItem(processed_text)
                # 완료되면 녹색, 진행중이면 주황색
                if worker.current_processed >= worker.current_total_frames:
                    processed_item.setForeground(QColor(76, 175, 80))  # 녹색
                else:
                    processed_item.setForeground(QColor(255, 152, 0))  # 주황색
            else:
                processed_item = QTableWidgetItem("-")
            self.workers_table.setItem(i, 6, processed_item)

            # 에러 수
            error_item = QTableWidgetItem(str(worker.total_errors) if worker.total_errors > 0 else "0")
            if worker.total_errors > 0:
                error_item.setForeground(QColor(244, 67, 54))  # 빨간색
            else:
                error_item.setForeground(QColor(76, 175, 80))  # 녹색
            self.workers_table.setItem(i, 7, error_item)

    def update_jobs_table(self, jobs_with_status):
        """작업 목록 테이블 업데이트 (실시간 동기화)

        Args:
            jobs_with_status: List of (RenderJob, status, completed, total) tuples
        """
        # 완료된 작업 표시 여부 확인
        show_completed = getattr(self, 'show_completed_jobs', True)

        # 필터링
        if not show_completed:
            jobs_with_status = [item for item in jobs_with_status if item[1] != 'completed']

        self.jobs_table.setRowCount(len(jobs_with_status))
        for i, (job, status, completed, total) in enumerate(jobs_with_status):
            try:
                progress_percent = (completed / total * 100) if total > 0 else 0

                # 작업 ID - 상태에 따라 색상 변경 (강화된 색상 구분)
                job_id_item = QTableWidgetItem(job.job_id)
                if status == 'pending':
                    # 대기중 - 파란색
                    job_id_item.setForeground(QColor(33, 150, 243))
                elif status == 'in_progress':
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

                # 진행률 - 퍼센트와 프레임 수 + 상태 표시
                if status == 'completed':
                    progress_text = f"✓ 완료 ({completed}/{total})"
                elif status == 'in_progress':
                    progress_text = f"⏳ {progress_percent:.1f}% ({completed}/{total})"
                else:
                    progress_text = f"⏸ 대기중 ({completed}/{total})"

                progress_item = QTableWidgetItem(progress_text)
                if status == 'pending':
                    progress_item.setForeground(QColor(158, 158, 158))  # 회색
                elif status == 'in_progress':
                    progress_item.setForeground(QColor(255, 152, 0))  # 주황색
                else:
                    progress_item.setForeground(QColor(76, 175, 80))  # 녹색
                self.jobs_table.setItem(i, 3, progress_item)

                # 제출자
                self.jobs_table.setItem(i, 4, QTableWidgetItem(job.created_by))
            except (AttributeError, TypeError, OSError):
                pass

    def on_show_completed_changed(self, state):
        """완료된 작업 표시 체크박스 상태 변경"""
        self.show_completed_jobs = (state == Qt.Checked)
        # 다음 업데이트에서 자동 반영됨 (StatusUpdateThread가 1초마다 갱신)

    def on_job_double_clicked(self, row, column):
        """작업 목록에서 더블클릭 시 프레임 범위 수정"""
        job_id_item = self.jobs_table.item(row, 0)
        if not job_id_item:
            return

        job_id = job_id_item.text()
        job_info = self.farm_manager.load_job(job_id)
        if not job_info:
            QMessageBox.warning(self, "오류", f"작업 정보를 찾을 수 없습니다: {job_id}")
            return

        # 현재 프레임 범위
        current_start = job_info.get("start_frame", 0)
        current_end = job_info.get("end_frame", 29)
        total_frames = job_info.get("total_frames", current_end + 1)

        # 다이얼로그로 프레임 범위 수정
        dialog = QDialog(self)
        dialog.setWindowTitle(f"프레임 범위 수정: {job_id}")
        dialog.setMinimumWidth(300)

        layout = QVBoxLayout(dialog)

        # 정보 라벨
        info_label = QLabel(f"클립: {Path(job_info.get('clip_path', '')).name}\n총 프레임: {total_frames}")
        layout.addWidget(info_label)

        # 프레임 범위 입력
        frame_layout = QHBoxLayout()
        start_spin = QSpinBox()
        start_spin.setRange(0, max(100000, total_frames))
        start_spin.setValue(current_start)

        end_spin = QSpinBox()
        end_spin.setRange(0, max(100000, total_frames))
        end_spin.setValue(current_end)

        frame_layout.addWidget(QLabel("시작:"))
        frame_layout.addWidget(start_spin)
        frame_layout.addWidget(QLabel("~"))
        frame_layout.addWidget(QLabel("끝:"))
        frame_layout.addWidget(end_spin)
        layout.addLayout(frame_layout)

        # 버튼
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("확인")
        cancel_btn = QPushButton("취소")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            new_start = start_spin.value()
            new_end = end_spin.value()

            if new_start > new_end:
                QMessageBox.warning(self, "오류", "시작 프레임이 끝 프레임보다 클 수 없습니다.")
                return

            # 작업 정보 업데이트
            job_info["start_frame"] = new_start
            job_info["end_frame"] = new_end

            # 작업 파일에 저장
            job_file = self.farm_manager.config.jobs_dir / f"{job_id}.json"
            try:
                with open(job_file, 'w', encoding='utf-8') as f:
                    json.dump(job_info, f, indent=2, ensure_ascii=False)

                # 테이블 업데이트
                self.jobs_table.setItem(row, 3, QTableWidgetItem(f"{new_start}-{new_end}"))
                self.add_log(f"📝 작업 '{job_id}' 프레임 범위 수정: {new_start}-{new_end}")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"작업 저장 실패: {e}")

    def show_job_context_menu(self, position):
        """작업 목록 컨텍스트 메뉴 표시"""
        # 선택된 행들 확인
        selected_rows = self.jobs_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # 선택된 작업 ID들 수집
        job_ids = []
        for index in selected_rows:
            row = index.row()
            job_id_item = self.jobs_table.item(row, 0)
            if job_id_item:
                job_ids.append(job_id_item.text())

        if not job_ids:
            return

        # 컨텍스트 메뉴 생성
        menu = QMenu(self)

        # 단일 선택일 때만 출력 폴더 열기
        if len(job_ids) == 1:
            open_folder_action = QAction("📁 출력 폴더 열기", self)
            open_folder_action.triggered.connect(lambda: self.open_output_folder(job_ids[0]))
            menu.addAction(open_folder_action)
            menu.addSeparator()

        # 다중 선택 지원 액션들
        if len(job_ids) == 1:
            # 리셋 액션
            reset_action = QAction("🔄 작업 리셋 (진행 상태 초기화)", self)
            reset_action.triggered.connect(lambda: self.reset_job(job_ids[0]))
            menu.addAction(reset_action)

            # 완료 표시 액션
            complete_action = QAction("✅ 완료로 표시", self)
            complete_action.triggered.connect(lambda: self.mark_job_complete(job_ids[0]))
            menu.addAction(complete_action)
        else:
            # 다중 리셋
            reset_action = QAction(f"🔄 선택한 {len(job_ids)}개 작업 리셋", self)
            reset_action.triggered.connect(lambda: self.reset_jobs(job_ids))
            menu.addAction(reset_action)

            # 다중 완료 표시
            complete_action = QAction(f"✅ 선택한 {len(job_ids)}개 작업 완료로 표시", self)
            complete_action.triggered.connect(lambda: self.mark_jobs_complete(job_ids))
            menu.addAction(complete_action)

        menu.addSeparator()

        # 삭제 액션 (다중 선택 지원)
        if len(job_ids) == 1:
            delete_action = QAction("🗑️ 작업 삭제", self)
            delete_action.triggered.connect(lambda: self.delete_job(job_ids[0]))
        else:
            delete_action = QAction(f"🗑️ 선택한 {len(job_ids)}개 작업 삭제", self)
            delete_action.triggered.connect(lambda: self.delete_jobs(job_ids))
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

    def reset_jobs(self, job_ids: list):
        """여러 작업 리셋"""
        reply = QMessageBox.question(
            self, "작업 리셋",
            f"{len(job_ids)}개의 작업을 리셋하시겠습니까?\n모든 진행 상태가 초기화됩니다.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for job_id in job_ids:
                self.farm_manager.reset_job(job_id)
            QMessageBox.information(self, "완료", f"{len(job_ids)}개의 작업이 리셋되었습니다.")

    def mark_jobs_complete(self, job_ids: list):
        """여러 작업을 완료로 표시"""
        reply = QMessageBox.question(
            self, "완료로 표시",
            f"{len(job_ids)}개의 작업을 완료로 표시하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for job_id in job_ids:
                self.farm_manager.mark_job_completed(job_id)
            QMessageBox.information(self, "완료", f"{len(job_ids)}개의 작업이 완료로 표시되었습니다.")

    def delete_jobs(self, job_ids: list):
        """여러 작업 삭제"""
        reply = QMessageBox.question(
            self, "작업 삭제",
            f"{len(job_ids)}개의 작업을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for job_id in job_ids:
                self.farm_manager.delete_job(job_id)
            QMessageBox.information(self, "완료", f"{len(job_ids)}개의 작업이 삭제되었습니다.")

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
