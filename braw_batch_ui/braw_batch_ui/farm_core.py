#!/usr/bin/env python3
"""
BRAW Render Farm Core
공유 폴더 기반 분산 렌더링 시스템
"""

import json
import socket
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime
import threading
import psutil

from config import settings


class FarmConfig:
    """렌더팜 설정 (settings에서 가져옴)"""
    def __init__(self, farm_root: str = None):
        # settings에서 farm_root 사용
        self.farm_root = Path(settings.farm_root) if farm_root is None else Path(farm_root)
        self.jobs_dir = self.farm_root / "jobs"
        self.claims_dir = self.farm_root / "claims"
        self.workers_dir = self.farm_root / "workers"
        self.completed_dir = self.farm_root / "completed"

        # 디렉토리 생성
        for d in [self.jobs_dir, self.claims_dir, self.workers_dir, self.completed_dir]:
            d.mkdir(parents=True, exist_ok=True)


class WorkerInfo:
    """워커 PC 정보"""
    def __init__(self):
        self.worker_id = socket.gethostname()
        self.ip = self.get_ip()
        self.last_heartbeat = datetime.now()
        self.status = "idle"  # idle, active
        self.frames_processing = 0
        self.frames_completed = 0
        self.cpu_usage = 0.0
        self.current_job_id = ""
        self.current_clip_name = ""
        self.total_errors = 0
        self.current_processed = 0

    @staticmethod
    def get_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def to_dict(self):
        return {
            "worker_id": self.worker_id,
            "ip": self.ip,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "status": self.status,
            "frames_processing": self.frames_processing,
            "frames_completed": self.frames_completed,
            "cpu_usage": self.cpu_usage,
            "current_job_id": self.current_job_id,
            "current_clip_name": self.current_clip_name,
            "total_errors": self.total_errors,
            "current_processed": self.current_processed
        }

    @classmethod
    def from_dict(cls, data):
        w = cls()
        w.worker_id = data["worker_id"]
        w.ip = data["ip"]
        w.last_heartbeat = datetime.fromisoformat(data["last_heartbeat"])
        w.status = data["status"]
        w.frames_processing = data.get("frames_processing", 0)
        w.frames_completed = data.get("frames_completed", 0)
        w.cpu_usage = data.get("cpu_usage", 0.0)
        w.current_job_id = data.get("current_job_id", "")
        w.current_clip_name = data.get("current_clip_name", "")
        w.total_errors = data.get("total_errors", 0)
        w.current_processed = data.get("current_processed", 0)
        return w


class RenderJob:
    """렌더 작업 정보"""
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.clip_path = ""
        self.output_dir = ""
        self.start_frame = 0
        self.end_frame = 0
        self.eyes = ["left", "right"]
        self.format = "exr"
        self.separate_folders = False
        self.created_at = datetime.now()
        self.created_by = socket.gethostname()

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "clip_path": self.clip_path,
            "output_dir": self.output_dir,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "eyes": self.eyes,
            "format": self.format,
            "separate_folders": self.separate_folders,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data):
        job = cls(data["job_id"])
        job.clip_path = data["clip_path"]
        job.output_dir = data["output_dir"]
        job.start_frame = data["start_frame"]
        job.end_frame = data["end_frame"]
        job.eyes = data["eyes"]
        job.format = data["format"]
        job.separate_folders = data["separate_folders"]
        job.created_at = datetime.fromisoformat(data["created_at"])
        job.created_by = data["created_by"]
        return job

    def get_total_tasks(self):
        """전체 작업 수 (프레임 x 눈)"""
        frame_count = self.end_frame - self.start_frame + 1
        return frame_count * len(self.eyes)


class FrameClaim:
    """프레임 클레임 (중복 방지용)"""
    def __init__(self, job_id: str, frame_idx: int, eye: str, worker_id: str):
        self.job_id = job_id
        self.frame_idx = frame_idx
        self.eye = eye
        self.worker_id = worker_id
        self.claimed_at = datetime.now()

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "frame_idx": self.frame_idx,
            "eye": self.eye,
            "worker_id": self.worker_id,
            "claimed_at": self.claimed_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        claim = cls(data["job_id"], data["frame_idx"], data["eye"], data["worker_id"])
        claim.claimed_at = datetime.fromisoformat(data["claimed_at"])
        return claim

    def is_expired(self, timeout_seconds=300):
        """타임아웃 확인 (기본 5분)"""
        elapsed = (datetime.now() - self.claimed_at).total_seconds()
        return elapsed > timeout_seconds


