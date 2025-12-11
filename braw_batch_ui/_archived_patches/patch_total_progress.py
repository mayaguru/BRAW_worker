#!/usr/bin/env python3
"""Add total job progress to live monitoring"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

old_monitor = '''        def monitor_progress():
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
                time.sleep(2)  # 2초마다 체크'''

new_monitor = '''        def monitor_progress():
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
                        self.log_signal.emit(f"  📊 [{start_frame}-{end_frame}] {eye.upper()}: {completed}/{frame_count} ({pct:.0f}%) | 전체: {total_done}/{total_all} ({total_pct:.0f}%)")
                    except:
                        self.log_signal.emit(f"  📊 [{start_frame}-{end_frame}] {eye.upper()}: {completed}/{frame_count} ({pct:.0f}%)")

                if completed >= frame_count:
                    break
                time.sleep(2)  # 2초마다 체크'''

if old_monitor in content:
    content = content.replace(old_monitor, new_monitor)
    file_path.write_text(content, encoding='utf-8')
    print("[OK] Total progress added")
else:
    print("[WARN] Pattern not found")
