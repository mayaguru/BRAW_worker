#!/usr/bin/env python3
"""
BRAW Batch Export UI
새로운 범위 기반 CLI 인터페이스 사용 (클립 한 번 열고 연속 처리)
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
import re


class BatchJob:
    """배치 작업 정의 (프레임 범위 단위)"""
    def __init__(self, clip_path: Path, output_dir: Path, start_frame: int, end_frame: int, eye_mode: str):
        self.clip_path = clip_path
        self.output_dir = output_dir
        self.start_frame = start_frame
        self.end_frame = end_frame
        self.eye_mode = eye_mode  # "left", "right", "both"
        self.success = False
        self.completed_frames = 0
        self.total_frames = end_frame - start_frame + 1
        self.error_msg = ""


class BrawBatchUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BRAW Batch Export - Range Mode")
        self.root.geometry("800x600")

        # CLI 경로
        self.cli_path = Path(__file__).parents[2] / "build" / "bin" / "braw_cli.exe"

        # 상태
        self.is_running = False
        self.current_process: Optional[subprocess.Popen] = None
        self.current_thread: Optional[threading.Thread] = None
        self.log_queue = queue.Queue()

        self.setup_ui()
        self.update_log()

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
        self.eye_var = tk.StringVar(value="both")
        ttk.Radiobutton(eye_frame, text="양쪽 (L+R)", variable=self.eye_var, value="both").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(eye_frame, text="왼쪽 (L)", variable=self.eye_var, value="left").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(eye_frame, text="오른쪽 (R)", variable=self.eye_var, value="right").pack(side=tk.LEFT, padx=10)

        # 포맷 선택
        format_frame = ttk.Frame(main_frame)
        format_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=10)

        ttk.Label(format_frame, text="출력 포맷:").pack(side=tk.LEFT, padx=5)
        self.format_var = tk.StringVar(value="exr")
        ttk.Radiobutton(format_frame, text="EXR (Half/DWAA)", variable=self.format_var, value="exr").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(format_frame, text="PPM", variable=self.format_var, value="ppm").pack(side=tk.LEFT, padx=10)

        # 색공간 옵션
        color_frame = ttk.Frame(main_frame)
        color_frame.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=10)

        self.aces_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(color_frame, text="ACES 색공간 변환", variable=self.aces_var).pack(side=tk.LEFT, padx=5)

        self.gamma_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(color_frame, text="Rec.709 감마", variable=self.gamma_var).pack(side=tk.LEFT, padx=20)

        # 시작/중지 버튼
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=15)

        self.start_btn = ttk.Button(button_frame, text="시작", command=self.start_export)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(button_frame, text="중지", command=self.stop_export, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # 진행 상황
        ttk.Label(main_frame, text="진행 상황:").grid(row=7, column=0, sticky=tk.W)
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.grid(row=7, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        self.status_var = tk.StringVar(value="대기 중...")
        ttk.Label(main_frame, textvariable=self.status_var).grid(row=8, column=0, columnspan=3, sticky=tk.W)

        # 로그
        ttk.Label(main_frame, text="로그:").grid(row=9, column=0, sticky=tk.W, pady=(10, 0))
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=10, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        self.log_text = tk.Text(log_frame, height=15, width=85)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 그리드 가중치
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(10, weight=1)
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
            self.fetch_clip_info()

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
                    self.eye_var.set("both")

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

    def start_export(self):
        # 검증
        if not self.clip_var.get():
            messagebox.showerror("오류", "BRAW 파일을 선택하세요.")
            return

        try:
            start_frame = int(self.start_var.get())
            end_frame = int(self.end_var.get())
            if start_frame > end_frame:
                raise ValueError()
        except ValueError:
            messagebox.showerror("오류", "프레임 범위가 올바르지 않습니다.")
            return

        clip = Path(self.clip_var.get())
        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        # UI 상태 변경
        self.is_running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.progress['value'] = 0

        eye_mode = self.eye_var.get()
        total_frames = end_frame - start_frame + 1
        total_outputs = total_frames * (2 if eye_mode == "both" else 1)

        self.log(f"=== BRAW Batch Export (Range Mode) ===")
        self.log(f"파일: {clip}")
        self.log(f"출력: {output_dir}")
        self.log(f"프레임: {start_frame} ~ {end_frame} ({total_frames} frames)")
        self.log(f"눈: {eye_mode}")
        self.log(f"예상 출력: {total_outputs} 파일")
        self.log("")

        # 작업 생성
        job = BatchJob(clip, output_dir, start_frame, end_frame, eye_mode)

        # 백그라운드 스레드 시작
        self.current_thread = threading.Thread(target=self.export_worker, args=(job,), daemon=True)
        self.current_thread.start()

    def stop_export(self):
        self.is_running = False
        self.status_var.set("중지 중...")
        self.stop_btn.configure(state=tk.DISABLED)

        # 현재 프로세스 종료
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
            except:
                self.current_process.kill()

    def export_worker(self, job: BatchJob):
        """범위 기반 CLI 실행"""
        start_time = time.time()

        # CLI 명령 구성
        # braw_cli <clip.braw> <output_dir> <start-end> <eye> [options]
        cmd = [
            str(self.cli_path),
            str(job.clip_path),
            str(job.output_dir),
            f"{job.start_frame}-{job.end_frame}",
            job.eye_mode
        ]

        # 옵션 추가
        cmd.append(f"--format={self.format_var.get()}")

        if self.aces_var.get():
            cmd.append("--aces")

        if self.gamma_var.get():
            cmd.append("--gamma")

        self.log(f"실행: {' '.join(cmd)}")
        self.log("")

        try:
            # 프로세스 시작 (실시간 출력)
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )

            # 실시간 출력 읽기
            progress_pattern = re.compile(r'\[(\d+)%\]')

            for line in self.current_process.stdout:
                if not self.is_running:
                    break

                line = line.strip()
                if not line:
                    continue

                # 진행률 파싱
                match = progress_pattern.search(line)
                if match:
                    pct = int(match.group(1))
                    self.progress['value'] = pct
                    self.status_var.set(line)
                else:
                    self.log(line)

            self.current_process.wait()
            returncode = self.current_process.returncode

            elapsed = time.time() - start_time

            self.log("")
            if returncode == 0:
                self.log(f"✓ 성공! (소요시간: {elapsed:.1f}초)")
                job.success = True
            else:
                self.log(f"✗ 실패 (exit code: {returncode})", "error")
                job.success = False

        except Exception as e:
            self.log(f"오류: {str(e)}", "error")
            job.success = False

        finally:
            self.current_process = None
            self.is_running = False
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)

            if job.success:
                self.progress['value'] = 100
                self.status_var.set("완료!")
            else:
                self.status_var.set("실패")


def main():
    root = tk.Tk()
    app = BrawBatchUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
