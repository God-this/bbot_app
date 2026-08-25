# user_id 기준 요청 빈도 제한 (기존 Redis 인스턴스 재사용)

from fastapi import HTTPException
from logging_config import get_logger

logger = get_logger(__name__)

try:
    from redis_cache import r as _redis_client
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 15  # 분당 15회 — 정상 사용자는 충분, 봇/도배는 차단


def check_rate_limit(user_id: int):
    """
    분당 요청 수 제한. 초과 시 429 발생.
    Redis 미사용 환경(개발용 emptycan 등)에서는 자동 통과.
    """
    if not _REDIS_AVAILABLE:
        return

    key = f"ratelimit:{user_id}"
    try:
        current = _redis_client.incr(key)
        if current == 1:
            _redis_client.expire(key, WINDOW_SECONDS)

        if current > MAX_REQUESTS_PER_WINDOW:
            logger.warning("[RateLimit] user_id=%s 초과 (%d회/%d초)", user_id, current, WINDOW_SECONDS)
            raise HTTPException(
                status_code=429,
                detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
            )
    except HTTPException:
        raise
    except Exception as e:
        # Redis 장애 시 서비스 중단 방지 (fail-open)
        logger.error("[RateLimit] Redis 오류: %s", e, exc_info=True)
