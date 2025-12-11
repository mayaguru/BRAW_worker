#!/usr/bin/env python3
"""Add live progress tracking by monitoring output files"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

changes = []

# Replace process_frame_range with live progress version
old_method = '''    def process_frame_range(self, job: Job, start_frame: int, end_frame: int, eye: str) -> bool:
        """프레임 범위 처리"""
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
            cmd.extend(["--aces", "--gamma"])
            if job.color_input_space:
                cmd.append(f"--input-cs={job.color_input_space}")
            if job.color_output_space:
                cmd.append(f"--output-cs={job.color_output_space}")
        if job.separate_folders:
            cmd.append("--separate-folders")
        if job.use_stmap and job.stmap_path:
            cmd.append(f"--stmap={job.stmap_path}")

        try:
            frame_count = end_frame - start_frame + 1
            # 프레임당 60초 + 기본 300초 (SBS는 2배)
            base_timeout = 300 + (frame_count * 60)
            if eye == "sbs":
                base_timeout *= 2
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
# CLI 실행 결과 확인            if result.returncode != 0:                err_msg = result.stderr[:200] if result.stderr else "no stderr"                self.log_signal.emit(f"  ⚠️ CLI 오류 (code={result.returncode}): {err_msg}")

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
            return False'''

new_method = '''    def process_frame_range(self, job: Job, start_frame: int, end_frame: int, eye: str) -> bool:
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
            cmd.extend(["--aces", "--gamma"])
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
                    self.log_signal.emit(f"  📊 [{start_frame}-{end_frame}] {eye.upper()}: {completed}/{frame_count} ({pct:.0f}%)")

                if completed >= frame_count:
                    break
                time.sleep(2)  # 2초마다 체크

        # 진행률 모니터 스레드 시작
        monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
        monitor_thread.start()

        try:
            # 프레임당 60초 + 기본 300초 (SBS는 2배)
            base_timeout = 300 + (frame_count * 60)
            if eye == "sbs":
                base_timeout *= 2
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
            monitor_thread.join(timeout=1)'''

if old_method in content:
    content = content.replace(old_method, new_method)
    changes.append("[OK] Live progress monitoring added")
else:
    changes.append("[WARN] process_frame_range pattern not found")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)
print("[DONE] Patch complete!")
