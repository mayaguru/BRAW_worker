#!/usr/bin/env python3
"""Custom frames input and hard/soft stop patch"""
import re
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

changes_made = []

# 1. Add custom frames input after frame range section
old_frame_section = """        # SpinBox 값 변경시 라벨 즉시 업데이트
        self.start_frame_spin.valueChanged.connect(self.update_frame_range_label)
        self.end_frame_spin.valueChanged.connect(self.update_frame_range_label)

        # 우선순위"""

new_frame_section = """        # SpinBox 값 변경시 라벨 즉시 업데이트
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

        # 우선순위"""

if old_frame_section in content and "custom_frames_input" not in content:
    content = content.replace(old_frame_section, new_frame_section)
    changes_made.append("[OK] Custom frames input added")
else:
    changes_made.append("[SKIP] Custom frames already exists or pattern mismatch")

# 2. Replace stop button with soft/hard stop buttons
old_stop_btn = """        # 시작/중지 버튼
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶️ 시작")
        self.start_btn.setStyleSheet("background-color: #0d7377;")
        self.start_btn.clicked.connect(self.start_worker)
        self.stop_btn = QPushButton("⏹️ 중지")
        self.stop_btn.setStyleSheet("background-color: #d9534f;")
        self.stop_btn.clicked.connect(self.stop_worker)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)"""

new_stop_btn = """        # 시작/중지 버튼
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
        layout.addLayout(btn_layout)"""

if old_stop_btn in content:
    content = content.replace(old_stop_btn, new_stop_btn)
    changes_made.append("[OK] Soft/Hard stop buttons added")
else:
    changes_made.append("[SKIP] Stop buttons already changed or pattern mismatch")

# 3. Update start_worker to enable both stop buttons
old_start_worker = """    def start_worker(self):
        \"\"\"워커 시작\"\"\"
        self.worker_thread = WorkerThreadV2(
            self.farm_manager,
            self.cli_path,
            self.parallel_spin.value(),
            self.watchdog_check.isChecked()
        )
        self.worker_thread.log_signal.connect(self.append_worker_log)
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)"""

new_start_worker = """    def start_worker(self):
        \"\"\"워커 시작\"\"\"
        self.worker_thread = WorkerThreadV2(
            self.farm_manager,
            self.cli_path,
            self.parallel_spin.value(),
            self.watchdog_check.isChecked()
        )
        self.worker_thread.log_signal.connect(self.append_worker_log)
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.start()

        self.start_btn.setEnabled(False)
        self.soft_stop_btn.setEnabled(True)
        self.hard_stop_btn.setEnabled(True)"""

if old_start_worker in content:
    content = content.replace(old_start_worker, new_start_worker)
    changes_made.append("[OK] start_worker updated for new buttons")
else:
    changes_made.append("[SKIP] start_worker already updated or pattern mismatch")

# 4. Replace stop_worker with soft_stop_worker and hard_stop_worker
old_stop_worker = """    def stop_worker(self):
        \"\"\"워커 중지\"\"\"
        if self.worker_thread:
            self.worker_thread.stop()
            self.append_worker_log("⏳ 워커 중지 요청...")
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("⏳ 중지 중...")

            # 종료 대기
            QTimer.singleShot(1000, self.check_worker_stopped)

    def check_worker_stopped(self):
        \"\"\"워커 종료 확인\"\"\"
        if self.worker_thread and self.worker_thread.isRunning():
            QTimer.singleShot(1000, self.check_worker_stopped)
        else:
            self.start_btn.setEnabled(True)
            self.stop_btn.setText("⏹️ 중지")
            self.stop_btn.setEnabled(False)"""

