"""2단계: 임베딩·벡터 DB·검색. 세 방식이 모두 이 파일의 함수를 같이 쓴다.

- build_index(): articles.jsonl → 임베딩 → Chroma 저장
- search(질문, domain): 비슷한 조문 top-k
- get_article(법령명, 조번호): 번호로 정확히 조회 (툴콜링용)
"""
import json
import re
from functools import lru_cache

import chromadb

import config


class OpenAIEmbedder:
    def __init__(self, model: str = config.EMBED_MODEL):
        from openai import OpenAI
        self.client = OpenAI(api_key=config.OPENAI_API_KEY or None)
        self.model = model

    def __call__(self, texts: list[str]) -> list[list[float]]:
        out = []
        for i in range(0, len(texts), 100):  # 한 번에 100개씩
            resp = self.client.embeddings.create(model=self.model, input=texts[i:i + 100])
            out += [d.embedding for d in resp.data]
        return out


_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = OpenAIEmbedder()
    return _embedder


def set_embedder(fn) -> None:
    """테스트에서 가짜 임베딩으로 바꿀 때 사용."""
    global _embedder
    _embedder = fn


def _collection(reset: bool = False):
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if reset:
        try:
            client.delete_collection(config.COLLECTION)
        except Exception:
            pass
    return client.get_or_create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})


def load_articles() -> list[dict]:
    lines = config.ARTICLES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def embed_text(c: dict) -> str:
    # 법령명·조번호·제목을 본문 앞에 붙여 임베딩 (제목만 맞아도 걸리도록)
    return f"{c['law_name']} 제{c['article_no']}조({c['title']})\n{c['text']}"


def build_index() -> int:
    chunks = load_articles()
    col = _collection(reset=True)
    embed = get_embedder()
    for i in range(0, len(chunks), 200):
        batch = chunks[i:i + 200]
        col.add(
            ids=[c["id"] for c in batch],
            embeddings=embed([embed_text(c) for c in batch]),
            documents=[c["text"] for c in batch],
            metadatas=[{k: c[k] for k in ("domain", "law_name", "law_type", "article_no",
                                          "title", "effective_date", "part")} for c in batch],
        )
    _articles_by_key.cache_clear()
    return len(chunks)


def search(query: str, domain: str | None = None, k: int = config.TOP_K) -> list[dict]:
    """질문과 비슷한 조문 top-k. domain을 주면 그 분야 안에서만 찾는다."""
    col = _collection()
    res = col.query(
        query_embeddings=get_embedder()([query]),
        n_results=k,
        where={"domain": domain} if domain else None,
    )
    hits = []
    for meta, doc, dist in zip(res["metadatas"][0], res["documents"][0], res["distances"][0]):
        hits.append({**meta, "text": doc, "score": round(1 - dist, 4)})
    return hits


@lru_cache(maxsize=1)
def _articles_by_key() -> dict:
    by = {}
    for c in load_articles():
        by.setdefault((c["law_name"], c["article_no"]), []).append(c)
    return by


def normalize_article_no(s: str) -> str:
    """'제44조의2', '44조의 2', '44-2' → '44의2'"""
    s = re.sub(r"\s", "", str(s)).replace("제", "").replace("조", "")
    s = s.replace("-", "의")
    return s


def get_article(law_name: str, article_no: str) -> dict | None:
    parts = _articles_by_key().get((law_name.strip(), normalize_article_no(article_no)))
    if not parts:
        return None
    parts = sorted(parts, key=lambda c: c["part"])
    return {**parts[0], "text": "\n".join(p["text"] for p in parts)}


def format_hits(hits: list[dict]) -> str:
    """검색 결과를 LLM 프롬프트에 넣을 문자열로."""
    return "\n\n".join(
        f"[{h['law_name']} 제{h['article_no']}조({h['title']})]\n{h['text']}" for h in hits)
