"""qa_eval_queue 적재 — 서비스(BeBot) 측 쓰기 경로.

답변 생성 시 RAGAS 평가 대기 항목을 큐에 넣는다. 평가 자체는 별도 프로젝트
(bebot-cache-eval)가 이 큐를 읽어서 수행하므로, 이 모듈은 ragas에 의존하지 않고
표준 라이브러리와 config만 쓴다.

⚠️ 공유 계약 — 평가 프로젝트와 맞춰야 하는 것:
  - qa_eval_queue 테이블 스키마 (schema/qa_eval.sql, 평가 레포가 소유)
  - CONTEXT_CHAR_LIMIT = 800 (아래 주석 참조)
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