new_stop_worker = """    def soft_stop_worker(self):
        \"\"\"소프트 중지 - 현재 작업 완료 후 중지\"\"\"
        if self.worker_thread:
            self.worker_thread.stop()
            self.append_worker_log("⏸️ 소프트 중지 요청 - 현재 작업 완료 후 중지...")
            self.soft_stop_btn.setEnabled(False)
            self.soft_stop_btn.setText("⏳ 대기...")
            QTimer.singleShot(1000, self.check_worker_stopped)

    def hard_stop_worker(self):
        \"\"\"하드 중지 - 모든 프로세스 즉시 종료\"\"\"
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
        \"\"\"braw_cli 관련 프로세스 강제 종료\"\"\"
        import subprocess
        try:
            # braw_cli.exe 프로세스 종료
            subprocess.run(
                ["taskkill", "/F", "/IM", "braw_cli.exe"],
                capture_output=True, timeout=10
            )
            self.append_worker_log("  - braw_cli.exe 프로세스 종료됨")
        except Exception as e:
            self.append_worker_log(f"  - braw_cli 종료 오류: {e}")

        try:
            # cli_cuda.exe 프로세스도 종료 (있을 경우)
            subprocess.run(
                ["taskkill", "/F", "/IM", "cli_cuda.exe"],
                capture_output=True, timeout=10
            )
        except:
            pass

    def check_worker_stopped(self):
        \"\"\"워커 종료 확인\"\"\"
        if self.worker_thread and self.worker_thread.isRunning():
            QTimer.singleShot(1000, self.check_worker_stopped)
        else:
            self.reset_stop_buttons()

    def reset_stop_buttons(self):
        \"\"\"중지 버튼 상태 리셋\"\"\"
        self.start_btn.setEnabled(True)
        self.soft_stop_btn.setText("⏸️ 소프트")
        self.soft_stop_btn.setEnabled(False)
        self.hard_stop_btn.setText("⛔ 하드")
        self.hard_stop_btn.setEnabled(False)"""

if "def stop_worker(self):" in content and "def soft_stop_worker" not in content:
    content = content.replace(old_stop_worker, new_stop_worker)
    changes_made.append("[OK] soft/hard stop methods added")
else:
    changes_made.append("[SKIP] stop methods already changed or pattern mismatch")

# 5. Add parse_custom_frames method (before submit_job)
parse_method = '''
    def parse_custom_frames(self, input_text: str) -> list:
        """커스텀 프레임 문자열 파싱

        입력 예: "509, 540, 602, 1675-1679, 1707"
        출력: [(509, 509), (540, 540), (602, 602), (1675, 1679), (1707, 1707)]
        """
        if not input_text.strip():
            return []

        result = []
        parts = input_text.replace(" ", "").split(",")

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
                except ValueError:
                    self.append_worker_log(f"잘못된 범위: {part}")
            else:
                # 개별 프레임: 509
                try:
                    frame = int(part)
                    result.append((frame, frame))
                except ValueError:
                    self.append_worker_log(f"잘못된 프레임: {part}")

        return result

'''

if "def parse_custom_frames" not in content:
    # Insert before submit_job
    submit_job_pos = content.find("    def submit_job(self):")
    if submit_job_pos > 0:
        content = content[:submit_job_pos] + parse_method + content[submit_job_pos:]
        changes_made.append("[OK] parse_custom_frames method added")
    else:
        changes_made.append("[WARN] submit_job not found")
else:
    changes_made.append("[SKIP] parse_custom_frames already exists")

# 6. Modify submit_job to handle custom frames
# Find and update the frame range handling section in submit_job
old_submit_range = """            # 프레임 범위 결정 (0이면 전체)
            user_start = self.start_frame_spin.value()
            user_end = self.end_frame_spin.value()
            start_frame = user_start if user_start > 0 else 0
            end_frame = (user_end - 1) if user_end > 0 else (frame_count - 1)

            # 범위 검증
            if start_frame >= frame_count:
                self.append_worker_log(f"⚠️ 시작 프레임이 범위 초과: {clip_name}")
                continue
            if end_frame >= frame_count:
                end_frame = frame_count - 1

            # 클립별 출력 폴더
            clip_output = str(Path(output_dir) / clip_name) if settings.render_clip_folder else output_dir

            job_id = self.farm_manager.submit_job("""

new_submit_range = """            # 커스텀 프레임 확인
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
            start_frame = user_start if user_start > 0 else 0
            end_frame = (user_end - 1) if user_end > 0 else (frame_count - 1)

            # 범위 검증
            if start_frame >= frame_count:
                self.append_worker_log(f"⚠️ 시작 프레임이 범위 초과: {clip_name}")
                continue
            if end_frame >= frame_count:
                end_frame = frame_count - 1

            # 클립별 출력 폴더
            clip_output = str(Path(output_dir) / clip_name) if settings.render_clip_folder else output_dir

            job_id = self.farm_manager.submit_job("""

if old_submit_range in content and "custom_ranges = self.parse_custom_frames" not in content:
    content = content.replace(old_submit_range, new_submit_range)
    changes_made.append("[OK] submit_job updated for custom frames")
else:
    changes_made.append("[SKIP] submit_job custom frames already added or pattern mismatch")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for msg in changes_made:
    print(msg)
print("=" * 50)
print("[DONE] Patch complete!")
