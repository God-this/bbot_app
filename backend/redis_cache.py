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


# ==================== Exact Match Cache ====================

def get_cached_answer(question):
    result = r.get(question)

    if result:
        return json.loads(result)

    return None


def save_cached_answer(question, answer_data, expire=3600):
    r.setex(
        question,
        expire,
        json.dumps(answer_data, ensure_ascii=False)
    )


# ==================== Semantic Cache ====================

def get_embedding(text):
    return embedding_model.embed_query(text)


def save_semantic_cache(query, data):
    embedding = get_embedding(query)

    payload = {
        "query": query,
        "embedding": embedding,
        "data": data
    }

    r.set(
        f"semantic:{query}",
        json.dumps(payload, ensure_ascii=False)
    )

    logger.debug("Semantic Cache Saved to Redis!")


def search_semantic_cache(query, threshold=0.99):
    query_embedding = get_embedding(query)

    best_score = 0
    best_result = None

    for key in r.scan_iter("semantic:*"):
        raw = r.get(key)

        if not raw:
            continue

        item = json.loads(raw)

        score = cosine_similarity(
            [query_embedding],
            [item["embedding"]]
        )[0][0]

        logger.debug("[Semantic Cache] query='%s' | score=%.4f (threshold=%s)", item['query'], score, threshold)

        if score > best_score:
            best_score = score
            best_result = item

    if best_score >= threshold:
        logger.debug("Semantic Cache Hit! best_score=%.4f >= threshold=%s", best_score, threshold)
        return best_result["data"]

    logger.debug("Semantic Cache Miss. best_score=%.4f < threshold=%s", best_score, threshold)
    return None
