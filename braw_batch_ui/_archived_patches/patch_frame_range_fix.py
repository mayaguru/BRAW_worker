#!/usr/bin/env python3
"""Fix frame range calculation - remove wrong -1"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

# Fix: end_frame was being reduced by 1 incorrectly
old_code = '''            start_frame = user_start if user_start > 0 else 0
            end_frame = (user_end - 1) if user_end > 0 else (frame_count - 1)'''

new_code = '''            start_frame = user_start  # 0이면 처음부터
            end_frame = user_end if user_end > 0 else (frame_count - 1)  # 0이면 끝까지'''

if old_code in content:
    content = content.replace(old_code, new_code)
    file_path.write_text(content, encoding='utf-8')
    print("[OK] Frame range fixed - removed incorrect -1 from end_frame")
else:
    print("[SKIP] Pattern not found or already fixed")
