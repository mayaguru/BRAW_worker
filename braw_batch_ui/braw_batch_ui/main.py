#!/usr/bin/env python3
"""
BRAW Batch Export UI
세그먼트 기반 배치 처리 + 주기적 재시도 + 병렬 처리
"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional, List, Tuple
import threading
import queue
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class Job:
    """단일 작업 정의"""
    def __init__(self, frame_idx: int, eye_mode: str, output_file: Path, clip_path: Path):
        self.frame_idx = frame_idx
        self.eye_mode = eye_mode
        self.output_file = output_file
        self.clip_path = clip_path
        self.attempts = 0
        self.success = False
        self.error_msg = ""

    def to_dict(self):
        return {
            "frame_idx": self.frame_idx,
            "eye_mode": self.eye_mode,
            "output_file": str(self.output_file),
            "clip_path": str(self.clip_path),
            "attempts": self.attempts,
            "error_msg": self.error_msg
        }


class BrawBatchUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BRAW Batch Export - Segmented")
        self.root.geometry("800x650")

        # CLI 경로
        self.cli_path = Path(__file__).parents[2] / "build" / "bin" / "braw_cli.exe"
        self.failed_log_path = Path(__file__).parents[2] / "failed_jobs.json"

        # 상태
        self.is_running = False
        self.current_thread: Optional[threading.Thread] = None
        self.log_queue = queue.Queue()

        # 작업 큐 시스템
        self.all_jobs: List[Job] = []
        self.pending_jobs: List[Job] = []
        self.failed_jobs: List[Job] = []
        self.completed_count = 0

        self.setup_ui()
        self.update_log()
        self.load_failed_jobs()

    def setup_ui(self):
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 입력 파일
        ttk.Label(main_frame, text="BRAW 파일:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.clip_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.clip_var, width=50).grid(row=0, column=1, pady=5)
        ttk.Button(main_frame, text="찾기", command=self.browse_clip).grid(row=0, column=2, pady=5)

        # 출력 폴더
        ttk.Label(main_frame, text="출력 폴더:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.output_var = tk.StringVar(value="export")
        ttk.Entry(main_frame, textvariable=self.output_var, width=50).grid(row=1, column=1, pady=5)
        ttk.Button(main_frame, text="찾기", command=self.browse_output).grid(row=1, column=2, pady=5)

        # 프레임 범위
        frame_frame = ttk.Frame(main_frame)
        frame_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=10)

        ttk.Label(frame_frame, text="프레임 범위:").pack(side=tk.LEFT, padx=5)
        self.start_var = tk.StringVar(value="0")
        ttk.Entry(frame_frame, textvariable=self.start_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(frame_frame, text="~").pack(side=tk.LEFT)
        self.end_var = tk.StringVar(value="29")
        ttk.Entry(frame_frame, textvariable=self.end_var, width=8).pack(side=tk.LEFT, padx=5)

        self.all_frames_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_frame, text="전체", variable=self.all_frames_var,
                       command=self.toggle_all_frames).pack(side=tk.LEFT, padx=10)

        ttk.Button(frame_frame, text="클립 정보 가져오기",
                  command=self.fetch_clip_info).pack(side=tk.LEFT, padx=10)

        # 눈 선택
        eye_frame = ttk.Frame(main_frame)
        eye_frame.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=10)

        ttk.Label(eye_frame, text="스테레오:").pack(side=tk.LEFT, padx=5)
        self.left_var = tk.BooleanVar(value=True)
        self.right_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(eye_frame, text="왼쪽 (L)", variable=self.left_var).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(eye_frame, text="오른쪽 (R)", variable=self.right_var).pack(side=tk.LEFT, padx=10)

        # 포맷 선택
        format_frame = ttk.Frame(main_frame)
        format_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=10)

        ttk.Label(format_frame, text="출력 포맷:").pack(side=tk.LEFT, padx=5)
        self.format_var = tk.StringVar(value="exr")
        ttk.Radiobutton(format_frame, text="EXR (Half/DWAA)", variable=self.format_var, value="exr").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(format_frame, text="PPM", variable=self.format_var, value="ppm").pack(side=tk.LEFT, padx=10)

        # L/R 폴더 분리 옵션
        self.separate_folders_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(format_frame, text="L/R 폴더 분리", variable=self.separate_folders_var).pack(side=tk.LEFT, padx=20)

        # 세그먼트 및 재시도 설정
        options_frame = ttk.Frame(main_frame)
        options_frame.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=10)

        ttk.Label(options_frame, text="세그먼트 크기:").pack(side=tk.LEFT, padx=5)
        self.segment_var = tk.StringVar(value="10")
        ttk.Entry(options_frame, textvariable=self.segment_var, width=4).pack(side=tk.LEFT, padx=5)
        ttk.Label(options_frame, text="작업").pack(side=tk.LEFT)

        ttk.Label(options_frame, text="병렬 작업 수:").pack(side=tk.LEFT, padx=(20, 5))
        self.parallel_var = tk.StringVar(value="10")
        ttk.Entry(options_frame, textvariable=self.parallel_var, width=4).pack(side=tk.LEFT, padx=5)

        ttk.Label(options_frame, text="최대 재시도:").pack(side=tk.LEFT, padx=(20, 5))
        self.max_retry_var = tk.StringVar(value="3")
        ttk.Entry(options_frame, textvariable=self.max_retry_var, width=4).pack(side=tk.LEFT, padx=5)

        # 시작/중지 버튼
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=15)

        self.start_btn = ttk.Button(button_frame, text="시작", command=self.start_export)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(button_frame, text="중지", command=self.stop_export, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.clear_failed_btn = ttk.Button(button_frame, text="실패 목록 지우기", command=self.clear_failed)
        self.clear_failed_btn.pack(side=tk.LEFT, padx=5)

        # 통계
        stats_frame = ttk.Frame(main_frame)
        stats_frame.grid(row=7, column=0, columnspan=3, pady=5)

        self.total_var = tk.StringVar(value="총: 0")
        self.completed_var = tk.StringVar(value="완료: 0")
        self.failed_count_var = tk.StringVar(value="실패: 0")
        self.pending_var = tk.StringVar(value="대기: 0")

        ttk.Label(stats_frame, textvariable=self.total_var).pack(side=tk.LEFT, padx=10)
        ttk.Label(stats_frame, textvariable=self.completed_var, foreground="green").pack(side=tk.LEFT, padx=10)
        ttk.Label(stats_frame, textvariable=self.failed_count_var, foreground="red").pack(side=tk.LEFT, padx=10)
        ttk.Label(stats_frame, textvariable=self.pending_var, foreground="orange").pack(side=tk.LEFT, padx=10)

        # 진행 상황
        ttk.Label(main_frame, text="진행 상황:").grid(row=8, column=0, sticky=tk.W)
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.grid(row=8, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        self.status_var = tk.StringVar(value="대기 중...")
        ttk.Label(main_frame, textvariable=self.status_var).grid(row=9, column=0, columnspan=3, sticky=tk.W)

        # 로그
        ttk.Label(main_frame, text="로그:").grid(row=10, column=0, sticky=tk.W, pady=(10, 0))
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=11, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        self.log_text = tk.Text(log_frame, height=12, width=85)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 그리드 가중치
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(11, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

    def browse_clip(self):
        filename = filedialog.askopenfilename(
            title="BRAW 파일 선택",
            filetypes=[("BRAW files", "*.braw"), ("All files", "*.*")]
        )
        if filename:
            self.clip_var.set(filename)

    def browse_output(self):
        directory = filedialog.askdirectory(title="출력 폴더 선택")
        if directory:
            self.output_var.set(directory)

    def toggle_all_frames(self):
        """전체 체크박스 토글"""
        if self.all_frames_var.get():
            # 전체 선택 시 자동으로 클립 정보 가져오기
            self.fetch_clip_info()
        else:
            # 전체 해제 시 수동 입력 가능하도록 활성화
            pass

    def fetch_clip_info(self):
        """BRAW 파일에서 프레임 정보 가져오기"""
        clip_path = self.clip_var.get()
        if not clip_path:
            messagebox.showwarning("경고", "BRAW 파일을 먼저 선택하세요.")
            return

        clip = Path(clip_path)
        if not clip.exists():
            messagebox.showerror("오류", f"파일이 존재하지 않습니다: {clip_path}")
            return

        try:
            cmd = [str(self.cli_path), str(clip), "--info"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )

            if result.returncode != 0:
                messagebox.showerror("오류", f"클립 정보를 가져올 수 없습니다.\n{result.stderr}")
                return

            # 출력 파싱
            info = {}
            for line in result.stdout.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key] = value

            if 'FRAME_COUNT' in info:
                frame_count = int(info['FRAME_COUNT'])
                self.start_var.set("0")
                self.end_var.set(str(frame_count - 1))

                stereo = info.get('STEREO', 'false') == 'true'
                if stereo:
                    self.left_var.set(True)
                    self.right_var.set(True)

                messagebox.showinfo("정보",
                    f"프레임 수: {frame_count}\n"
                    f"해상도: {info.get('WIDTH', '?')}x{info.get('HEIGHT', '?')}\n"
                    f"프레임률: {info.get('FRAME_RATE', '?')}\n"
                    f"스테레오: {'예' if stereo else '아니오'}")
            else:
                messagebox.showerror("오류", "프레임 정보를 파싱할 수 없습니다.")

        except subprocess.TimeoutExpired:
            messagebox.showerror("오류", "클립 정보 가져오기 시간 초과")
        except Exception as e:
            messagebox.showerror("오류", f"오류 발생: {str(e)}")

    def log(self, message: str, tag: str = "info"):
        self.log_queue.put((message, tag))

    def update_log(self):
        try:
            while True:
                message, tag = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, message + "\n", tag)
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self.update_log)

    def load_failed_jobs(self):
        if self.failed_log_path.exists():
            try:
                with open(self.failed_log_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        job = Job(
                            item["frame_idx"],
                            item["eye_mode"],
                            Path(item["output_file"]),
                            Path(item["clip_path"])
                        )
                        job.attempts = item.get("attempts", 0)
                        job.error_msg = item.get("error_msg", "")
                        self.failed_jobs.append(job)
                self.update_stats()
            except Exception as e:
                self.log(f"실패 로그 로드 실패: {e}", "error")

    def save_failed_jobs(self):
        try:
            data = [job.to_dict() for job in self.failed_jobs]
            with open(self.failed_log_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"실패 로그 저장 실패: {e}", "error")

    def update_stats(self):
        total = len(self.all_jobs)
        completed = self.completed_count
        failed = len(self.failed_jobs)
        pending = len(self.pending_jobs)

        self.total_var.set(f"총: {total}")
        self.completed_var.set(f"완료: {completed}")
        self.failed_count_var.set(f"실패: {failed}")
        self.pending_var.set(f"대기: {pending}")

        if total > 0:
            self.progress['value'] = (completed / total) * 100

    def clear_failed(self):
        self.failed_jobs = []
        self.update_stats()
        self.save_failed_jobs()
        self.log("실패 목록이 지워졌습니다.")

    def start_export(self):
        # 검증
        if not self.clip_var.get():
            messagebox.showerror("오류", "BRAW 파일을 선택하세요.")
            return

        if not self.left_var.get() and not self.right_var.get():
            messagebox.showerror("오류", "왼쪽 또는 오른쪽을 선택하세요.")
            return

        try:
            start_frame = int(self.start_var.get())
            end_frame = int(self.end_var.get())
            if start_frame > end_frame:
                raise ValueError()
        except ValueError:
            messagebox.showerror("오류", "프레임 범위가 올바르지 않습니다.")
            return

        # 작업 큐 생성
        clip = Path(self.clip_var.get())
        output_dir = Path(self.output_var.get())
        ext = "." + self.format_var.get()
        output_dir.mkdir(parents=True, exist_ok=True)

        self.all_jobs = []
        self.pending_jobs = []
        self.failed_jobs = []
        self.completed_count = 0

        eyes = []
        if self.left_var.get():
            eyes.append(("left", "_L"))
        if self.right_var.get():
            eyes.append(("right", "_R"))

        # 클립 파일명 (확장자 제거)
        clip_basename = clip.stem
        separate_folders = self.separate_folders_var.get()

        # L/R 폴더 생성 (옵션이 켜져 있는 경우)
        if separate_folders:
            for _, suffix in eyes:
                folder_name = "L" if suffix == "_L" else "R"
                (output_dir / folder_name).mkdir(parents=True, exist_ok=True)

        # 모든 작업 생성
        for frame_idx in range(start_frame, end_frame + 1):
            frame_num = f"{frame_idx:06d}"  # 6자리
            for eye_mode, suffix in eyes:
                if separate_folders:
                    # L/R 폴더에 저장
                    folder_name = "L" if suffix == "_L" else "R"
                    output_file = output_dir / folder_name / f"{clip_basename}_{frame_num}{ext}"
                else:
                    # 기존 방식: 파일명에 suffix 포함
                    output_file = output_dir / f"{clip_basename}{suffix}_{frame_num}{ext}"

                job = Job(frame_idx, eye_mode, output_file, clip)
                self.all_jobs.append(job)
                self.pending_jobs.append(job)

        # UI 상태 변경
        self.is_running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.update_stats()

        self.log(f"=== BRAW 세그먼트 배치 익스포트 시작 ===")
        self.log(f"파일: {clip}")
        self.log(f"출력: {output_dir}")
        self.log(f"총 작업: {len(self.all_jobs)}")
        self.log(f"세그먼트 크기: {self.segment_var.get()}")
        self.log(f"병렬 작업 수: {self.parallel_var.get()}")
        self.log(f"최대 재시도: {self.max_retry_var.get()}")
        self.log("")

        # 백그라운드 스레드 시작
        self.current_thread = threading.Thread(target=self.export_worker, daemon=True)
        self.current_thread.start()

    def stop_export(self):
        self.is_running = False
        self.status_var.set("중지 중...")
        self.stop_btn.configure(state=tk.DISABLED)

    def run_cli(self, job: Job) -> bool:
        """단일 CLI 실행"""
        cmd = [
            str(self.cli_path),
            str(job.clip_path),
            str(job.output_file),
            str(job.frame_idx),
            job.eye_mode
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

            if result.returncode == 0 and job.output_file.exists():
                job.success = True
                return True

            job.error_msg = f"exit: {result.returncode}"
            if result.stderr:
                job.error_msg = result.stderr.strip()
            return False

        except subprocess.TimeoutExpired:
            job.error_msg = "Timeout"
            return False
        except Exception as e:
            job.error_msg = str(e)
            return False

    def export_worker(self):
        """세그먼트 기반 작업 처리 (병렬)"""
        segment_size = int(self.segment_var.get())
        max_workers = int(self.parallel_var.get())
        max_retries = int(self.max_retry_var.get())

        segment_num = 0

        while self.is_running and (self.pending_jobs or self.failed_jobs):
            segment_num += 1

            # 현재 세그먼트 작업 선택
            current_segment = []

            # 먼저 실패한 작업 재시도
            retry_jobs = [j for j in self.failed_jobs if j.attempts < max_retries]
            take_from_failed = min(segment_size, len(retry_jobs))
            current_segment.extend(retry_jobs[:take_from_failed])

            # 남은 공간은 대기 작업으로 채움
            remaining = segment_size - len(current_segment)
            if remaining > 0 and self.pending_jobs:
                current_segment.extend(self.pending_jobs[:remaining])

            if not current_segment:
                break

            self.log(f"--- 세그먼트 #{segment_num} ({len(current_segment)} 작업, 병렬: {max_workers}) ---")

            # 병렬 처리
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 작업 제출
                future_to_job = {}
                for job in current_segment:
                    if not self.is_running:
                        break

                    job.attempts += 1
                    is_retry = job in self.failed_jobs

                    prefix = "↻" if is_retry else "→"
                    self.log(f"{prefix} [{job.frame_idx}] {job.eye_mode.upper()} ({job.attempts}차) 시작")

                    future = executor.submit(self.run_cli, job)
                    future_to_job[future] = job

                # 완료된 작업 처리
                for future in as_completed(future_to_job):
                    if not self.is_running:
                        break

                    job = future_to_job[future]
                    success = future.result()

                    if success:
                        size_mb = job.output_file.stat().st_size / 1024 / 1024
                        self.log(f"  ✓ [{job.frame_idx}] {job.eye_mode.upper()} {size_mb:.1f} MB")

                        # 성공 시 리스트에서 제거
                        if job in self.pending_jobs:
                            self.pending_jobs.remove(job)
                        if job in self.failed_jobs:
                            self.failed_jobs.remove(job)

                        self.completed_count += 1
                    else:
                        self.log(f"  ✗ [{job.frame_idx}] {job.eye_mode.upper()} FAIL: {job.error_msg}", "error")

                        # 실패 처리
                        if job in self.pending_jobs:
                            self.pending_jobs.remove(job)

                        if job not in self.failed_jobs:
                            self.failed_jobs.append(job)

                        # 최대 재시도 초과 시
                        if job.attempts >= max_retries:
                            self.log(f"  ⚠ [{job.frame_idx}] {job.eye_mode.upper()} 최대 재시도 횟수 초과 (포기)", "error")

                    self.update_stats()

            # 세그먼트 완료
            self.log(f"세그먼트 #{segment_num} 완료\n")

        # 최종 실패 작업 집중 재시도
        if self.is_running and self.failed_jobs:
            final_failed_jobs = [j for j in self.failed_jobs if j.attempts >= max_retries]

            if final_failed_jobs:
                self.log("")
                self.log(f"=== 최종 실패 작업 집중 재시도 ===")
                self.log(f"실패 작업 수: {len(final_failed_jobs)}")
                self.log(f"병렬 처리: {max_workers}")
                self.log("")

                # 최종 재시도 (모든 실패 작업을 한번에 병렬 처리)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_job = {}
                    for job in final_failed_jobs:
                        if not self.is_running:
                            break

                        job.attempts += 1
                        self.log(f"🔄 [{job.frame_idx}] {job.eye_mode.upper()} 최종 재시도 ({job.attempts}차)")

                        future = executor.submit(self.run_cli, job)
                        future_to_job[future] = job

                    # 완료된 작업 처리
                    for future in as_completed(future_to_job):
                        if not self.is_running:
                            break

                        job = future_to_job[future]
                        success = future.result()

                        if success:
                            size_mb = job.output_file.stat().st_size / 1024 / 1024
                            self.log(f"  ✓ [{job.frame_idx}] {job.eye_mode.upper()} 성공! {size_mb:.1f} MB")

                            self.failed_jobs.remove(job)
                            self.completed_count += 1
                        else:
                            self.log(f"  ✗ [{job.frame_idx}] {job.eye_mode.upper()} 여전히 실패: {job.error_msg}", "error")

                        self.update_stats()

                self.log(f"\n최종 재시도 완료\n")

        # 최종 결과
        self.save_failed_jobs()

        total = len(self.all_jobs)
        completed = self.completed_count
        final_failed = len(self.failed_jobs)

        self.log("")
        self.log(f"=== 전체 작업 완료 ===")
        self.log(f"완료: {completed}/{total}")
        self.log(f"최종 실패: {final_failed}")

        self.status_var.set(f"완료: {completed}/{total}, 실패: {final_failed}")

        self.is_running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = BrawBatchUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
