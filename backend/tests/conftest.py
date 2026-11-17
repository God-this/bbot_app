"""성경 구절 검증 테스트 공통 설정.

    cd backend && python -m pytest tests

성경 원문은 기본으로 bible.txt(BIBLE_SOURCE=file)를 쓴다. bible.txt가 없으면 건너뛴다.
운영 DB로 돌리려면 BIBLE_SOURCE=db (bible_krv 테이블 사용).
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))          # 테스트에서 backend/ 모듈을 import하기 위해

os.environ.setdefault("BIBLE_SOURCE", "file")
BIBLE_FILE = BACKEND_DIR / "bible.txt"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("BIBLE_SOURCE", "file") != "file" or BIBLE_FILE.exists():
        return
    import pytest

    skip = pytest.mark.skip(reason="bible.txt가 없습니다 (BIBLE_SOURCE=db로 운영 DB를 쓰거나 bible.txt를 backend/에 두세요)")
    for item in items:
        item.add_marker(skip)
