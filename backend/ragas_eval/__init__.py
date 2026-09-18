"""RAGAS 품질 평가 모듈.

BeBot 본체와 분리 운용하며 Redis/Postgres만 공유한다.

주의: 이 패키지는 서비스(EC2)와 배치 양쪽에서 import된다.
서비스가 쓰는 queue_repo는 표준 라이브러리와 config만 의존해야 한다.
ragas 패키지에 의존하는 모듈(judge / metrics / runner)은 EC2 서비스 venv에
ragas가 없으므로 여기서 re-export하지 않는다 — 배치에서 직접 import할 것.
"""

from .queue_repo import enqueue_eval

__all__ = ["enqueue_eval"]
