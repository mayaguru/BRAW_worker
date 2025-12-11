#!/usr/bin/env python3
"""Frame label instant update patch"""
import re
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

# 1. SpinBox valueChanged signal connection
old_text1 = """        frame_layout.addStretch()
        layout.addLayout(frame_layout)

        # 우선순위"""

new_text1 = """        frame_layout.addStretch()
        layout.addLayout(frame_layout)

        # SpinBox 값 변경시 라벨 즉시 업데이트
        self.start_frame_spin.valueChanged.connect(self.update_frame_range_label)
        self.end_frame_spin.valueChanged.connect(self.update_frame_range_label)

        # 우선순위"""

if old_text1 in content and "update_frame_range_label" not in content:
    content = content.replace(old_text1, new_text1)
    print("[OK] SpinBox signal connected")
else:
    print("[SKIP] SpinBox signal already exists or pattern mismatch")

# 2. update_frame_range_label method (after on_file_selected)
old_text2 = '''    def on_file_selected(self, current, previous):
        """파일 선택 시 프레임 범위 업데이트"""
        if not current:
            self.frame_info_label.setText("(0=전체)")
            return

        clip_path = current.data(Qt.UserRole)
        if clip_path and clip_path in self.clip_frame_cache:
            frame_count = self.clip_frame_cache[clip_path]
            if frame_count > 0:
                self.frame_info_label.setText(f"(0-{frame_count - 1})")
                self.end_frame_spin.setMaximum(frame_count)
            else:
                self.frame_info_label.setText("(정보 없음)")

    def on_clear_files(self):'''

new_text2 = '''    def on_file_selected(self, current, previous):
        """파일 선택 시 프레임 범위 업데이트"""
        if not current:
            self.frame_info_label.setText("(0=전체)")
            return

        clip_path = current.data(Qt.UserRole)
        if clip_path and clip_path in self.clip_frame_cache:
            frame_count = self.clip_frame_cache[clip_path]
            if frame_count > 0:
                # 최대값 설정
                self.end_frame_spin.setMaximum(frame_count - 1)
                self.start_frame_spin.setMaximum(frame_count - 1)
                # 라벨 업데이트
                self.update_frame_range_label()
            else:
                self.frame_info_label.setText("(정보 없음)")

    def update_frame_range_label(self):
        """SpinBox 값 변경시 프레임 범위 라벨 즉시 업데이트"""
        start = self.start_frame_spin.value()
        end = self.end_frame_spin.value()

        # 현재 선택된 파일의 전체 프레임 수 확인
        current = self.file_list.currentItem()
        if current:
            clip_path = current.data(Qt.UserRole)
            if clip_path and clip_path in self.clip_frame_cache:
                max_frame = self.clip_frame_cache[clip_path] - 1

                # 0-0이면 전체 범위 표시
                if start == 0 and end == 0:
                    self.frame_info_label.setText(f"(0-{max_frame})")
                else:
                    # 사용자 지정 범위 표시
                    actual_end = end if end > 0 else max_frame
                    self.frame_info_label.setText(f"({start}-{actual_end})")
                return

        # 파일 미선택시 또는 캐시 없을 때
        if start == 0 and end == 0:
            self.frame_info_label.setText("(0=전체)")
        else:
            actual_end = end if end > 0 else "끝"
            self.frame_info_label.setText(f"({start}-{actual_end})")

    def on_clear_files(self):'''

if "def update_frame_range_label" not in content:
    if old_text2 in content:
        content = content.replace(old_text2, new_text2)
        print("[OK] update_frame_range_label method added")
    else:
        print("[WARN] on_file_selected pattern mismatch - manual check needed")
else:
    print("[SKIP] update_frame_range_label already exists")

# Save
file_path.write_text(content, encoding='utf-8')
print("[DONE] Patch complete!")
