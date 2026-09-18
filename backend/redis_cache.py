import json
from datetime import datetime, timezone

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

CACHE_KEY_PREFIX = "bebot:cache:"
TOMBSTONE_PREFIX = "bebot:rejected:"

DEFAULT_EXPIRE = 7776000    # 90일 — exact/semantic 공통 TTL, 히트 시 갱신
TOMBSTONE_EXPIRE = 2592000  # 30일 — 문서 보강 후 재도전 기회 부여

SCHEMA_VERSION = 2

# 캐시 payload에 남길 sources 키. chat_history(개인정보)와
# top_sources(다른 세 키와 중복)를 제외하기 위한 화이트리스트.
# auth.py의 save_chat_message가 DB에 저장할 때 쓰는 키 집합과 동일하다.
CACHED_SOURCE_KEYS = ("web_docs", "book_docs", "video_docs")

# 평가 배치(RAGAS) 가동 전에는 모든 항목이 pending으로 남는다.
# True로 두면 semantic 매칭이 사실상 전면 중단되므로,
# 배치가 실제로 pending을 소진하기 시작한 뒤에 켠다.
PENDING_SEMANTIC_EXCLUDED = False

# tombstone에 이 횟수 이상 누적되면 캐시 저장을 건너뛴다.
# 1회면 LLM 출력 변동만으로 영구 차단될 수 있어 여유를 둔다.
TOMBSTONE_FAIL_LIMIT = 3


def _cache_key(normalized_question: str) -> str:
    return f"{CACHE_KEY_PREFIX}{normalized_question}"


def _tombstone_key(normalized_question: str) -> str:
    return f"{TOMBSTONE_PREFIX}{normalized_question}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==================== 임베딩 ====================

def get_embedding(text):
    return embedding_model.embed_query(text)


# ==================== 저장 (write 1회) ====================

def _filter_sources(sources) -> dict:
    """캐시에 저장할 sources만 남긴다.

    chat_history는 캐시 키가 정규화된 질문뿐이라 전 사용자가 공유하는데,
    그대로 저장하면 타 사용자의 캐시 히트 시 이전 사용자의 대화 이력이 노출된다.
    top_sources는 web/book/video_docs와 중복이라 payload만 2배로 키운다.
    """
    if not isinstance(sources, dict):
        return {}
    return {k: v for k, v in sources.items() if k in CACHED_SOURCE_KEYS}


def save_answer_cache(normalized_question: str, original_question: str, answer_data: dict, expire: int = DEFAULT_EXPIRE):
    """
    answer_data({"answer":..., "sources":...})를 임베딩과 함께 한 번만 저장.
    exact 조회(정규화된 질문 → key)와 semantic 조회(임베딩 유사도) 모두
    이 하나의 키/값을 공유한다.

    반복적으로 품질 평가에서 탈락한 질문(tombstone)은 저장을 건너뛴다.
    답변 자체는 사용자에게 정상 제공되며, 캐시에만 올리지 않는다.
    """
    tombstone = get_tombstone(normalized_question)
    if tombstone and tombstone.get("fail_count", 0) >= TOMBSTONE_FAIL_LIMIT:
        logger.info(
            "tombstone 누적 %d회 — 캐시 저장 스킵: %s",
            tombstone["fail_count"], original_question
        )
        return

    embedding = get_embedding(original_question)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "query": original_question,
        "normalized_query": normalized_question,
        "embedding": embedding,
        "data": {
            "answer": answer_data.get("answer"),
            "sources": _filter_sources(answer_data.get("sources")),
        },
        "eval": {
            "status": "pending",
            "score": None,
            "evaluated_at": None,
        },
    }

    r.setex(
        _cache_key(normalized_question),
        expire,
        json.dumps(payload, ensure_ascii=False)
    )

    logger.debug("캐시 저장 완료 (embedding dim=%d) — question: %s", len(embedding), original_question)


# ==================== 조회 1단계: Exact ====================

def get_cached_answer(normalized_question: str):
    """정규화된 질문으로 정확히 일치하는 키를 바로 조회. 임베딩 계산 없음.

    구버전(v1) 스키마 항목은 폐기 대상이므로 조회 시 삭제하고 미스로 처리한다.
    히트한 항목은 계속 쓰이고 있다는 뜻이므로 TTL을 갱신한다.
    """
    key = _cache_key(normalized_question)
    raw = r.get(key)
    if not raw:
        return None

    try:
        item = json.loads(raw)
        if item.get("schema_version") != SCHEMA_VERSION:
            logger.info("구버전 스키마 캐시 삭제 — key=%s", normalized_question)
            r.delete(key)
            return None
        data = item["data"]
    except (json.JSONDecodeError, KeyError):
        logger.warning("캐시 항목 파싱 실패, 삭제 — key=%s", normalized_question)
        r.delete(key)
        return None

    r.expire(key, DEFAULT_EXPIRE)
    return data


# ==================== 조회 2단계: Semantic ====================

