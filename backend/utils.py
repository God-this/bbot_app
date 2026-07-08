# 질문을 한국어 -> 영어 번역
import re
from config import LLM_MODEL
from llm_factory import get_client


def detect_language(text: str) -> str:
    return "ko" if any("가" <= c <= "힣" for c in text) else "en"


def translate_to_english(question: str) -> str:
    if detect_language(question) == "en":
        return question

    client = get_client()
    res = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate the following Korean question to English. "
                    "Keep technical terms (e.g. Gap Theory, Noah's Flood, "
                    "Cambrian Explosion) as-is. "
                    "Return only the translated text, nothing else."
                )
            },
            {"role": "user", "content": question}
        ],
        temperature=0,
        max_completion_tokens=200,
    )
    translated = res.choices[0].message.content.strip()
    return translated


# ==================== Reasoning 필드 제거 ====================

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_final_answer(message) -> str:
    """
    reasoning 모델 응답에서 최종 답변만 안전하게 추출.
    1) message.reasoning 같은 별도 필드는 애초에 안 씀 (content만 사용)
    2) 혹시 content 안에 <think>...</think> 형태로 섞여 들어온 경우 제거
    """
    content = message.content or ""
    content = _THINK_TAG_RE.sub("", content).strip()
    return content


def reasoning_kwargs() -> dict:
    """
    Upstage solar-pro3 전용 파라미터. PROVIDER가 upstage가 아니면
    빈 dict를 반환해서 openai/ollama 호출 시 에러 안 나게 함.
    """
    from config import PROVIDER
    if PROVIDER == "upstage":
        return {"reasoning_effort": "minimal"}
    return {}