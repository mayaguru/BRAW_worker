#!/usr/bin/env python3
"""Fix get_output_file_path to match CLI output pattern"""
from pathlib import Path

file_path = Path(__file__).parent / "braw_batch_ui" / "farm_core_v2.py"
content = file_path.read_text(encoding='utf-8')

old_method = '''    def get_output_file_path(self, job: Job, frame_idx: int, eye: str) -> Path:
        """출력 파일 경로 계산"""
        output_dir = Path(job.output_dir)
        clip_basename = Path(job.clip_path).stem
        ext = ".exr" if job.format == "exr" else ".ppm"

        if job.separate_folders:
            if eye == "sbs":
                folder = "SBS"
            else:
                folder = "L" if eye == "left" else "R"
            return output_dir / folder / f"{clip_basename}_{frame_idx:06d}{ext}"
        else:
            if eye == "sbs":
                suffix = "_SBS"
            else:
                suffix = "_L" if eye == "left" else "_R"
            return output_dir / f"{clip_basename}{suffix}_{frame_idx:06d}{ext}"'''

new_method = '''    def get_output_file_path(self, job: Job, frame_idx: int, eye: str) -> Path:
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
            return output_dir / f"{clip_basename}{suffix}_{frame_idx:06d}{ext}"'''

if old_method in content:
    content = content.replace(old_method, new_method)
    file_path.write_text(content, encoding='utf-8')
    print("[OK] get_output_file_path fixed - SBS always uses SBS folder")
else:
    print("[SKIP] Pattern not found or already fixed")
