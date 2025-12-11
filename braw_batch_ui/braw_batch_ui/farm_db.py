#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BRAW Render Farm Database Module
SQLite 기반 작업 관리 시스템 - 다중 워커 동시 접근 최적화
"""

import sqlite3
import threading
import socket
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(Enum):
    """작업 상태"""
    PENDING = "pending"          # 대기 중
    IN_PROGRESS = "in_progress"  # 처리 중
    COMPLETED = "completed"      # 완료
    EXCLUDED = "excluded"        # 제외됨 (처리 안함)
    PAUSED = "paused"           # 일시정지
    FAILED = "failed"           # 실패


class FrameStatus(Enum):
    """프레임 상태"""
    PENDING = "pending"          # 대기 중
    CLAIMED = "claimed"          # 클레임됨 (처리 중)
    COMPLETED = "completed"      # 완료
    FAILED = "failed"           # 실패


@dataclass
class Pool:
    """워커 풀 (작업 구역)"""
    pool_id: str
    name: str
    description: str = ""
    priority: int = 50  # 0-100, 높을수록 우선
    max_workers: int = 0  # 0 = 무제한
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Job:
    """렌더 작업"""
    job_id: str
    pool_id: str  # 작업 풀
    clip_path: str
    output_dir: str
    start_frame: int
    end_frame: int
    eyes: List[str]
    format: str = "exr"
    separate_folders: bool = False
    use_aces: bool = True
    color_input_space: str = "BMDFilm WideGamut Gen5"
    color_output_space: str = "ACEScg"
    use_stmap: bool = False
    stmap_path: str = ""
    status: JobStatus = JobStatus.PENDING
    priority: int = 50  # 0-100
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""

    def get_total_frames(self) -> int:
        return (self.end_frame - self.start_frame + 1) * len(self.eyes)


@dataclass
class Worker:
    """워커 정보"""
    worker_id: str
    pool_id: str  # 소속 풀
    hostname: str
    ip: str = ""
    status: str = "idle"  # idle, active, offline
    current_job_id: str = ""
    frames_completed: int = 0
    last_heartbeat: datetime = field(default_factory=datetime.now)


class FarmDatabase:
    """렌더팜 데이터베이스 관리자"""

    # 클레임 타임아웃 (초)
    CLAIM_TIMEOUT_SEC = 180  # 3분
    HEARTBEAT_TIMEOUT_SEC = 300  # 2분

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """스레드별 연결 반환"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                timeout=60.0,  # 락 대기 시간 (네트워크용)
                isolation_level=None  # autocommit
            )
            self._local.conn.row_factory = sqlite3.Row
            # DELETE 모드 - 네트워크 드라이브 호환
            self._local.conn.execute("PRAGMA journal_mode=DELETE")
            self._local.conn.execute("PRAGMA synchronous=FULL")
            self._local.conn.execute("PRAGMA busy_timeout=60000")
            self._local.conn.execute("PRAGMA temp_store=MEMORY")
        return self._local.conn

    @contextmanager
    def transaction(self):
        """트랜잭션 컨텍스트 매니저"""
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e

    def _init_db(self):
        """데이터베이스 초기화"""
        conn = self._get_connection()

        # 풀 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pools (
                pool_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                priority INTEGER DEFAULT 50,
                max_workers INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # 작업 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                clip_path TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                start_frame INTEGER NOT NULL,
                end_frame INTEGER NOT NULL,
                eyes TEXT NOT NULL,
                format TEXT DEFAULT 'exr',
                separate_folders INTEGER DEFAULT 0,
                use_aces INTEGER DEFAULT 1,
                color_input_space TEXT DEFAULT 'BMDFilm WideGamut Gen5',
                color_output_space TEXT DEFAULT 'ACEScg',
                use_stmap INTEGER DEFAULT 0,
                stmap_path TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 50,
                created_at TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                FOREIGN KEY (pool_id) REFERENCES pools(pool_id)
            )
        """)

        # 프레임 테이블 (개별 프레임 상태 추적)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                frame_idx INTEGER NOT NULL,
                eye TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                worker_id TEXT,
                claimed_at TEXT,
                completed_at TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                UNIQUE(job_id, frame_idx, eye)
            )
        """)

        # 워커 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT PRIMARY KEY,
                pool_id TEXT NOT NULL,
                hostname TEXT NOT NULL,
                ip TEXT DEFAULT '',
                status TEXT DEFAULT 'idle',
                current_job_id TEXT DEFAULT '',
                frames_completed INTEGER DEFAULT 0,
                last_heartbeat TEXT NOT NULL,
                FOREIGN KEY (pool_id) REFERENCES pools(pool_id)
            )
        """)

        # 인덱스 생성
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_pool ON jobs(pool_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_job ON frames(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_status ON frames(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_worker ON frames(worker_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workers_pool ON workers(pool_id)")

        # 기본 풀 생성
        conn.execute("""
            INSERT OR IGNORE INTO pools (pool_id, name, description, priority, created_at)
            VALUES ('default', '기본 풀', '기본 작업 풀', 50, ?)
        """, (datetime.now().isoformat(),))


    # ===== Pool 관리 =====

    def create_pool(self, pool: Pool) -> bool:
        """풀 생성"""
        try:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO pools (pool_id, name, description, priority, max_workers, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pool.pool_id, pool.name, pool.description, pool.priority,
                  pool.max_workers, pool.created_at.isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_pools(self) -> List[Pool]:
        """모든 풀 조회"""
        conn = self._get_connection()
        rows = conn.execute("SELECT * FROM pools ORDER BY priority DESC, name").fetchall()
        return [Pool(
            pool_id=r['pool_id'],
            name=r['name'],
            description=r['description'],
            priority=r['priority'],
            max_workers=r['max_workers'],
            created_at=datetime.fromisoformat(r['created_at'])
        ) for r in rows]

    def delete_pool(self, pool_id: str) -> bool:
        """풀 삭제 (기본 풀은 삭제 불가)"""
        if pool_id == 'default':
            return False
        conn = self._get_connection()
        # 해당 풀의 작업을 기본 풀로 이동
        conn.execute("UPDATE jobs SET pool_id = 'default' WHERE pool_id = ?", (pool_id,))
        conn.execute("UPDATE workers SET pool_id = 'default' WHERE pool_id = ?", (pool_id,))
        conn.execute("DELETE FROM pools WHERE pool_id = ?", (pool_id,))
        return True

    # ===== Job 관리 =====

    def submit_job(self, job: Job) -> bool:
        """작업 제출 및 프레임 생성"""
        try:
            with self.transaction() as conn:
                # 작업 삽입
                conn.execute("""
                    INSERT INTO jobs (job_id, pool_id, clip_path, output_dir, start_frame, end_frame,
                                     eyes, format, separate_folders, use_aces, color_input_space,
                                     color_output_space, use_stmap, stmap_path, status, priority,
                                     created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (job.job_id, job.pool_id, job.clip_path, job.output_dir,
                      job.start_frame, job.end_frame, json.dumps(job.eyes),
                      job.format, int(job.separate_folders), int(job.use_aces),
                      job.color_input_space, job.color_output_space,
                      int(job.use_stmap), job.stmap_path, job.status.value,
                      job.priority, job.created_at.isoformat(), job.created_by))

                # 프레임 레코드 생성
                frames_data = []
                for frame_idx in range(job.start_frame, job.end_frame + 1):
                    for eye in job.eyes:
                        frames_data.append((job.job_id, frame_idx, eye, 'pending'))

                conn.executemany("""
                    INSERT INTO frames (job_id, frame_idx, eye, status)
                    VALUES (?, ?, ?, ?)
                """, frames_data)

            return True
        except sqlite3.IntegrityError:
            return False

    def get_job(self, job_id: str) -> Optional[Job]:
        """작업 조회"""
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def get_jobs_by_pool(self, pool_id: str, include_excluded: bool = False) -> List[Job]:
        """풀별 작업 목록"""
        conn = self._get_connection()
        if include_excluded:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE pool_id = ? ORDER BY priority DESC, created_at",
                (pool_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE pool_id = ? AND status != 'excluded' ORDER BY priority DESC, created_at",
                (pool_id,)
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_all_jobs(self, include_excluded: bool = True) -> List[Tuple[Job, str, int, int]]:
        """모든 작업 + 상태 정보"""
        conn = self._get_connection()

        if include_excluded:
            jobs_rows = conn.execute(
                "SELECT * FROM jobs ORDER BY priority DESC, created_at"
            ).fetchall()
        else:
            jobs_rows = conn.execute(
                "SELECT * FROM jobs WHERE status != 'excluded' ORDER BY priority DESC, created_at"
            ).fetchall()

        result = []
        for row in jobs_rows:
            job = self._row_to_job(row)

            # 진행률 조회
            stats = conn.execute("""
                SELECT status, COUNT(*) as cnt FROM frames
                WHERE job_id = ? GROUP BY status
            """, (job.job_id,)).fetchall()

            total = sum(s['cnt'] for s in stats)
            completed = sum(s['cnt'] for s in stats if s['status'] == 'completed')
            claimed = sum(s['cnt'] for s in stats if s['status'] == 'claimed')

            # 상태 결정 (claimed도 진행중으로 간주)
            if job.status == JobStatus.EXCLUDED:
                status = 'excluded'
            elif job.status == JobStatus.PAUSED:
                status = 'paused'
            elif completed >= total and total > 0:
                status = 'completed'
            elif completed > 0 or claimed > 0:
                status = 'in_progress'
            else:
                status = 'pending'

            result.append((job, status, completed, total))

        return result

    def set_job_status(self, job_id: str, status: JobStatus):
        """작업 상태 변경"""
        conn = self._get_connection()
        conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?",
                    (status.value, job_id))

    def set_job_priority(self, job_id: str, priority: int):
        """작업 우선순위 변경"""
        conn = self._get_connection()
        conn.execute("UPDATE jobs SET priority = ? WHERE job_id = ?",
                    (max(0, min(100, priority)), job_id))

    def move_job_to_pool(self, job_id: str, pool_id: str):
        """작업을 다른 풀로 이동"""
        conn = self._get_connection()
        conn.execute("UPDATE jobs SET pool_id = ? WHERE job_id = ?", (pool_id, job_id))

    def delete_job(self, job_id: str):
        """작업 삭제"""
        with self.transaction() as conn:
            conn.execute("DELETE FROM frames WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def reset_job(self, job_id: str):
        """작업 리셋 (모든 프레임 pending으로)"""
        with self.transaction() as conn:
            conn.execute("""
                UPDATE frames SET status = 'pending', worker_id = NULL,
                       claimed_at = NULL, completed_at = NULL, retry_count = 0
                WHERE job_id = ?
            """, (job_id,))
            conn.execute("UPDATE jobs SET status = 'pending' WHERE job_id = ?", (job_id,))

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Row를 Job 객체로 변환"""
        return Job(
            job_id=row['job_id'],
            pool_id=row['pool_id'],
            clip_path=row['clip_path'],
            output_dir=row['output_dir'],
            start_frame=row['start_frame'],
            end_frame=row['end_frame'],
            eyes=json.loads(row['eyes']),
            format=row['format'],
            separate_folders=bool(row['separate_folders']),
            use_aces=bool(row['use_aces']),
            color_input_space=row['color_input_space'],
            color_output_space=row['color_output_space'],
            use_stmap=bool(row['use_stmap']),
            stmap_path=row['stmap_path'],
            status=JobStatus(row['status']),
            priority=row['priority'],
            created_at=datetime.fromisoformat(row['created_at']),
            created_by=row['created_by']
        )

    # ===== Frame 관리 (핵심: 원자적 클레임) =====


    def get_pending_frame_count(self, pool_id: str) -> int:
        """해당 풀의 대기 중인 프레임 수"""
        conn = self._get_connection()
        result = conn.execute("""
            SELECT COUNT(*) as cnt FROM frames f
            JOIN jobs j ON f.job_id = j.job_id
            WHERE j.pool_id = ? AND j.status NOT IN ('excluded', 'paused', 'completed')
              AND f.status = 'pending'
        """, (pool_id,)).fetchone()
        return result['cnt'] if result else 0

    def claim_frames(self, pool_id: str, worker_id: str, batch_size: int = 10) -> Optional[Tuple[str, int, int, str]]:
        """프레임 범위 클레임 (원자적 처리)

        Returns:
            (job_id, start_frame, end_frame, eye) 또는 None
        """
        now = datetime.now().isoformat()
        timeout = (datetime.now() - timedelta(seconds=self.CLAIM_TIMEOUT_SEC)).isoformat()

        with self.transaction() as conn:
            # 만료된 클레임 정리
            conn.execute("""
                UPDATE frames SET status = 'pending', worker_id = NULL, claimed_at = NULL
                WHERE status = 'claimed' AND claimed_at < ?
            """, (timeout,))

            # 해당 풀의 대기 중인 작업에서 프레임 찾기
            row = conn.execute("""
                SELECT f.job_id, f.frame_idx, f.eye, j.priority
                FROM frames f
                JOIN jobs j ON f.job_id = j.job_id
                WHERE j.pool_id = ? AND j.status NOT IN ('excluded', 'paused', 'completed')
                  AND f.status = 'pending'
                ORDER BY j.priority DESC, j.created_at, f.frame_idx, f.eye
                LIMIT 1
            """, (pool_id,)).fetchone()

            if not row:
                return None

            job_id = row['job_id']
            start_frame = row['frame_idx']
            eye = row['eye']

            # 연속된 프레임 범위 클레임
            frames_to_claim = conn.execute("""
                SELECT frame_idx FROM frames
                WHERE job_id = ? AND eye = ? AND status = 'pending'
                  AND frame_idx >= ?
                ORDER BY frame_idx
                LIMIT ?
            """, (job_id, eye, start_frame, batch_size)).fetchall()

            if not frames_to_claim:
                return None

            frame_indices = [f['frame_idx'] for f in frames_to_claim]
            end_frame = frame_indices[-1]

            # 클레임 실행
            placeholders = ','.join('?' * len(frame_indices))
            conn.execute(f"""
                UPDATE frames SET status = 'claimed', worker_id = ?, claimed_at = ?
                WHERE job_id = ? AND eye = ? AND frame_idx IN ({placeholders})
            """, [worker_id, now, job_id, eye] + frame_indices)

            # 작업 상태 업데이트
            conn.execute("""
                UPDATE jobs SET status = 'in_progress'
                WHERE job_id = ? AND status = 'pending'
            """, (job_id,))

            return (job_id, start_frame, end_frame, eye)

    def complete_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
        """프레임 범위 완료 처리"""
        now = datetime.now().isoformat()
        conn = self._get_connection()

        # 완료 처리 (worker_id 조건 제거 - 중요!)
        cursor = conn.execute("""
            UPDATE frames SET status = 'completed', completed_at = ?
            WHERE job_id = ? AND eye = ? AND frame_idx BETWEEN ? AND ?
              AND status IN ('claimed', 'pending')
        """, (now, job_id, eye, start_frame, end_frame))

        updated = cursor.rowcount

        # 작업 완료 여부 확인
        remaining = conn.execute("""
            SELECT COUNT(*) as cnt FROM frames
            WHERE job_id = ? AND status != 'completed'
        """, (job_id,)).fetchone()['cnt']

        if remaining == 0:
            conn.execute("UPDATE jobs SET status = 'completed' WHERE job_id = ?", (job_id,))

        # 명시적 commit (안전을 위해)
        conn.commit()

        return updated

    def release_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
        """프레임 범위 클레임 해제 (실패 시)"""
        conn = self._get_connection()
        conn.execute("""
            UPDATE frames SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                   retry_count = retry_count + 1
            WHERE job_id = ? AND eye = ? AND frame_idx BETWEEN ? AND ? AND worker_id = ?
        """, (job_id, eye, start_frame, end_frame, worker_id))
        conn.commit()

    def get_job_progress(self, job_id: str) -> Dict[str, int]:
        """작업 진행률"""
        conn = self._get_connection()
        stats = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM frames
            WHERE job_id = ? GROUP BY status
        """, (job_id,)).fetchall()

        result = {'pending': 0, 'claimed': 0, 'completed': 0, 'failed': 0}
        for s in stats:
            result[s['status']] = s['cnt']
        result['total'] = sum(result.values())
        return result

    def get_job_eye_progress(self, job_id: str) -> Dict[str, Dict[str, int]]:
        """작업별 눈(eye) 진행률 조회"""
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT eye, status, COUNT(*) as cnt FROM frames
            WHERE job_id = ? GROUP BY eye, status
        """, (job_id,)).fetchall()

        result = {}
        for r in rows:
            eye = r['eye']
            if eye not in result:
                result[eye] = {'pending': 0, 'claimed': 0, 'completed': 0, 'failed': 0, 'total': 0}
            result[eye][r['status']] = r['cnt']

        for eye in result:
            result[eye]['total'] = sum(v for k, v in result[eye].items() if k != 'total')
        return result

    def get_active_workers(self) -> List[Worker]:
        """모든 워커 목록 (오프라인 포함, 24시간 이내)"""
        conn = self._get_connection()
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()
        day_ago = (datetime.now() - timedelta(hours=24)).isoformat()

        rows = conn.execute("""
            SELECT *,
                   CASE WHEN last_heartbeat < ? THEN 'offline' ELSE status END as actual_status
            FROM workers
            WHERE last_heartbeat >= ?
            ORDER BY
                CASE WHEN last_heartbeat >= ? THEN 0 ELSE 1 END,
                pool_id, hostname
        """, (timeout, day_ago, timeout)).fetchall()

        return [Worker(
            worker_id=r['worker_id'],
            pool_id=r['pool_id'],
            hostname=r['hostname'],
            ip=r['ip'],
            status=r['actual_status'],
            current_job_id=r['current_job_id'],
            frames_completed=r['frames_completed'],
            last_heartbeat=datetime.fromisoformat(r['last_heartbeat'])
        ) for r in rows]

    # ===== Worker 관리 =====

    def register_worker(self, worker: Worker):
        """워커 등록/업데이트"""
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO workers (worker_id, pool_id, hostname, ip, status, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                pool_id = excluded.pool_id,
                hostname = excluded.hostname,
                ip = excluded.ip,
                status = excluded.status,
                last_heartbeat = excluded.last_heartbeat
        """, (worker.worker_id, worker.pool_id, worker.hostname, worker.ip,
              worker.status, worker.last_heartbeat.isoformat()))

    def update_heartbeat(self, worker_id: str, status: str = "active",
                         current_job_id: str = "", frames_completed: int = 0):
        """워커 하트비트 업데이트"""
        conn = self._get_connection()
        conn.execute("""
            UPDATE workers SET last_heartbeat = ?, status = ?,
                   current_job_id = ?, frames_completed = ?
            WHERE worker_id = ?
        """, (datetime.now().isoformat(), status, current_job_id,
              frames_completed, worker_id))

    def get_workers_by_pool(self, pool_id: str) -> List[Worker]:
        """풀별 워커 목록"""
        conn = self._get_connection()
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()

        rows = conn.execute("""
            SELECT *,
                   CASE WHEN last_heartbeat < ? THEN 'offline' ELSE status END as actual_status
            FROM workers WHERE pool_id = ?
            ORDER BY hostname
        """, (timeout, pool_id)).fetchall()

        return [Worker(
            worker_id=r['worker_id'],
            pool_id=r['pool_id'],
            hostname=r['hostname'],
            ip=r['ip'],
            status=r['actual_status'],
            current_job_id=r['current_job_id'],
            frames_completed=r['frames_completed'],
            last_heartbeat=datetime.fromisoformat(r['last_heartbeat'])
        ) for r in rows]

    def get_all_workers(self) -> List[Worker]:
        """모든 워커 목록"""
        conn = self._get_connection()
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()

        rows = conn.execute("""
            SELECT *,
                   CASE WHEN last_heartbeat < ? THEN 'offline' ELSE status END as actual_status
            FROM workers ORDER BY pool_id, hostname
        """, (timeout,)).fetchall()

        return [Worker(
            worker_id=r['worker_id'],
            pool_id=r['pool_id'],
            hostname=r['hostname'],
            ip=r['ip'],
            status=r['actual_status'],
            current_job_id=r['current_job_id'],
            frames_completed=r['frames_completed'],
            last_heartbeat=datetime.fromisoformat(r['last_heartbeat'])
        ) for r in rows]

    def get_pool_stats(self, pool_id: str) -> Dict[str, Any]:
        """풀 통계"""
        conn = self._get_connection()

        # 작업 통계
        job_stats = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM jobs
            WHERE pool_id = ? GROUP BY status
        """, (pool_id,)).fetchall()

        # 프레임 통계
        frame_stats = conn.execute("""
            SELECT f.status, COUNT(*) as cnt FROM frames f
            JOIN jobs j ON f.job_id = j.job_id
            WHERE j.pool_id = ? GROUP BY f.status
        """, (pool_id,)).fetchall()

        # 워커 통계
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()
        worker_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN last_heartbeat >= ? AND status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN last_heartbeat >= ? AND status = 'idle' THEN 1 ELSE 0 END) as idle,
                SUM(CASE WHEN last_heartbeat < ? THEN 1 ELSE 0 END) as offline
            FROM workers WHERE pool_id = ?
        """, (timeout, timeout, timeout, pool_id)).fetchone()

        return {
            'jobs': {s['status']: s['cnt'] for s in job_stats},
            'frames': {s['status']: s['cnt'] for s in frame_stats},
            'workers': {
                'total': worker_stats['total'] or 0,
                'active': worker_stats['active'] or 0,
                'idle': worker_stats['idle'] or 0,
                'offline': worker_stats['offline'] or 0
            }
        }

    def cleanup_offline_workers(self):
        """오프라인 워커의 클레임 정리"""
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()

        with self.transaction() as conn:
            # 오프라인 워커 ID 수집
            offline_workers = conn.execute("""
                SELECT worker_id FROM workers WHERE last_heartbeat < ?
            """, (timeout,)).fetchall()

            for w in offline_workers:
                # 해당 워커의 클레임 해제
                conn.execute("""
                    UPDATE frames SET status = 'pending', worker_id = NULL, claimed_at = NULL
                    WHERE worker_id = ? AND status = 'claimed'
                """, (w['worker_id'],))

                # 워커 상태 업데이트
                conn.execute("""
                    UPDATE workers SET status = 'offline', current_job_id = ''
                    WHERE worker_id = ?
                """, (w['worker_id'],))

    def close(self):
        """연결 종료"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# 싱글톤 인스턴스
_db_instance: Optional[FarmDatabase] = None

# 기본 DB 경로 (환경변수 또는 기본값)
DEFAULT_DB_PATH = os.environ.get('BRAW_FARM_DB', 'P:/99-Pipeline/Blackmagic/Braw_convert_Project/farm.db')


def get_default_db_path() -> str:
    """기본 DB 경로 반환 (환경변수 우선)"""
    return os.environ.get('BRAW_FARM_DB', DEFAULT_DB_PATH)


def get_database(db_path: str = None) -> FarmDatabase:
    """데이터베이스 인스턴스 반환"""
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            db_path = get_default_db_path()
        _db_instance = FarmDatabase(db_path)
    return _db_instance


def init_database(db_path: str = None) -> FarmDatabase:
    """데이터베이스 초기화"""
    global _db_instance
    if db_path is None:
        db_path = get_default_db_path()
    _db_instance = FarmDatabase(db_path)
    return _db_instance
