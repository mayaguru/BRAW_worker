#!/usr/bin/env python3
"""Add frame range column to jobs table"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

changes = []

# 1. Update jobs_table column count and headers
old_table = '''        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(10)
        self.jobs_table.setHorizontalHeaderLabels([
            "작업 ID", "클립", "풀", "상태", "L", "R", "SBS", "진행률", "우선순위", "생성"
        ])
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for i in [2, 3, 4, 5, 6, 7, 8, 9]:
            self.jobs_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)'''

new_table = '''        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(11)
        self.jobs_table.setHorizontalHeaderLabels([
            "작업 ID", "클립", "프레임", "풀", "상태", "L", "R", "SBS", "진행률", "우선순위", "생성"
        ])
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.jobs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in [3, 4, 5, 6, 7, 8, 9, 10]:
            self.jobs_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)'''

if old_table in content:
    content = content.replace(old_table, new_table)
    changes.append("[OK] Table headers updated (11 columns)")
elif 'setColumnCount(11)' in content:
    changes.append("[SKIP] Already 11 columns")
else:
    changes.append("[WARN] Table header pattern not found")

# 2. Update refresh_jobs to include frame range column
old_refresh = '''            # 클립
            clip_name = Path(job.clip_path).stem
            self.jobs_table.setItem(row, 1, QTableWidgetItem(clip_name))

            # 풀
            self.jobs_table.setItem(row, 2, QTableWidgetItem(job.pool_id))'''

new_refresh = '''            # 클립
            clip_name = Path(job.clip_path).stem
            self.jobs_table.setItem(row, 1, QTableWidgetItem(clip_name))

            # 프레임 범위
            frame_range = f"{job.start_frame}-{job.end_frame}"
            self.jobs_table.setItem(row, 2, QTableWidgetItem(frame_range))

            # 풀
            self.jobs_table.setItem(row, 3, QTableWidgetItem(job.pool_id))'''

if old_refresh in content:
    content = content.replace(old_refresh, new_refresh)
    changes.append("[OK] Frame range column added in refresh_jobs")
else:
    changes.append("[SKIP] refresh_jobs already updated or pattern mismatch")

# 3. Update column indices for remaining items in refresh_jobs (status, L, R, SBS, progress, priority, created)
# Status: 3 -> 4
old_status = '''            # 상태
            status_text = {
                'pending': '⏳ 대기',
                'in_progress': '🔄 진행중',
                'completed': '✅ 완료',
                'excluded': '⏸️ 제외',
                'paused': '⏯️ 일시정지',
                'failed': '❌ 실패'
            }.get(status, status)
            self.jobs_table.setItem(row, 3, QTableWidgetItem(status_text))'''

new_status = '''            # 상태
            status_text = {
                'pending': '⏳ 대기',
                'in_progress': '🔄 진행중',
                'completed': '✅ 완료',
                'excluded': '⏸️ 제외',
                'paused': '⏯️ 일시정지',
                'failed': '❌ 실패'
            }.get(status, status)
            self.jobs_table.setItem(row, 4, QTableWidgetItem(status_text))'''

if old_status in content:
    content = content.replace(old_status, new_status)
    changes.append("[OK] Status column index updated (3->4)")
else:
    changes.append("[SKIP] Status already at index 4 or pattern mismatch")

# 4. Update eye progress columns: 4,5,6 -> 5,6,7
old_eye = '''            # 눈별 진행률 (L, R, SBS)
            eye_progress = self.farm_manager.get_job_eye_progress(job.job_id)
            for col, eye in [(4, 'left'), (5, 'right'), (6, 'sbs')]:'''

new_eye = '''            # 눈별 진행률 (L, R, SBS)
            eye_progress = self.farm_manager.get_job_eye_progress(job.job_id)
            for col, eye in [(5, 'left'), (6, 'right'), (7, 'sbs')]:'''

if old_eye in content:
    content = content.replace(old_eye, new_eye)
    changes.append("[OK] Eye progress columns updated (4,5,6 -> 5,6,7)")
else:
    changes.append("[SKIP] Eye progress already updated or pattern mismatch")

# 5. Update total progress column: 7 -> 8
old_progress = '''            # 전체 진행률
            pct = (completed / total * 100) if total > 0 else 0
            self.jobs_table.setItem(row, 7, QTableWidgetItem(f"{completed}/{total} ({pct:.1f}%)"))'''

new_progress = '''            # 전체 진행률
            pct = (completed / total * 100) if total > 0 else 0
            self.jobs_table.setItem(row, 8, QTableWidgetItem(f"{completed}/{total} ({pct:.1f}%)"))'''

if old_progress in content:
    content = content.replace(old_progress, new_progress)
    changes.append("[OK] Progress column updated (7->8)")
else:
    changes.append("[SKIP] Progress already at index 8 or pattern mismatch")

# 6. Update priority column: 8 -> 9
old_priority = '''            # 우선순위
            self.jobs_table.setItem(row, 8, QTableWidgetItem(str(job.priority)))'''

new_priority = '''            # 우선순위
            self.jobs_table.setItem(row, 9, QTableWidgetItem(str(job.priority)))'''

if old_priority in content:
    content = content.replace(old_priority, new_priority)
    changes.append("[OK] Priority column updated (8->9)")
else:
    changes.append("[SKIP] Priority already at index 9 or pattern mismatch")

# 7. Update created column: 9 -> 10
old_created = '''            # 생성일
            self.jobs_table.setItem(row, 9, QTableWidgetItem('''

new_created = '''            # 생성일
            self.jobs_table.setItem(row, 10, QTableWidgetItem('''

if old_created in content:
    content = content.replace(old_created, new_created)
    changes.append("[OK] Created column updated (9->10)")
else:
    changes.append("[SKIP] Created already at index 10 or pattern mismatch")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)
print("[DONE] Patch complete!")
