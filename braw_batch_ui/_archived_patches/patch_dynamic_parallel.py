#!/usr/bin/env python3
"""Dynamic parallel worker adjustment based on remaining frames"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

changes = []

# 1. Add method to get remaining pending frames count
new_method = '''
    def get_pending_frame_count(self) -> int:
        """대기 중인 프레임 수 조회"""
        try:
            return self.farm_manager.db.get_pending_frame_count(self.farm_manager.current_pool_id)
        except:
            return 9999  # 오류시 기본값 (제한 없음)

'''

# Insert before run method
if "def get_pending_frame_count" not in content:
    run_pos = content.find("    def run(self):\n        \"\"\"워커 실행 - 병렬 처리\"\"\"")
    if run_pos > 0:
        content = content[:run_pos] + new_method + content[run_pos:]
        changes.append("[OK] get_pending_frame_count method added")
    else:
        changes.append("[WARN] run method not found")
else:
    changes.append("[SKIP] get_pending_frame_count already exists")

# 2. Update the claim loop to dynamically adjust parallel workers
old_claim_loop = '''                    # 빈 슬롯만큼 작업 클레임
                    while len(futures) < self.parallel_workers and self.is_running:
                        claimed = self.farm_manager.claim_frames(settings.batch_frame_size)'''

new_claim_loop = '''                    # 남은 프레임 수에 따라 동적 병렬 수 조절
                    pending_frames = self.get_pending_frame_count()
                    batch_size = settings.batch_frame_size

                    # 남은 프레임이 적으면 병렬 수 제한
                    # 예: 120프레임 남음, batch=10 -> 최대 12개 병렬
                    # 예: 30프레임 남음, batch=10 -> 최대 3개 병렬
                    if pending_frames > 0:
                        max_effective_workers = max(1, (pending_frames + batch_size - 1) // batch_size)
                        effective_workers = min(self.parallel_workers, max_effective_workers)
                    else:
                        effective_workers = self.parallel_workers

                    # 빈 슬롯만큼 작업 클레임
                    while len(futures) < effective_workers and self.is_running:
                        claimed = self.farm_manager.claim_frames(batch_size)'''

if old_claim_loop in content:
    content = content.replace(old_claim_loop, new_claim_loop)
    changes.append("[OK] Dynamic parallel adjustment added")
else:
    changes.append("[WARN] Claim loop pattern not found")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)

# Now add DB method
db_path = Path(__file__).parent / "braw_batch_ui" / "farm_db.py"
db_content = db_path.read_text(encoding='utf-8')

db_method = '''
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

'''

if "def get_pending_frame_count" not in db_content:
    # Insert before claim_frames
    claim_pos = db_content.find("    def claim_frames(self, pool_id: str")
    if claim_pos > 0:
        db_content = db_content[:claim_pos] + db_method + db_content[claim_pos:]
        db_path.write_text(db_content, encoding='utf-8')
        print("[OK] DB get_pending_frame_count method added")
    else:
        print("[WARN] claim_frames not found in DB")
else:
    print("[SKIP] DB get_pending_frame_count already exists")

print("=" * 50)
print("[DONE] Patch complete!")
