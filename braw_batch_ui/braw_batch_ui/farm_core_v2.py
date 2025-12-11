#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BRAW Render Farm Core V2 - SQLite DB 기반
다중 워커 동시 접근 최적화, Pool 시스템 지원
"""

import os
import socket
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

from .config import settings, CLAIM_TIMEOUT_SEC, HEARTBEAT_INTERVAL_SEC
from .farm_db import (
    FarmDatabase, init_database, get_database, get_default_db_path,
    Pool, Job, Worker, JobStatus, FrameStatus
)


def get_local_ip() -> str:
    """로컬 IP 주소 반환"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class FarmManagerV2:
    """렌더팜 매니저 V2 - DB 기반"""

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: SQLite DB 파일 경로. None이면 환경변수 BRAW_FARM_DB 또는 기본값 사용
        """
        if db_path is None:
            db_path = get_default_db_path()

        self.db = init_database(db_path)
        self.worker_id = f"{socket.gethostname()}_{get_local_ip()}"
        self.hostname = socket.gethostname()
        self.ip = get_local_ip()
        self.current_pool_id = "default"
        self.is_running = False

        # 워커 등록
        self._register_worker()

    def _register_worker(self):
        """워커 등록"""
        worker = Worker(
            worker_id=self.worker_id,
            pool_id=self.current_pool_id,
            hostname=self.hostname,
            ip=self.ip,
            status="idle",
            last_heartbeat=datetime.now()
        )
        self.db.register_worker(worker)

    def set_pool(self, pool_id: str):
        """워커의 풀 변경"""
        self.current_pool_id = pool_id
        self.db.register_worker(Worker(
            worker_id=self.worker_id,
            pool_id=pool_id,
            hostname=self.hostname,
            ip=self.ip,
            status="idle",
            last_heartbeat=datetime.now()
        ))

    def start(self):
        """워커 시작"""
        self.is_running = True
        self.update_heartbeat("active")

    def stop(self):
        """워커 중지"""
        self.is_running = False
        self.update_heartbeat("idle")

    def update_heartbeat(self, status: str = "active", current_job_id: str = "", frames_completed: int = 0):
        """하트비트 업데이트"""
        self.db.update_heartbeat(self.worker_id, status, current_job_id, frames_completed)

    # ===== Pool 관리 =====

    def get_pools(self) -> List[Pool]:
        """모든 풀 조회"""
        return self.db.get_pools()

    def create_pool(self, pool_id: str, name: str, description: str = "", priority: int = 50) -> bool:
        """풀 생성"""
        pool = Pool(
            pool_id=pool_id,
            name=name,
            description=description,
            priority=priority,
            created_at=datetime.now()
        )
        return self.db.create_pool(pool)

    def delete_pool(self, pool_id: str) -> bool:
        """풀 삭제"""
        return self.db.delete_pool(pool_id)

    def get_pool_stats(self, pool_id: str) -> Dict:
        """풀 통계"""
        return self.db.get_pool_stats(pool_id)

    # ===== Job 관리 =====

    def submit_job(self, clip_path: str, output_dir: str, start_frame: int, end_frame: int,
                   eyes: List[str], pool_id: str = None, **kwargs) -> str:
        """작업 제출

        Returns:
            job_id
        """
        if pool_id is None:
            pool_id = self.current_pool_id

        job_id = f"job_{int(datetime.now().timestamp() * 1000)}_{Path(clip_path).stem}"

        job = Job(
            job_id=job_id,
            pool_id=pool_id,
            clip_path=clip_path,
            output_dir=output_dir,
            start_frame=start_frame,
            end_frame=end_frame,
            eyes=eyes,
            format=kwargs.get('format', 'exr'),
            separate_folders=kwargs.get('separate_folders', False),
            use_aces=kwargs.get('use_aces', True),
            color_input_space=kwargs.get('color_input_space', 'BMDFilm WideGamut Gen5'),
            color_output_space=kwargs.get('color_output_space', 'ACEScg'),
            use_stmap=kwargs.get('use_stmap', False),
            stmap_path=kwargs.get('stmap_path', ''),
            priority=kwargs.get('priority', 50),
            created_at=datetime.now(),
            created_by=self.hostname
        )

        self.db.submit_job(job)
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """작업 조회"""
        return self.db.get_job(job_id)

    def get_jobs_by_pool(self, pool_id: str = None, include_excluded: bool = False) -> List[Job]:
        """풀별 작업 목록"""
        if pool_id is None:
            pool_id = self.current_pool_id
        return self.db.get_jobs_by_pool(pool_id, include_excluded)

    def get_all_jobs_with_status(self, include_excluded: bool = True) -> List[Tuple[Job, str, int, int]]:
        """모든 작업 + 상태"""
        return self.db.get_all_jobs(include_excluded)

    def set_job_status(self, job_id: str, status: str):
        """작업 상태 변경"""
        status_map = {
            'pending': JobStatus.PENDING,
            'in_progress': JobStatus.IN_PROGRESS,
            'completed': JobStatus.COMPLETED,
            'excluded': JobStatus.EXCLUDED,
            'paused': JobStatus.PAUSED,
            'failed': JobStatus.FAILED
        }
        if status in status_map:
            self.db.set_job_status(job_id, status_map[status])

    def exclude_job(self, job_id: str):
        """작업 제외"""
        self.db.set_job_status(job_id, JobStatus.EXCLUDED)

    def activate_job(self, job_id: str):
        """작업 활성화"""
        self.db.set_job_status(job_id, JobStatus.PENDING)

    def pause_job(self, job_id: str):
        """작업 일시정지"""
        self.db.set_job_status(job_id, JobStatus.PAUSED)

    def set_job_priority(self, job_id: str, priority: int):
        """작업 우선순위 변경"""
        self.db.set_job_priority(job_id, priority)

    def move_job_to_pool(self, job_id: str, pool_id: str):
        """작업 풀 이동"""
        self.db.move_job_to_pool(job_id, pool_id)

    def delete_job(self, job_id: str):
        """작업 삭제"""
        self.db.delete_job(job_id)

    def reset_job(self, job_id: str):
        """작업 리셋"""
        self.db.reset_job(job_id)

    def get_job_progress(self, job_id: str) -> Dict[str, int]:
        """작업 진행률"""
        return self.db.get_job_progress(job_id)

    def get_job_eye_progress(self, job_id: str) -> Dict[str, Dict[str, int]]:
        """작업별 눈(eye) 진행률 조회"""
        return self.db.get_job_eye_progress(job_id)

    def get_active_workers(self) -> List[Worker]:
        """활성 워커 목록"""
        return self.db.get_active_workers()

    def is_job_complete(self, job: Job) -> bool:
        """작업 완료 여부"""
        progress = self.get_job_progress(job.job_id)
        return progress['completed'] >= progress['total'] and progress['total'] > 0

    # ===== Frame 처리 (워커용) =====

    def claim_frames(self, batch_size: int = None) -> Optional[Tuple[str, int, int, str]]:
        """프레임 범위 클레임

        Returns:
            (job_id, start_frame, end_frame, eye) 또는 None
        """
        if batch_size is None:
            batch_size = settings.batch_frame_size

        return self.db.claim_frames(self.current_pool_id, self.worker_id, batch_size)

    def complete_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str):
        """프레임 범위 완료"""
        self.db.complete_frames(job_id, start_frame, end_frame, eye, self.worker_id)

    def release_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str):
        """프레임 범위 클레임 해제 (실패 시)"""
        self.db.release_frames(job_id, start_frame, end_frame, eye, self.worker_id)

    # ===== Worker 관리 =====

    def get_workers_by_pool(self, pool_id: str = None) -> List[Worker]:
        """풀별 워커 목록"""
        if pool_id is None:
            pool_id = self.current_pool_id
        return self.db.get_workers_by_pool(pool_id)

    def get_all_workers(self) -> List[Worker]:
        """모든 워커 목록"""
        return self.db.get_all_workers()

    def cleanup_offline_workers(self):
        """오프라인 워커 정리"""
        self.db.cleanup_offline_workers()

    # ===== 유틸리티 =====

    def get_output_file_path(self, job: Job, frame_idx: int, eye: str) -> Path:
        """출력 파일 경로 계산

        CLI 출력 패턴:
        - SBS: {output_dir}/SBS/{clip}_{frame:06d}.exr (항상 SBS 폴더)
        - Left: {output_dir}/L/{clip}_{frame:06d}.exr (폴더분리시)
        - Right: {output_dir}/R/{clip}_{frame:06d}.exr (폴더분리시)
        - Left/Right 폴더분리 안할때: {output_dir}/{clip}_L_{frame:06d}.exr
        """
        output_dir = Path(job.output_dir)
        clip_basename = Path(job.clip_path).stem
        ext = ".exr" if job.format == "exr" else ".ppm"
        filename = f"{clip_basename}_{frame_idx:06d}{ext}"

        if eye == "sbs":
            # SBS는 항상 SBS 폴더
            return output_dir / "SBS" / filename
        elif job.separate_folders:
            # L/R 폴더 분리
            folder = "L" if eye == "left" else "R"
            return output_dir / folder / filename
        else:
            # L/R 접미사로 구분
            suffix = "_L" if eye == "left" else "_R"
            return output_dir / f"{clip_basename}{suffix}_{frame_idx:06d}{ext}"

    def close(self):
        """리소스 정리"""
        self.update_heartbeat("offline")
        self.db.close()


# 편의 함수
def create_farm_manager(db_path: str = None) -> FarmManagerV2:
    """FarmManager 인스턴스 생성"""
    return FarmManagerV2(db_path)
