"""RAGAS judge LLM / 임베딩 구성.

`llm_factory.get_judge_llm()`은 LangChain 객체를 돌려주지만, ragas 0.4.x의
collections 메트릭은 `InstructorBaseRagasLLM`(네이티브 클라이언트 기반)을 요구한다.
그래서 여기서는 config의 JUDGE_* 설정을 읽어 ragas용 인스턴스를 따로 만든다.
설정 소스(config.JUDGE_*)는 동일하므로 두 경로가 갈라지지 않는다.

이 모듈은 ragas에 의존하므로 배치 프로세스에서만 import할 것.
"""

import os

from logging_config import get_logger

logger = get_logger(__name__)

# ragas 0.4.3의 InstructorModelArgs 기본값은 max_tokens=1024다.
# gpt-5/o-series는 max_completion_tokens만 받으므로 교체가 필요하고,
# 구조화 출력(Pydantic)에는 1024가 모자라 4096을 권장한다(ragas 문서).
JUDGE_MAX_COMPLETION_TOKENS = 4096


def _is_reasoning_model(model: str) -> bool:
    """gpt-5+/o-series 여부. ragas도 동일 판정을 하지만 'gpt-5.4-mini'처럼
    버전에 소수점이 있으면 int() 파싱에 실패해 오판한다(ragas 0.4.3).
    그 경우 max_tokens가 그대로 전송되어 400 에러가 나므로 여기서 다시 판정한다."""
    m = (model or "").lower()
    if m.startswith("o") and len(m) > 1 and m[1].isdigit():
        return True
    if m.startswith("gpt-"):
        version = m[4:].split("-")[0].split("_")[0]
        try:
            # '5.4' → 5 로 읽는다. ragas는 여기서 ValueError로 빠진다.
            return 5 <= int(float(version)) <= 19
        except ValueError:
            return False
    return m == "codex-mini"


def build_judge():
    """(judge_llm, judge_embeddings, judge_provider, judge_model) 반환.

    생성 모델과 judge 모델이 같으면 self-preference bias(자기 출력에 후한 점수)가
    생긴다. 차단하지는 않되 — 파이프라인 검증 목적으로 동일 모델을 쓸 수 있으므로 —
    경고를 남긴다. threshold 확정(④단계)은 반드시 분리된 judge로 낸 점수로 할 것.
    """
    from config import (
        PROVIDER, LLM_MODEL,
        JUDGE_PROVIDER, JUDGE_OPENAI_MODEL, JUDGE_UPSTAGE_MODEL,
        JUDGE_OLLAMA_MODEL, JUDGE_OLLAMA_BASE_URL,
        OPENAI_API_KEY, UPSTAGE_API_KEY, UPSTAGE_BASE_URL,
        OPENAI_EMBED_MODEL,
    )
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.embeddings.base import embedding_factory

    provider = (JUDGE_PROVIDER or "").lower()

    if provider == "openai":
        model = JUDGE_OPENAI_MODEL
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    elif provider == "upstage":
        # Upstage는 OpenAI 호환 API를 제공하므로 동일 클라이언트로 붙인다.
        model = JUDGE_UPSTAGE_MODEL
        client = AsyncOpenAI(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_BASE_URL)
    elif provider == "ollama":
        model = JUDGE_OLLAMA_MODEL
        client = AsyncOpenAI(api_key="ollama", base_url=f"{JUDGE_OLLAMA_BASE_URL}/v1")
    else:
        raise ValueError(f"지원하지 않는 JUDGE_PROVIDER: {JUDGE_PROVIDER}")

    if provider == PROVIDER and model == LLM_MODEL:
        logger.warning(
            "judge 모델이 생성 모델과 동일하다 (%s/%s). self-preference bias로 "
            "점수가 관대해질 수 있으므로 threshold 확정용으로는 쓰지 말 것. "
            "JUDGE_PROVIDER 또는 JUDGE_OPENAI_MODEL을 분리할 것.",
            provider, model,
        )

    llm = llm_factory(model, provider="openai", client=client)

    # ragas 기본 model_args(temperature=0.01, top_p=0.1, max_tokens=1024)를
    # 모델 제약에 맞게 보정한다. reasoning 계열은 temperature=1.0만 허용하고
    # top_p를 받지 않는다.
    args = llm.model_args
    if _is_reasoning_model(model):
        args.pop("max_tokens", None)
        args.pop("top_p", None)
        args["max_completion_tokens"] = JUDGE_MAX_COMPLETION_TOKENS
        args["temperature"] = 1.0
    else:
        # 판정은 결정적이어야 한다 (spec §6.5).
        args["temperature"] = 0

    # answer_relevancy가 임베딩 유사도를 쓴다. 판정 편향과 무관하므로
    # 서비스와 동일한 임베딩을 써도 된다(spec §6.5 원칙 3).
    embed_model = OPENAI_EMBED_MODEL or "text-embedding-3-small"
    if provider == "openai":
        embeddings = embedding_factory(provider="openai", model=embed_model, client=client)
    else:
        # judge가 openai가 아니어도 임베딩은 OpenAI를 쓴다 — 키가 없으면 실패한다.
        if not OPENAI_API_KEY:
            raise ValueError(
                "answer_relevancy에 임베딩이 필요하지만 OPENAI_API_KEY가 없다. "
                "JUDGE_PROVIDER를 openai로 두거나 OPENAI_API_KEY를 설정할 것."
            )
        embeddings = embedding_factory(
            provider="openai", model=embed_model, client=AsyncOpenAI(api_key=OPENAI_API_KEY)
        )

    logger.info("judge 구성 완료 — provider=%s model=%s embed=%s", provider, model, embed_model)
    return llm, embeddings, provider, model


def get_ragas_version() -> str:
    import ragas
    return getattr(ragas, "__version__", "unknown")
