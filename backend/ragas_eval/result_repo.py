"""ragas_evaluations CRUD.

queue_repo와 마찬가지로 표준 라이브러리 + config만 의존한다 (ragas import 없음).
"""

import json

from config import get_conn
from logging_config import get_logger

logger = get_logger(__name__)


def save_evaluation(
    cache_key: str,
    normalized_question: str,
    original_question: str,
    answer: str,
    contexts: list[str],
    context_char_limit: int,
    scores: dict,
    composite: float | None,
    verdict: str,
    dry_run: bool,
    ragas_version: str,
    judge_provider: str,
    judge_model: str,
) -> int | None:
    """평가 결과 1건 저장. Returns: 생성된 id (실패 시 None).

    ragas_version / judge_model을 반드시 함께 기록한다 — RAGAS는 버전 간
    메트릭 계산식이 바뀔 수 있고 judge가 달라지면 점수 비교가 무의미해진다.
    없으면 "삭제율이 왜 갑자기 올랐는가"를 추적할 수 없다(spec §4.2).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ragas_evaluations
                        (cache_key, normalized_question, original_question, answer,
                         contexts, context_char_limit,
                         faithfulness, answer_relevancy, context_precision, composite_score,
                         verdict, dry_run,
                         ragas_version, judge_provider, judge_model)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s)
                    RETURNING id
                """, (
                    cache_key, normalized_question, original_question, answer,
                    json.dumps(contexts, ensure_ascii=False), context_char_limit,
                    scores.get("faithfulness"),
                    scores.get("answer_relevancy"),
                    scores.get("context_precision"),
                    composite,
                    verdict, dry_run,
                    ragas_version, judge_provider, judge_model,
                ))
                new_id = cur.fetchone()[0]
                conn.commit()
        return new_id
    except Exception as e:
        logger.error("평가 결과 저장 실패: %s", e, exc_info=True)
        return None


def score_distribution(metric: str = "faithfulness", buckets: int = 10) -> list[tuple]:
    """④단계 분포 확인용 (spec §6.3).

    metric은 컬럼명이라 파라미터 바인딩이 안 되므로 화이트리스트로 검증한다.
    """
    allowed = {"faithfulness", "answer_relevancy", "context_precision", "composite_score"}
    if metric not in allowed:
        raise ValueError(f"허용되지 않은 메트릭: {metric} (가능: {sorted(allowed)})")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # width_bucket은 값이 정확히 1.0이면 상한 초과로 buckets+1을 돌려준다.
            # 1.0은 만점이지 이상치가 아니므로 least()로 마지막 버킷에 합친다.
            cur.execute(f"""
                SELECT least(width_bucket({metric}, 0, 1, %s), %s) AS bucket,
                       count(*),
                       round(avg({metric})::numeric, 3)
                FROM ragas_evaluations
                WHERE {metric} IS NOT NULL
                GROUP BY 1 ORDER BY 1
            """, (buckets, buckets))
            return cur.fetchall()


def verdict_summary() -> list[tuple]:
    """판정별 건수 — 배치 후 요약 출력용."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT verdict, count(*), round(avg(composite_score)::numeric, 3)
                FROM ragas_evaluations
                GROUP BY 1 ORDER BY 2 DESC
            """)
            return cur.fetchall()
