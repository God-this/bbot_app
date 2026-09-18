"""qa_eval_queue CRUD.

②단계에서는 적재(enqueue_eval)만 사용한다. 배치 조회/완료 처리
(fetch_pending / mark_queue_evaluated)는 ③단계 runner가 쓸 것을 함께 둔다.
"""

import json

from config import get_conn
from logging_config import get_logger

logger = get_logger(__name__)

# 프롬프트 조립(_build_context)이 모든 doc을 content[:800]으로 자르므로
# 평가 입력도 동일해야 측정값이 유효하다. 전체 content를 넣으면 LLM이 보지
# 못한 텍스트가 근거 후보에 들어가 실제보다 관대한 점수가 나온다.
# 값을 바꾸면 이전 점수와 직접 비교할 수 없으므로 행마다 함께 기록한다.
CONTEXT_CHAR_LIMIT = 800


def build_contexts(docs: list[dict]) -> list[str]:
    """reranked_documents에서 평가용 contexts를 추출한다.

    reranked_documents는 rerank top-5이고, sources의 web/book/video_docs는
    이를 분류만 한 것이라 동일한 문서 집합이다 (bbot_graph.rerank_node).
    따라서 프롬프트에 실린 텍스트와 여기서 뽑는 텍스트가 일치한다.
    """
    contexts = []
    for doc in docs:
        content = (doc or {}).get("content") or ""
        if content:
            contexts.append(content[:CONTEXT_CHAR_LIMIT])
    return contexts


def enqueue_eval(
    cache_key: str,
    normalized_question: str,
    original_question: str,
    answer: str,
    contexts: list[str],
) -> bool:
    """평가 대기 항목을 qa_eval_queue에 적재.

    Returns: 적재 성공 여부. 실패해도 예외를 올리지 않는다(fail-open) —
    평가 큐 적재 실패가 사용자 응답을 깨뜨려서는 안 된다. 누락된 항목은
    다음 동일 질문에서 다시 적재될 기회가 있고, 평가는 어차피 비동기다.
    """
    if not contexts:
        # contexts가 비면 faithfulness/context_precision을 계산할 수 없다.
        # 배치에서 걸러내느니 큐에 넣지 않는 편이 낫다.
        logger.debug("contexts 없음 — enqueue 스킵: %s", original_question)
        return False

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO qa_eval_queue
                        (cache_key, normalized_question, original_question,
                         answer, contexts, context_char_limit)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """, (
                    cache_key,
                    normalized_question,
                    original_question,
                    answer,
                    json.dumps(contexts, ensure_ascii=False),
                    CONTEXT_CHAR_LIMIT,
                ))
                conn.commit()
        logger.debug("평가 큐 적재 완료 — question: %s", original_question)
        return True
    except Exception as e:
        logger.error("평가 큐 적재 실패: %s", e, exc_info=True)
        return False


def fetch_pending(limit: int = 200) -> list[dict]:
    """미평가 항목을 오래된 순으로 조회 (③단계 배치용).

    BATCH_LIMIT 초과분은 Postgres 큐에 남아 다음 회차로 자연 이월된다.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, cache_key, normalized_question, original_question,
                       answer, contexts, context_char_limit
                FROM qa_eval_queue
                WHERE evaluated_at IS NULL
                ORDER BY created_at
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "cache_key": row[1],
            "normalized_question": row[2],
            "original_question": row[3],
            "answer": row[4],
            "contexts": row[5],
            "context_char_limit": row[6],
        }
        for row in rows
    ]


def mark_queue_evaluated(queue_ids: list[int]) -> int:
    """평가를 마친 큐 항목에 evaluated_at을 기록 (③단계 배치용).

    Returns: 갱신된 행 수
    """
    if not queue_ids:
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE qa_eval_queue
                SET evaluated_at = now()
                WHERE id = ANY(%s) AND evaluated_at IS NULL
            """, (queue_ids,))
            updated = cur.rowcount
            conn.commit()

    return updated
