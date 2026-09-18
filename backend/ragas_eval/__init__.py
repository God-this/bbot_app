"""RAGAS 품질 평가 모듈.

BeBot 본체와 분리 운용하며 Redis/Postgres만 공유한다.
②단계에서는 큐 적재(queue_repo)만 존재하고, 평가 배치(runner/metrics)와
결과 저장(result_repo)은 ③단계에서 추가된다.

주의: 이 패키지는 서비스(EC2)와 배치 양쪽에서 import된다.
queue_repo는 표준 라이브러리와 config만 의존해야 하며,
ragas 패키지는 ③단계 모듈에서만 import할 것 — EC2에는 ragas가 설치되어 있지 않다.
"""

from .queue_repo import enqueue_eval

__all__ = ["enqueue_eval"]
