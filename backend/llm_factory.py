# llm_factory.py
from config import (
    PROVIDER,
    UPSTAGE_API_KEY, UPSTAGE_BASE_URL, UPSTAGE_LLM_MODEL, UPSTAGE_EMBED_MODEL,
    OPENAI_API_KEY,  OPENAI_LLM_MODEL,  OPENAI_EMBED_MODEL,
    OLLAMA_BASE_URL, OLLAMA_LLM_MODEL,  OLLAMA_EMBED_MODEL,
)


def get_llm():
    """LangChain LLM — structured output, chain용"""
    if PROVIDER == "upstage":
        from langchain_upstage import ChatUpstage
        return ChatUpstage(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_BASE_URL)
    elif PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_LLM_MODEL)
    elif PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_LLM_MODEL)
    else:
        raise ValueError(f"지원하지 않는 PROVIDER: {PROVIDER}")


def get_embedding():
    """임베딩 모델 — EMBED_PROVIDER 우선, 미설정 시 PROVIDER 사용"""
    from config import EMBED_PROVIDER
    if EMBED_PROVIDER == "upstage":
        from langchain_upstage import UpstageEmbeddings
        return UpstageEmbeddings(upstage_api_key=UPSTAGE_API_KEY, model=UPSTAGE_EMBED_MODEL)
    elif EMBED_PROVIDER == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=OPENAI_API_KEY, model=OPENAI_EMBED_MODEL)
    elif EMBED_PROVIDER == "ollama":
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(base_url=OLLAMA_BASE_URL, model=OLLAMA_EMBED_MODEL)
    else:
        raise ValueError(f"지원하지 않는 EMBED_PROVIDER: {EMBED_PROVIDER}")


def get_judge_llm():
    """Ragas 평가용 judge LLM — JUDGE_PROVIDER로 답변 생성 모델과 독립 설정 가능"""
    from config import (
        JUDGE_PROVIDER,
        JUDGE_OLLAMA_MODEL, JUDGE_OLLAMA_BASE_URL,
        JUDGE_OPENAI_MODEL,
        JUDGE_UPSTAGE_MODEL, UPSTAGE_API_KEY, UPSTAGE_BASE_URL,
        OPENAI_API_KEY,
    )
    if JUDGE_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(base_url=JUDGE_OLLAMA_BASE_URL, model=JUDGE_OLLAMA_MODEL)
    elif JUDGE_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=OPENAI_API_KEY, model=JUDGE_OPENAI_MODEL)
    elif JUDGE_PROVIDER == "upstage":
        from langchain_upstage import ChatUpstage
        return ChatUpstage(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_BASE_URL, model=JUDGE_UPSTAGE_MODEL)
    else:
        raise ValueError(f"지원하지 않는 JUDGE_PROVIDER: {JUDGE_PROVIDER}")


def get_model_info() -> dict:
    """현재 설정된 답변 생성 모델과 judge 모델 정보를 반환"""
    from config import (
        PROVIDER, UPSTAGE_LLM_MODEL, OPENAI_LLM_MODEL, OLLAMA_LLM_MODEL,
        JUDGE_PROVIDER, JUDGE_UPSTAGE_MODEL, JUDGE_OPENAI_MODEL, JUDGE_OLLAMA_MODEL,
    )
    _model_name = {
        "upstage": UPSTAGE_LLM_MODEL,
        "openai":  OPENAI_LLM_MODEL,
        "ollama":  OLLAMA_LLM_MODEL,
    }
    _judge_name = {
        "upstage": JUDGE_UPSTAGE_MODEL,
        "openai":  JUDGE_OPENAI_MODEL,
        "ollama":  JUDGE_OLLAMA_MODEL,
    }
    return {
        "answer_model": f"{PROVIDER}/{_model_name.get(PROVIDER, '?')}",
        "judge_model":  f"{JUDGE_PROVIDER}/{_judge_name.get(JUDGE_PROVIDER, '?')}",
    }


def get_client():
    """openai.OpenAI 클라이언트 — chat.completions.create 직접 호출용"""
    from openai import OpenAI
    if PROVIDER == "upstage":
        return OpenAI(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_BASE_URL)
    elif PROVIDER == "openai":
        return OpenAI(api_key=OPENAI_API_KEY)
    elif PROVIDER == "ollama":
        # Ollama는 OpenAI 호환 엔드포인트 제공
        return OpenAI(api_key="ollama", base_url=f"{OLLAMA_BASE_URL}/v1")
    else:
        raise ValueError(f"지원하지 않는 PROVIDER: {PROVIDER}")
