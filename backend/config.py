# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== Provider 선택 ====================
PROVIDER = os.getenv("PROVIDER")
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", PROVIDER)  # 미설정 시 PROVIDER와 동일

# ==================== Upstage ====================
UPSTAGE_API_KEY  = os.getenv("UPSTAGE_API_KEY")
UPSTAGE_BASE_URL       = os.getenv("UPSTAGE_BASE_URL")
UPSTAGE_EMBED_BASE_URL = os.getenv("UPSTAGE_EMBED_BASE_URL")
UPSTAGE_LLM_MODEL   = os.getenv("UPSTAGE_LLM_MODEL")
UPSTAGE_EMBED_MODEL = os.getenv("UPSTAGE_EMBED_MODEL")
UPSTAGE_EMBED_DIM   = 4096

# ==================== OpenAI ====================
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
OPENAI_LLM_MODEL   = os.getenv("OPENAI_LLM_MODEL")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL")
OPENAI_EMBED_DIM   = 1536

# ==================== Ollama ====================
OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_LLM_MODEL   = os.getenv("OLLAMA_LLM_MODEL")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
OLLAMA_EMBED_DIM   = int(os.getenv("OLLAMA_EMBED_DIM", "768"))    # nomic-embed-text 기본값

# ==================== Judge Provider ====================
JUDGE_PROVIDER       = os.getenv("JUDGE_PROVIDER", PROVIDER)
JUDGE_UPSTAGE_MODEL  = os.getenv("JUDGE_UPSTAGE_MODEL", UPSTAGE_LLM_MODEL)
JUDGE_OPENAI_MODEL   = os.getenv("JUDGE_OPENAI_MODEL", OPENAI_LLM_MODEL)
JUDGE_OLLAMA_MODEL   = os.getenv("JUDGE_OLLAMA_MODEL", OLLAMA_LLM_MODEL)
JUDGE_OLLAMA_BASE_URL = os.getenv("JUDGE_OLLAMA_BASE_URL", OLLAMA_BASE_URL)

# ==================== Guardrail Provider ====================
# 입력 가드레일(탈옥/주제 판단)용 프로바이더.
# 미설정 시 openai — 기존 동작(gpt-4o-mini 고정)과 호환.
# Structured Outputs(strict json_schema)를 지원하는 프로바이더여야 한다.
# upstage: Solar 계열 지원 확인됨 / ollama: 모델마다 다르므로 권장하지 않음.
# 주의) 유해 콘텐츠 검사(moderations API)는 OpenAI 전용이라 이 설정과 무관하게
#       항상 OPENAI_API_KEY를 사용한다.
GUARDRAIL_PROVIDER      = os.getenv("GUARDRAIL_PROVIDER", "openai")
GUARDRAIL_UPSTAGE_MODEL = os.getenv("GUARDRAIL_UPSTAGE_MODEL", UPSTAGE_LLM_MODEL)
GUARDRAIL_OPENAI_MODEL  = os.getenv("GUARDRAIL_OPENAI_MODEL", "gpt-4o-mini")
GUARDRAIL_OLLAMA_MODEL  = os.getenv("GUARDRAIL_OLLAMA_MODEL", OLLAMA_LLM_MODEL)

# 문서 충분성 판단용 프로바이더 — 입력 가드레일과 독립적으로 설정한다.
# 같은 문서를 판정해 본 결과 Solar가 gpt-4o-mini보다 훨씬 엄격해(창조과학 질문 5개 중
# 충분 판정 0개 vs 3개) not_resolved → 재작성 루프가 과도하게 돌아서 기본값은 openai.
DOC_JUDGE_PROVIDER      = os.getenv("DOC_JUDGE_PROVIDER", "openai")
DOC_JUDGE_UPSTAGE_MODEL = os.getenv("DOC_JUDGE_UPSTAGE_MODEL", UPSTAGE_LLM_MODEL)
DOC_JUDGE_OPENAI_MODEL  = os.getenv("DOC_JUDGE_OPENAI_MODEL", "gpt-4o-mini")
DOC_JUDGE_OLLAMA_MODEL  = os.getenv("DOC_JUDGE_OLLAMA_MODEL", OLLAMA_LLM_MODEL)

# ==================== 현재 Provider 기준 값 ====================
if PROVIDER == "upstage":
    EMBED_DIM = UPSTAGE_EMBED_DIM
    LLM_MODEL = UPSTAGE_LLM_MODEL
elif PROVIDER == "openai":
    EMBED_DIM = OPENAI_EMBED_DIM
    LLM_MODEL = OPENAI_LLM_MODEL
elif PROVIDER == "ollama":
    EMBED_DIM = OLLAMA_EMBED_DIM
    LLM_MODEL = OLLAMA_LLM_MODEL
else:
    raise ValueError(f"지원하지 않는 PROVIDER: {PROVIDER}. (upstage / openai / ollama)")

# ==================== DB 접속 정보 ====================
DB_HOST     = os.getenv("DB_HOST")
DB_NAME     = os.getenv("DB_NAME")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT     = os.getenv("DB_PORT")

# ==================== DB 연결 함수 ====================
from contextlib import contextmanager

@contextmanager
def get_conn():
    import psycopg2
    conn = psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASSWORD, port=DB_PORT
    )
    try:
        yield conn
    finally:
        conn.close()