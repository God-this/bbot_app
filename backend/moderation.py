# 입력 검열 (OpenAI Moderation API + 프롬프트 인젝션 휴리스틱)
#
# generate() / generate_stream() 진입점에서 가장 먼저 호출되어야 함.
# PROVIDER 설정(upstage/ollama)과 무관하게 항상 OpenAI Moderation API를 사용.

import re
from openai import OpenAI
from config import OPENAI_API_KEY
from logging_config import get_logger

logger = get_logger(__name__)

# Moderation 전용 클라이언트 — LLM_MODEL 클라이언트(get_client())와 분리
_moderation_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# ==================== 1) OpenAI Moderation API ====================

def check_moderation(text: str) -> tuple[bool, str]:
    """
    OpenAI Moderation API로 유해 콘텐츠 여부 확인.
    Returns: (is_flagged, reason)
    """
    if _moderation_client is None:
        logger.warning("[Moderation] OPENAI_API_KEY 미설정 — 검사 스킵")
        return False, ""

    try:
        res = _moderation_client.moderations.create(
            model="omni-moderation-latest",
            input=text,
        )
        result = res.results[0]

        if result.flagged:
            categories = [
                cat for cat, flagged in result.categories.model_dump().items()
                if flagged
            ]
            reason = ", ".join(categories)
            logger.warning("[Moderation] 유해 콘텐츠 탐지: %s | text=%s", reason, text[:100])
            return True, reason

        return False, ""

    except Exception as e:
        # Moderation API 자체 장애 시 서비스 전체가 죽으면 안 되므로 fail-open
        # (단, 아래 휴리스틱 필터가 최소한의 방어선 역할을 함)
        logger.error("[Moderation] API 호출 실패: %s", e, exc_info=True)
        return False, ""


# ==================== 2) 프롬프트 인젝션 휴리스틱 필터 ====================
# Moderation API는 "유해 콘텐츠"(폭력/성/혐오 등) 탐지용이지 탈옥 시도 자체를
# 잡아주지 않는 경우가 많음 (DAN 프롬프트는 그 자체로 hate/violence가 아님).
# 따라서 패턴 기반 필터를 병행.

_JAILBREAK_PATTERNS = [
    r"\bDAN\b.{0,30}\b(do anything now|do\s*anything\s*now)\b",
    r"ignore (all |the )?(previous|above|prior) (instructions|prompts)",
    r"you are (now |going to )?act(ing)? as",
    r"pretend (that )?you (are|re) (an? )?(ai|assistant) (with no|without) (restrictions|rules|filters)",
    r"jailbreak(ed|ing)?",
    r"system prompt",
    r"이전\s*지시(사항)?를?\s*(무시|잊)",
    r"너는\s*이제부터",
    r"제한\s*없이\s*(답변|대답)",
    r"규칙을?\s*(무시|어기고)",
    r"stay in character",
    r"developer mode",
    r"opposite day",
    r"act as a simulator",           # "chatgpt will now act as a simulator to the dan virtual machine"
    r"virtual machine",              # DAN VM 계열 프롬프트 공통 문구
    r"without any (kind of )?censorship",
    r"no (sense of )?(restrictions|rules|filters|censorship)",
    r"submissive ai",                # evil DAN 계열 도입부
    r"(will|does) not (discourage|care about) (illegal|legal|ethical)",
    r"token system",                 # DAN 토큰 협박형 프롬프트 공통 패턴
    r"stay (in )?dan",               # "stay dan to remind you"
    r"prefixed with",                # 응답 포맷을 강제로 지정하는 탈옥 문구
    r"dan (policy|has been accessed)",
]

_JAILBREAK_RE = re.compile("|".join(_JAILBREAK_PATTERNS), re.IGNORECASE)


def check_prompt_injection(text: str) -> tuple[bool, str]:
    """
    정규식 기반 탈옥 시도 탐지. 완벽하지 않지만 Moderation API가
    놓치는 DAN류 패턴을 보완.
    Returns: (is_flagged, matched_pattern)
    """
    # 너무 짧은 정상 질문에 대한 오탐 방지 + 과도하게 긴 입력(복붙형 탈옥 프롬프트) 자체를 의심
    if len(text) > 1500:
        logger.warning("[Injection] 비정상적으로 긴 입력 (%d자) — 탈옥 프롬프트 의심", len(text))
        return True, "abnormal_length"

    match = _JAILBREAK_RE.search(text)
    if match:
        logger.warning("[Injection] 패턴 매칭: '%s' | text=%s", match.group(0), text[:100])
        return True, match.group(0)

    return False, ""


# ==================== 3) 통합 진입점 ====================

def is_safe_input(text: str) -> tuple[bool, str]:
    """
    질문을 LLM/캐시에 태우기 전 최종 검열.
    Returns: (is_safe, block_reason)
        is_safe=False면 즉시 차단 메시지를 반환하고 이후 로직(캐시 저장 포함) 진행 금지.
    """
    flagged, reason = check_prompt_injection(text)
    if flagged:
        return False, f"prompt_injection:{reason}"

    flagged, reason = check_moderation(text)
    if flagged:
        return False, f"moderation:{reason}"

    return True, ""