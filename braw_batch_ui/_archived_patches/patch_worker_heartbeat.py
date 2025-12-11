#!/usr/bin/env python3
"""Fix worker heartbeat - update during work, show all workers"""
from pathlib import Path

# 1. Fix farm_ui_v2.py - add periodic heartbeat in worker loop
ui_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
ui_content = ui_path.read_text(encoding='utf-8')

changes = []

# Add heartbeat counter and periodic update in the main loop
old_loop = '''                    # 완료된 작업 처리
                    if futures:
                        done_futures = [f for f in futures if f.done()]

                        for future in done_futures:'''

new_loop = '''                    # 주기적 하트비트 업데이트 (작업 중에도)
                    if futures:
                        self.farm_manager.update_heartbeat("active", None, self.total_success)

                    # 완료된 작업 처리
                    if futures:
                        done_futures = [f for f in futures if f.done()]

                        for future in done_futures:'''

if old_loop in ui_content:
    ui_content = ui_content.replace(old_loop, new_loop)
    changes.append("[OK] Periodic heartbeat added in worker loop")
else:
    changes.append("[WARN] Worker loop pattern not found")

ui_path.write_text(ui_content, encoding='utf-8')

# 2. Fix farm_db.py - show all workers including offline, increase timeout
db_path = Path(__file__).parent / "braw_batch_ui" / "farm_db.py"
db_content = db_path.read_text(encoding='utf-8')

# Change HEARTBEAT_TIMEOUT_SEC if needed
old_timeout = "HEARTBEAT_TIMEOUT_SEC = 120"
new_timeout = "HEARTBEAT_TIMEOUT_SEC = 300"  # 5분으로 늘림

if old_timeout in db_content:
    db_content = db_content.replace(old_timeout, new_timeout)
    changes.append("[OK] Heartbeat timeout increased to 300s")
elif "HEARTBEAT_TIMEOUT_SEC = 300" in db_content:
    changes.append("[SKIP] Heartbeat timeout already 300s")
else:
    changes.append("[WARN] HEARTBEAT_TIMEOUT_SEC not found")

# Fix get_active_workers to show all workers (not just recent)
old_get_workers = '''    def get_active_workers(self) -> List[Worker]:
        """활성 워커 목록 (최근 하트비트)"""
        conn = self._get_connection()
        timeout = (datetime.now() - timedelta(seconds=self.HEARTBEAT_TIMEOUT_SEC)).isoformat()

        rows = conn.execute("""
            SELECT *,
                   CASE WHEN last_heartbeat < ? THEN 'offline' ELSE status END as actual_status
            FROM workers
            WHERE last_heartbeat >= ? OR status != 'offline'
            ORDER BY pool_id, hostname
        """, (timeout, timeout)).fetchall()'''

new_get_workers = '''    def get_active_workers(self) -> List[Worker]:
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
        """, (timeout, day_ago, timeout)).fetchall()'''

if old_get_workers in db_content:
    db_content = db_content.replace(old_get_workers, new_get_workers)
    changes.append("[OK] get_active_workers shows all workers (24h)")
else:
    changes.append("[WARN] get_active_workers pattern not found")

db_path.write_text(db_content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)
print("[DONE] Patch complete!")
