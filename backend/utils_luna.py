# 질문을 한국어 -> 영어 번역
from config import LLM_MODEL, PROVIDER
from llm_factory import get_client


def detect_language(text: str) -> str:
    return "ko" if any("가" <= c <= "힣" for c in text) else "en"


# ==================== temperature 미지원 모델 대응 ====================
# gpt-5.6-luna 등 일부 최신 모델은 temperature 커스텀 값을 받지 않고
# 기본값(1)만 허용함 → 이런 모델일 땐 temperature 파라미터 자체를 생략해야 함.
# 새 모델 추가 시 이 리스트에 이름 추가하면 됨.
_NO_CUSTOM_TEMPERATURE_MODELS = (
    "gpt-5.6-luna",
    # "gpt-5.6-terra",  # 필요시 여기에 추가
)


def temperature_kwargs(temperature: float = 0) -> dict:
    """모델이 커스텀 temperature를 지원하면 {'temperature': temperature},
    지원하지 않으면 빈 dict를 반환한다."""
    if PROVIDER == "openai" and LLM_MODEL in _NO_CUSTOM_TEMPERATURE_MODELS:
        return {}
    return {"temperature": temperature}
# =======================================================================


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
        max_completion_tokens=200,
        **temperature_kwargs(0),
    )
    translated = res.choices[0].message.content.strip()
    return translated