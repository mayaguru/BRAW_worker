import re

with open("braw_batch_ui/braw_batch_ui/farm_core.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '''    def is_frame_completed(self, job_id: str, frame_idx: int, eye: str, job: 'RenderJob' = None) -> bool:
        """프레임 완료 여부 확인 (.done 파일 기준, job 전달 시 실제 파일도 확인)"""
        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
        if not completed_file.exists():
            return False

        # job이 전달되면 실제 출력 파일도 확인 (더 안전)
        if job is not None:
            output_file = self.get_output_file_path(job, frame_idx, eye)
            if not output_file.exists():
                # .done 파일은 있지만 실제 파일 없음 - .done 삭제하여 재처리 유도
                try:
                    completed_file.unlink(missing_ok=True)
                except (OSError, IOError):
                    pass
                return False

        return True'''

new = '''    def is_frame_completed(self, job_id: str, frame_idx: int, eye: str, job: 'RenderJob' = None) -> bool:
        """프레임 완료 여부 확인 (.done 파일 기준)

        .done 파일이 있으면 완료로 취급 (네트워크 지연으로 출력 파일이 안 보일 수 있음)
        232개 워커 동시 접근 시 중복 작업 방지를 위해 .done 파일만 신뢰
        """
        completed_file = self.config.completed_dir / f"{job_id}_{frame_idx:06d}_{eye}.done"
        return completed_file.exists()'''

if old in content:
    content = content.replace(old, new)
    with open("braw_batch_ui/braw_batch_ui/farm_core.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ is_frame_completed 수정 완료 - .done 파일만 확인")
else:
    print("❌ 패턴 못찾음")
