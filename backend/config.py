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