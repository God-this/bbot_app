"""설정: 분야별 법령 목록과 모델·경로.

새 케이스를 테스트하려면 DOMAINS에 분야와 법령 이름을 추가하고
`python collect.py` → `python build_index.py`를 다시 돌리면 된다.
법령 이름은 국가법령정보센터에 나오는 정식 이름과 같아야 한다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 분야 → 법령 이름 목록 (예시. 실험에 맞게 직접 고치기)
DOMAINS: dict[str, list[str]] = {
    "traffic": ["도로교통법", "도로교통법 시행령"],
    "jeonse": ["주택임대차보호법", "전세사기피해자 지원 및 주거안정에 관한 특별법"],
    "realestate": ["공인중개사법", "부동산 거래신고 등에 관한 법률"],
}

# 국가법령정보 공동활용(open.law.go.kr) 계정 ID의 @ 앞부분
LAW_OC = os.getenv("LAW_OC", "")
LAW_API_BASE = "https://www.law.go.kr/DRF"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

TOP_K = int(os.getenv("TOP_K", "5"))
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "4"))

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # API 원본 응답 (파싱 문제 확인용)
ARTICLES_PATH = DATA_DIR / "articles.jsonl"  # 조문 단위로 자른 결과
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION = "law_articles"
RESULTS_DIR = ROOT / "results"