def search_semantic_cache(query: str, threshold: float = 0.96):
    """
    저장된 모든 캐시 항목을 순회하며 임베딩 유사도로 매칭.
    exact match에서 못 찾았을 때만 호출되는 fallback 경로.

    저장 시점의 임베딩 차원이 현재 provider의 차원과 다르면
    (예: provider 전환) 비교하지 않고 건너뛰며, 더 이상 쓸 수 없는
    데이터이므로 함께 정리(삭제)한다.

    아직 품질 평가를 받지 않은(pending) 항목은 PENDING_SEMANTIC_EXCLUDED가
    켜져 있을 때 semantic 후보에서 제외된다 — exact match로만 서빙된다.
    """
    query_embedding = get_embedding(query)
    query_dim = len(query_embedding)

    best_score = 0
    best_result = None
    skipped_dim_mismatch = 0
    skipped_pending = 0

    for key in r.scan_iter(f"{CACHE_KEY_PREFIX}*"):
        raw = r.get(key)
        if not raw:
            continue

        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if item.get("schema_version") != SCHEMA_VERSION:
            # 폐기된 v1 항목 — 비교 불가, 정리
            r.delete(key)
            continue

        if PENDING_SEMANTIC_EXCLUDED and item.get("eval", {}).get("status") == "pending":
            skipped_pending += 1
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

    if skipped_pending:
        logger.debug("[Semantic Cache] 미평가(pending) %d개 항목 제외", skipped_pending)

    if best_score >= threshold:
        logger.debug("Semantic Cache Hit! best_score=%.4f >= threshold=%s", best_score, threshold)
        # 갱신 대상은 조회한 질문이 아니라 실제로 매칭된 항목의 키다.
        r.expire(_cache_key(best_result["normalized_query"]), DEFAULT_EXPIRE)
        return best_result["data"]

    logger.debug("Semantic Cache Miss. best_score=%.4f < threshold=%s", best_score, threshold)
    return None


# ==================== 평가 결과 반영 ====================
# 아래 세 함수는 RAGAS 평가 배치(후속 단계)와 관리자 대시보드에서 호출한다.
# payload 스키마를 나중에 또 바꾸면 캐시를 전부 폐기해야 하므로 미리 넣어둔다.

def mark_evaluated(normalized_question: str, score: float) -> bool:
    """평가를 통과한 항목을 passed로 전환. 남은 TTL은 보존한다."""
    key = _cache_key(normalized_question)
    raw = r.get(key)
    if not raw:
        return False

    try:
        item = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("mark_evaluated 파싱 실패 — key=%s", normalized_question)
        return False

    ttl = r.ttl(key)
    if ttl is None or ttl < 0:
        # -1(무만료) / -2(키 없음) — 갱신 중 만료된 경우 포함
        ttl = DEFAULT_EXPIRE

    item["eval"] = {
        "status": "passed",
        "score": score,
        "evaluated_at": _now_iso(),
    }
    r.setex(key, ttl, json.dumps(item, ensure_ascii=False))
    return True


def delete_and_tombstone(normalized_question: str, score: float, reason: str,
                         original_question: str = "") -> int:
    """평가 탈락 항목을 캐시에서 제거하고 tombstone에 누적 기록.

    Returns: 누적된 fail_count
    """
    key = _cache_key(normalized_question)

    if not original_question:
        # 삭제하기 전에 원본 질문을 건져둔다 (대시보드 표시용)
        raw = r.get(key)
        if raw:
            try:
                original_question = json.loads(raw).get("query", "")
            except json.JSONDecodeError:
                pass

    r.delete(key)

    tkey = _tombstone_key(normalized_question)
    fail_count = r.hincrby(tkey, "fail_count", 1)
    r.hset(tkey, mapping={
        "original_query": original_question,
        "last_score": score,
        "last_rejected_at": _now_iso(),
        "reason": reason,
    })
    r.expire(tkey, TOMBSTONE_EXPIRE)

    logger.info(
        "캐시 탈락 처리 — fail_count=%d, score=%.4f, reason=%s, question=%s",
        fail_count, score, reason, normalized_question
    )
    return fail_count


def get_tombstone(normalized_question: str):
    """tombstone 조회. 없으면 None."""
    data = r.hgetall(_tombstone_key(normalized_question))
    if not data:
        return None

    # Redis Hash는 모든 값을 문자열로 돌려주므로 숫자 필드를 캐스팅한다.
    try:
        data["fail_count"] = int(data.get("fail_count", 0))
    except (TypeError, ValueError):
        data["fail_count"] = 0
    try:
        data["last_score"] = float(data["last_score"])
    except (KeyError, TypeError, ValueError):
        data["last_score"] = None

    return data


def clear_tombstone(normalized_question: str) -> bool:
    """관리자 수동 해제 — 문서 보강 후 재평가 기회를 준다."""
    return bool(r.delete(_tombstone_key(normalized_question)))