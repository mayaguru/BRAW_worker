#!/usr/bin/env python3
"""Add 'Open Output Folder' to jobs table context menu"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

changes = []

# 1. Add context menu item for opening folder
old_menu = '''        menu = QMenu(self)

        # 상태 변경
        exclude_action = QAction("⏸️ 제외", self)'''

new_menu = '''        menu = QMenu(self)

        # 출력 폴더 열기 (단일 선택시)
        if len(job_ids) == 1:
            open_folder_action = QAction("📂 출력 폴더 열기", self)
            open_folder_action.triggered.connect(lambda: self.open_job_output_folder(job_ids[0]))
            menu.addAction(open_folder_action)
            menu.addSeparator()

        # 상태 변경
        exclude_action = QAction("⏸️ 제외", self)'''

if old_menu in content:
    content = content.replace(old_menu, new_menu)
    changes.append("[OK] Context menu item added")
elif "출력 폴더 열기" in content:
    changes.append("[SKIP] Context menu item already exists")
else:
    changes.append("[WARN] Context menu pattern not found")

# Save
file_path.write_text(content, encoding='utf-8')

print("=" * 50)
for c in changes:
    print(c)
print("=" * 50)
