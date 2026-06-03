# 질문을 한국어 -> 영어 번역
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
