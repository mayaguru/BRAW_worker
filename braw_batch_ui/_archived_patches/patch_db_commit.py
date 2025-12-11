#!/usr/bin/env python3
"""Add explicit commit to complete_frames and release_frames"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_db.py"
content = file_path.read_text(encoding='utf-8')

changes = []

# 1. Fix complete_frames - add commit
old_complete = '''    def complete_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
        """프레임 범위 완료 처리"""
        now = datetime.now().isoformat()
        conn = self._get_connection()
        conn.execute("""
            UPDATE frames SET status = 'completed', completed_at = ?
            WHERE job_id = ? AND eye = ? AND frame_idx BETWEEN ? AND ? AND worker_id = ?
        """, (now, job_id, eye, start_frame, end_frame, worker_id))

        # 작업 완료 여부 확인
        remaining = conn.execute("""
            SELECT COUNT(*) as cnt FROM frames
            WHERE job_id = ? AND status != 'completed'
        """, (job_id,)).fetchone()['cnt']

        if remaining == 0:
            conn.execute("UPDATE jobs SET status = 'completed' WHERE job_id = ?", (job_id,))'''

new_complete = '''    def complete_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
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

        return updated'''

if old_complete in content:
    content = content.replace(old_complete, new_complete)
    changes.append("[OK] complete_frames fixed with commit")
else:
    changes.append("[WARN] complete_frames pattern not found")

# 2. Fix release_frames - add commit
old_release = '''    def release_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
        """프레임 범위 클레임 해제 (실패 시)"""
        conn = self._get_connection()
        conn.execute("""
            UPDATE frames SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                   retry_count = retry_count + 1
            WHERE job_id = ? AND eye = ? AND frame_idx BETWEEN ? AND ? AND worker_id = ?
        """, (job_id, eye, start_frame, end_frame, worker_id))'''

new_release = '''    def release_frames(self, job_id: str, start_frame: int, end_frame: int, eye: str, worker_id: str):
        """프레임 범위 클레임 해제 (실패 시)"""
        conn = self._get_connection()
        conn.execute("""
            UPDATE frames SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                   retry_count = retry_count + 1
            WHERE job_id = ? AND eye = ? AND frame_idx BETWEEN ? AND ? AND worker_id = ?
        """, (job_id, eye, start_frame, end_frame, worker_id))
        conn.commit()'''

if old_release in content:
    content = content.replace(old_release, new_release)
    changes.append("[OK] release_frames fixed with commit")
else:
    changes.append("[WARN] release_frames pattern not found")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)
print("[DONE] Patch complete!")
