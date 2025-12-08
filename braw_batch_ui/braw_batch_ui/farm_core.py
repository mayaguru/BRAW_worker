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
        self.current_total_frames = 0  # 현재 작업의 전체 프레임 수

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
            "current_processed": self.current_processed,
            "current_total_frames": self.current_total_frames
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
        w.current_total_frames = data.get("current_total_frames", 0)
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
        self.use_aces = True  # ACES 색공간 변환 사용 여부
        self.color_input_space = "Linear BMD WideGamut Gen5"  # 입력 색공간
        self.color_output_space = "ACEScg"  # 출력 색공간
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
            "use_aces": self.use_aces,
            "color_input_space": self.color_input_space,
            "color_output_space": self.color_output_space,
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
        job.use_aces = data.get("use_aces", True)  # 기본값 True
        job.color_input_space = data.get("color_input_space", "Linear BMD WideGamut Gen5")
        job.color_output_space = data.get("color_output_space", "ACEScg")
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

    def is_expired(self, timeout_seconds=90):
        """타임아웃 확인 (기본 90초 - CLI 실행 30초 + 여유)"""
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

    def load_job(self, job_id: str) -> Optional[Dict]:
        """작업 정보 로드 (dict로 반환)"""
        job_file = self.config.jobs_dir / f"{job_id}.json"
        if job_file.exists():
            try:
                with open(job_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return None

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
                    # 만료된 claim 삭제
                    claim_file.unlink(missing_ok=True)
            except:
                # 읽기 실패 시 삭제 시도
                try:
                    claim_file.unlink(missing_ok=True)
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
        """프레임 완료 표시 - 항상 클레임 해제"""
        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
        with open(completed_file, 'w') as f:
            f.write(self.worker.worker_id)

        # 클레임 해제
        self.release_claim(job_id, frame_idx, eye)

    def mark_completed_if_file_exists(self, job: 'RenderJob', frame_idx: int, eye: str) -> bool:
        """파일이 실제로 존재할 때만 완료 표시, 아니면 False 반환"""
        output_file = self.get_output_file_path(job, frame_idx, eye)
        if output_file.exists():
            self.mark_completed(job.job_id, frame_idx, eye)
            return True
        else:
            # 파일 없음 - 클레임만 해제 (재시도 가능하도록)
            self.release_claim(job.job_id, frame_idx, eye)
            return False

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

    def is_job_verified(self, job_id: str) -> bool:
        """작업이 이미 검증 완료되었는지 확인"""
        verified_file = self.config.completed_dir / f"{job_id}.verified"
        return verified_file.exists()

    def claim_verification(self, job_id: str) -> bool:
        """검증 작업 클레임 (한 워커만 검증하도록)"""
        verifying_file = self.config.completed_dir / f"{job_id}.verifying"

        # 이미 검증 완료됐으면 클레임 필요 없음
        if self.is_job_verified(job_id):
            return False

        # atomic 파일 생성으로 클레임
        try:
            with open(verifying_file, 'x', encoding='utf-8') as f:
                json.dump({
                    "job_id": job_id,
                    "started_at": datetime.now().isoformat(),
                    "worker_id": self.worker.worker_id
                }, f, indent=2)
            return True
        except FileExistsError:
            return False

    def release_verification_claim(self, job_id: str):
        """검증 클레임 해제"""
        verifying_file = self.config.completed_dir / f"{job_id}.verifying"
        try:
            verifying_file.unlink(missing_ok=True)
        except:
            pass

    def is_job_complete(self, job: 'RenderJob') -> bool:
        """작업의 모든 프레임이 완료됐는지 확인 (.done 파일 기준 - 빠른 체크)"""
        expected_count = (job.end_frame - job.start_frame + 1) * len(job.eyes)
        completed_count = len(list(self.config.completed_dir.glob(f"{job.job_id}_*.done")))
        return completed_count >= expected_count

    def mark_job_verified(self, job_id: str, avg_size: float, total_files: int):
        """작업 검증 완료 표시"""
        verified_file = self.config.completed_dir / f"{job_id}.verified"
        with open(verified_file, 'w', encoding='utf-8') as f:
            json.dump({
                "job_id": job_id,
                "verified_at": datetime.now().isoformat(),
                "avg_file_size": avg_size,
                "total_files": total_files,
                "verified_by": self.worker.worker_id
            }, f, indent=2)

    def verify_job_output_files(self, job: 'RenderJob') -> Dict[str, any]:
        """실제 출력 파일 검증 - 미싱/손상 프레임 탐지 (평균 크기 기반)"""

        # 이미 검증 완료된 작업이면 스킵
        if self.is_job_verified(job.job_id):
            total_tasks = job.get_total_tasks()
            return {
                "total_expected": total_tasks,
                "total_existing": total_tasks,
                "total_missing": 0,
                "total_corrupted": 0,
                "avg_file_size": 0,
                "missing_files": [],
                "corrupted_files": [],
                "problem_files": [],
                "complete": True,
                "already_verified": True,
                "progress_percent": 100.0
            }

        output_dir = Path(job.output_dir)
        clip_basename = Path(job.clip_path).stem
        ext = ".exr" if job.format == "exr" else ".ppm"

        # 1차 스캔: 파일 존재 여부와 크기 수집
        file_info = []
        missing_files = []

        for frame_idx in range(job.start_frame, job.end_frame + 1):
            for eye in job.eyes:
                frame_num = f"{frame_idx:06d}"

                if job.separate_folders:
                    folder = "L" if eye == "left" else "R"
                    expected_path = output_dir / folder / f"{clip_basename}_{frame_num}{ext}"
                else:
                    suffix = "_L" if eye == "left" else "_R"
                    expected_path = output_dir / f"{clip_basename}{suffix}_{frame_num}{ext}"

                if expected_path.exists():
                    file_size = expected_path.stat().st_size
                    file_info.append({
                        "path": expected_path,
                        "frame": frame_idx,
                        "eye": eye,
                        "size": file_size
                    })
                else:
                    missing_files.append({
                        "path": expected_path,
                        "frame": frame_idx,
                        "eye": eye,
                        "reason": "not_found"
                    })

        # 2차 검사: 평균 크기 계산 및 이상치 탐지
        corrupted_files = []
        existing_files = []

        if file_info:
            # 평균 파일 크기 계산
            sizes = [f["size"] for f in file_info]
            avg_size = sum(sizes) / len(sizes)
            # 평균의 70% 미만이면 손상으로 간주 (30% 이상 작으면)
            min_acceptable_size = avg_size * 0.7

            for f in file_info:
                if f["size"] < min_acceptable_size:
                    corrupted_files.append({
                        "path": f["path"],
                        "frame": f["frame"],
                        "eye": f["eye"],
                        "size": f["size"],
                        "avg_size": avg_size,
                        "reason": "too_small"
                    })
                else:
                    existing_files.append(f["path"])
        else:
            avg_size = 0

        # 손상된 파일도 문제 파일로 합산
        all_problem_files = missing_files + corrupted_files
        total_expected = len(file_info) + len(missing_files)
        total_existing = len(existing_files)
        total_missing = len(missing_files)
        total_corrupted = len(corrupted_files)
        is_complete = len(all_problem_files) == 0

        # 검증 완료되면 마커 파일 생성
        if is_complete and total_expected > 0:
            self.mark_job_verified(job.job_id, avg_size, total_expected)

        return {
            "total_expected": total_expected,
            "total_existing": total_existing,
            "total_missing": total_missing,
            "total_corrupted": total_corrupted,
            "avg_file_size": avg_size,
            "missing_files": missing_files,
            "corrupted_files": corrupted_files,
            "problem_files": all_problem_files,  # 재처리 대상
            "complete": is_complete,
            "already_verified": False,
            "progress_percent": (total_existing / total_expected * 100) if total_expected > 0 else 0
        }

    def repair_missing_frames(self, job: 'RenderJob') -> int:
        """미싱/손상 프레임의 .done 파일 삭제하여 재처리 유도"""
        verify_result = self.verify_job_output_files(job)
        repaired_count = 0

        # 미싱 + 손상 파일 모두 처리
        for problem in verify_result["problem_files"]:
            frame_idx = problem["frame"]
            eye = problem["eye"]

            # 손상된 파일이면 삭제
            if problem.get("reason") == "too_small":
                try:
                    problem["path"].unlink()
                except:
                    pass

            # .done 파일 삭제 (재처리 유도)
            done_file = self.config.completed_dir / f"{job.job_id}_{frame_idx:06d}_{eye}.done"
            if done_file.exists():
                try:
                    done_file.unlink()
                    repaired_count += 1
                except:
                    pass

            # claim 파일도 삭제 (다시 클레임 가능하게)
            claim_file = self.config.claims_dir / f"{job.job_id}_{frame_idx:06d}_{eye}.json"
            if claim_file.exists():
                try:
                    claim_file.unlink()
                except:
                    pass

        return repaired_count

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

    def get_output_file_path(self, job: RenderJob, frame_idx: int, eye: str) -> Path:
        """출력 파일 경로 계산"""
        output_dir = Path(job.output_dir)
        clip_basename = Path(job.clip_path).stem
        ext = ".exr" if job.format == "exr" else ".ppm"

        if job.separate_folders:
            folder = "L" if eye == "left" else "R"
            return output_dir / folder / f"{clip_basename}_{frame_idx:06d}{ext}"
        else:
            suffix = "_L" if eye == "left" else "_R"
            return output_dir / f"{clip_basename}{suffix}_{frame_idx:06d}{ext}"

    def is_frame_really_complete(self, job: RenderJob, frame_idx: int, eye: str) -> bool:
        """프레임이 진짜 완료됐는지 확인 (.done 파일 + 실제 출력 파일 존재)"""
        # .done 파일 확인
        if not self.is_frame_completed(job.job_id, frame_idx, eye):
            return False

        # 실제 출력 파일 존재 확인
        output_file = self.get_output_file_path(job, frame_idx, eye)
        if not output_file.exists():
            # .done 파일만 있고 실제 파일이 없으면 .done 삭제 (재처리 유도)
            done_file = self.config.completed_dir / f"{job.job_id}_{frame_idx:06d}_{eye}.done"
            try:
                done_file.unlink(missing_ok=True)
            except:
                pass
            return False

        return True

    def find_next_frame(self, job: RenderJob) -> Optional[Tuple[int, str]]:
        """다음 처리할 프레임 찾기 (최적화: .done 파일만 확인)"""
        for frame_idx in range(job.start_frame, job.end_frame + 1):
            for eye in job.eyes:
                # 빠른 체크: .done 파일만 확인 (네트워크 부하 감소)
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
