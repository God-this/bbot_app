import json
import redis
from sklearn.metrics.pairwise import cosine_similarity
from llm_factory import get_embedding as _get_embedding_model
from logging_config import get_logger

logger = get_logger(__name__)

embedding_model = _get_embedding_model()

r = redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True
)

# ==================== 설정 ====================

CACHE_KEY_PREFIX = "cache:"
DEFAULT_EXPIRE = 604800  # 7일 — exact/semantic 공통 TTL


def _cache_key(normalized_question: str) -> str:
    return f"{CACHE_KEY_PREFIX}{normalized_question}"


# ==================== 임베딩 ====================

def get_embedding(text):
    return embedding_model.embed_query(text)


# ==================== 저장 (write 1회) ====================

def save_answer_cache(normalized_question: str, original_question: str, answer_data: dict, expire: int = DEFAULT_EXPIRE):
    """
    answer_data({"answer":..., "sources":...})를 임베딩과 함께 한 번만 저장.
    exact 조회(정규화된 질문 → key)와 semantic 조회(임베딩 유사도) 모두
    이 하나의 키/값을 공유한다.
    """
    embedding = get_embedding(original_question)

    payload = {
        "query": original_question,
        "normalized_query": normalized_question,
        "embedding": embedding,
        "data": answer_data,
    }

    r.setex(
        _cache_key(normalized_question),
        expire,
        json.dumps(payload, ensure_ascii=False)
    )

    logger.debug("캐시 저장 완료 (embedding dim=%d) — question: %s", len(embedding), original_question)


# ==================== 조회 1단계: Exact ====================

def get_cached_answer(normalized_question: str):
    """정규화된 질문으로 정확히 일치하는 키를 바로 조회. 임베딩 계산 없음."""
    raw = r.get(_cache_key(normalized_question))
    if not raw:
        return None

    try:
        item = json.loads(raw)
        return item["data"]
    except (json.JSONDecodeError, KeyError):
        logger.warning("캐시 항목 파싱 실패 — key=%s", normalized_question)
        return None


# ==================== 조회 2단계: Semantic ====================

def search_semantic_cache(query: str, threshold: float = 0.99):
    """
    저장된 모든 캐시 항목을 순회하며 임베딩 유사도로 매칭.
    exact match에서 못 찾았을 때만 호출되는 fallback 경로.

    저장 시점의 임베딩 차원이 현재 provider의 차원과 다르면
    (예: provider 전환) 비교하지 않고 건너뛰며, 더 이상 쓸 수 없는
    데이터이므로 함께 정리(삭제)한다.
    """
    query_embedding = get_embedding(query)
    query_dim = len(query_embedding)

    best_score = 0
    best_result = None
    skipped_dim_mismatch = 0

    for key in r.scan_iter(f"{CACHE_KEY_PREFIX}*"):
        raw = r.get(key)
        if not raw:
            continue

        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue

        cached_embedding = item.get("embedding")
        if not cached_embedding:
            continue

        if len(cached_embedding) != query_dim:
            # 다른 provider/모델로 저장된 옛 데이터 — 비교 불가, 정리
            skipped_dim_mismatch += 1
            r.delete(key)
            continue

        score = cosine_similarity([query_embedding], [cached_embedding])[0][0]

        logger.debug(
            "[Semantic Cache] query='%s' | score=%.4f (threshold=%s)",
            item.get("query", ""), score, threshold
        )

        if score > best_score:
            best_score = score
            best_result = item

    if skipped_dim_mismatch:
        logger.info(
            "[Semantic Cache] 차원 불일치로 %d개 항목 스킵 및 삭제 (현재 dim=%d)",
            skipped_dim_mismatch, query_dim
        )

    if best_score >= threshold:
        logger.debug("Semantic Cache Hit! best_score=%.4f >= threshold=%s", best_score, threshold)
        return best_result["data"]

    logger.debug("Semantic Cache Miss. best_score=%.4f < threshold=%s", best_score, threshold)
    return None