#!/usr/bin/env python3
"""Fix parse_custom_frames to handle various dash/hyphen characters"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_ui_v2.py"
content = file_path.read_text(encoding='utf-8')

old_method = '''    def parse_custom_frames(self, input_text: str) -> list:
        """커스텀 프레임 문자열 파싱

        입력 예: "509, 540, 602, 1675-1679, 1707"
        출력: [(509, 509), (540, 540), (602, 602), (1675, 1679), (1707, 1707)]
        """
        if not input_text.strip():
            return []

        result = []
        parts = input_text.replace(" ", "").split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if "-" in part:
                # 범위: 1675-1679
                try:
                    start, end = part.split("-", 1)
                    start_frame = int(start)
                    end_frame = int(end)
                    if start_frame <= end_frame:
                        result.append((start_frame, end_frame))
                except ValueError:
                    self.append_worker_log(f"잘못된 범위: {part}")
            else:
                # 개별 프레임: 509
                try:
                    frame = int(part)
                    result.append((frame, frame))
                except ValueError:
                    self.append_worker_log(f"잘못된 프레임: {part}")

        return result'''

new_method = '''    def parse_custom_frames(self, input_text: str) -> list:
        """커스텀 프레임 문자열 파싱

        입력 예: "509, 540, 602, 1675-1679, 1707"
        출력: [(509, 509), (540, 540), (602, 602), (1675, 1679), (1707, 1707)]
        """
        if not input_text.strip():
            return []

        import re

        # 다양한 하이픈/대시 문자를 일반 하이픈으로 정규화
        # 엔 대시, 엠 대시, 전각 하이픈, 마이너스, 틸드 등
        normalized = re.sub(r'[\\u2013\\u2014\\uFF0D\\u2010\\u2011\\u2012\\u2015\\u2212~]', '-', input_text)
        # 전각 쉼표, 세미콜론도 쉼표로
        normalized = re.sub(r'[\\uFF0C;\\uFF1B]', ',', normalized)

        result = []
        parts = normalized.replace(" ", "").split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if "-" in part:
                # 범위: 1675-1679
                try:
                    start, end = part.split("-", 1)
                    start_frame = int(start)
                    end_frame = int(end)
                    if start_frame <= end_frame:
                        result.append((start_frame, end_frame))
                    else:
                        # 역순이면 자동 수정
                        result.append((end_frame, start_frame))
                except ValueError:
                    self.append_worker_log(f"\\u26a0\\ufe0f \\uc798\\ubabb\\ub41c \\ubc94\\uc704: {part}")
            else:
                # 개별 프레임: 509
                try:
                    frame = int(part)
                    result.append((frame, frame))
                except ValueError:
                    self.append_worker_log(f"\\u26a0\\ufe0f \\uc798\\ubabb\\ub41c \\ud504\\ub808\\uc784: {part}")

        return result'''

if old_method in content:
    content = content.replace(old_method, new_method)
    file_path.write_text(content, encoding='utf-8')
    print("[OK] parse_custom_frames updated - now handles various dash characters")
else:
    print("[SKIP] Pattern not found or already fixed")