class FarmManager:
    """렌더팜 관리자"""

    def __init__(self, farm_root: str = None):
        # farm_root가 None이면 settings.farm_root 사용
        self.config = FarmConfig(farm_root)
        self.worker = WorkerInfo()
        self.heartbeat_thread = None
        self.is_running = False
        self.network_connected = True
        self.last_job_id = None  # 마지막 작업 ID 저장

    def start(self):
        """워커 시작"""
        self.is_running = True
        self.register_worker()
        self.start_heartbeat()

    def stop(self):
        """워커 정지"""
        self.is_running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=2)
        self.worker.status = "offline"
        self.update_worker()

    def register_worker(self):
        """워커 등록"""
        worker_file = self.config.workers_dir / f"{self.worker.worker_id}.json"
        with open(worker_file, 'w', encoding='utf-8') as f:
            json.dump(self.worker.to_dict(), f, indent=2)

    def update_worker(self):
        """워커 상태 업데이트"""
        self.worker.last_heartbeat = datetime.now()
        # CPU 사용률 업데이트
        try:
            self.worker.cpu_usage = psutil.cpu_percent(interval=0.1)
        except:
            self.worker.cpu_usage = 0.0
        worker_file = self.config.workers_dir / f"{self.worker.worker_id}.json"
        with open(worker_file, 'w', encoding='utf-8') as f:
            json.dump(self.worker.to_dict(), f, indent=2)

    def start_heartbeat(self):
        """하트비트 시작 (30초마다)"""
        def heartbeat_loop():
            while self.is_running:
                self.update_worker()
                time.sleep(30)

        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def get_active_workers(self) -> List[WorkerInfo]:
        """활성 워커 목록 (최근 2분 이내)"""
        workers = []
        for worker_file in self.config.workers_dir.glob("*.json"):
            try:
                with open(worker_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    worker = WorkerInfo.from_dict(data)
                    elapsed = (datetime.now() - worker.last_heartbeat).total_seconds()
                    if elapsed < 120:  # 2분 이내
                        workers.append(worker)
            except:
                pass
        return workers

    def submit_job(self, job: RenderJob):
        """작업 제출"""
        job_file = self.config.jobs_dir / f"{job.job_id}.json"
        with open(job_file, 'w', encoding='utf-8') as f:
            json.dump(job.to_dict(), f, indent=2)

    def get_pending_jobs(self) -> List[RenderJob]:
        """대기중인 작업 목록"""
        jobs = []
        for job_file in self.config.jobs_dir.glob("*.json"):
            try:
                with open(job_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    jobs.append(RenderJob.from_dict(data))
            except:
                pass
        return jobs

    def claim_frame(self, job_id: str, frame_idx: int, eye: str) -> bool:
        """프레임 클레임 시도 (atomic)"""
        claim = FrameClaim(job_id, frame_idx, eye, self.worker.worker_id)
        claim_file = self.config.claims_dir / f"{job_id}_{frame_idx:06d}_{eye}.json"

        # 이미 완료된 프레임인지 확인
        if self.is_frame_completed(job_id, frame_idx, eye):
            return False

        # 기존 클레임 확인
        if claim_file.exists():
            try:
                with open(claim_file, 'r', encoding='utf-8') as f:
                    existing = FrameClaim.from_dict(json.load(f))
                    # 타임아웃되지 않았으면 실패
                    if not existing.is_expired():
                        return False
            except:
                pass

        # 클레임 시도 (x 모드로 atomic)
        try:
            with open(claim_file, 'x', encoding='utf-8') as f:
                json.dump(claim.to_dict(), f, indent=2)
            return True
        except FileExistsError:
            return False

    def release_claim(self, job_id: str, frame_idx: int, eye: str):
        """클레임 해제"""
        claim_file = self.config.claims_dir / f"{job_id}_{frame_idx:06d}_{eye}.json"
        try:
            # missing_ok=True: 파일이 없어도 에러 안남
            claim_file.unlink(missing_ok=True)
        except Exception as e:
            # 권한 문제나 다른 에러도 무시 (다른 워커가 삭제했을 수 있음)
            pass

    def mark_completed(self, job_id: str, frame_idx: int, eye: str):
        """프레임 완료 표시"""
        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
        with open(completed_file, 'w') as f:
            f.write(self.worker.worker_id)

        # 클레임 해제
        self.release_claim(job_id, frame_idx, eye)

    def is_frame_completed(self, job_id: str, frame_idx: int, eye: str) -> bool:
        """프레임 완료 여부 확인"""
        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
        return completed_file.exists()

    def get_job_progress(self, job_id: str) -> Dict[str, int]:
        """작업 진행률"""
        completed = len(list(self.config.completed_dir.glob(f"{job_id}_*.done")))
        claimed = len(list(self.config.claims_dir.glob(f"{job_id}_*.json")))

        return {
            "completed": completed,
            "claimed": claimed,
            "processing": claimed  # claimed = 현재 처리중
        }

    def cleanup_expired_claims(self):
        """만료된 클레임 정리"""
        for claim_file in self.config.claims_dir.glob("*.json"):
            try:
                with open(claim_file, 'r', encoding='utf-8') as f:
                    claim = FrameClaim.from_dict(json.load(f))
                    if claim.is_expired():
                        # missing_ok=True: 다른 워커가 이미 삭제했을 수 있음
                        claim_file.unlink(missing_ok=True)
            except Exception as e:
                # 파일 읽기/삭제 중 에러 무시 (다른 워커가 처리중일 수 있음)
                pass

    def find_next_frame(self, job: RenderJob) -> Optional[Tuple[int, str]]:
        """다음 처리할 프레임 찾기"""
        for frame_idx in range(job.start_frame, job.end_frame + 1):
            for eye in job.eyes:
                # 완료되지 않았고 클레임되지 않은 프레임 찾기
                if not self.is_frame_completed(job.job_id, frame_idx, eye):
                    if self.claim_frame(job.job_id, frame_idx, eye):
                        return (frame_idx, eye)
        return None

    def check_network_connection(self) -> bool:
        """네트워크 연결 확인"""
        try:
            # jobs 폴더에 접근 시도
            list(self.config.jobs_dir.glob("*.json"))
            self.network_connected = True
            return True
        except (OSError, PermissionError):
            self.network_connected = False
            return False

    def get_last_job(self) -> Optional[RenderJob]:
        """마지막 작업 가져오기"""
        if not self.last_job_id:
            return None

        try:
            job_file = self.config.jobs_dir / f"{self.last_job_id}.json"
            if job_file.exists():
                with open(job_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return RenderJob.from_dict(data)
        except:
            pass
        return None

    def release_my_claims(self):
        """내 워커의 모든 클레임 해제 (네트워크 복구 시)"""
        try:
            for claim_file in self.config.claims_dir.glob("*.json"):
                try:
                    with open(claim_file, 'r', encoding='utf-8') as f:
                        claim = FrameClaim.from_dict(json.load(f))
                        if claim.worker_id == self.worker.worker_id:
                            claim_file.unlink(missing_ok=True)
                except:
                    pass
        except:
            pass

    def delete_job(self, job_id: str):
        """작업 삭제"""
        try:
            # 작업 파일 삭제
            job_file = self.config.jobs_dir / f"{job_id}.json"
            job_file.unlink(missing_ok=True)

            # 관련 클레임 삭제
            for claim_file in self.config.claims_dir.glob(f"{job_id}_*.json"):
                claim_file.unlink(missing_ok=True)

            # 관련 완료 파일 삭제
            for done_file in self.config.completed_dir.glob(f"{job_id}_*.done"):
                done_file.unlink(missing_ok=True)
        except Exception as e:
            pass

    def reset_job(self, job_id: str):
        """작업 리셋 (클레임 및 완료 정보 초기화)"""
        try:
            # 클레임 삭제
            for claim_file in self.config.claims_dir.glob(f"{job_id}_*.json"):
                claim_file.unlink(missing_ok=True)

            # 완료 파일 삭제
            for done_file in self.config.completed_dir.glob(f"{job_id}_*.done"):
                done_file.unlink(missing_ok=True)
        except Exception as e:
            pass

    def mark_job_completed(self, job_id: str):
        """작업을 완료로 표시 (모든 프레임 완료 처리)"""
        try:
            # 작업 정보 가져오기
            job_file = self.config.jobs_dir / f"{job_id}.json"
            if not job_file.exists():
                return

            with open(job_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                job = RenderJob.from_dict(data)

            # 모든 프레임을 완료로 표시
            for frame_idx in range(job.start_frame, job.end_frame + 1):
                for eye in job.eyes:
                    if not self.is_frame_completed(job_id, frame_idx, eye):
                        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
                        with open(completed_file, 'w') as f:
                            f.write("manual_complete")

            # 모든 클레임 해제
            for claim_file in self.config.claims_dir.glob(f"{job_id}_*.json"):
                claim_file.unlink(missing_ok=True)
        except Exception as e:
            pass
