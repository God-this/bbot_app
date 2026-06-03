from config import get_conn
from llm_factory import get_embedding

embedding_model = get_embedding()


def retrieve_web_documents(question: str, top_k: int = 5) -> list[dict]:
    """crawled_data 테이블에서 벡터 유사도 검색"""
    q_embedding = embedding_model.embed_query(question)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT title, url, content, content_embedding <=> %s::vector AS score
                FROM crawled_data
                ORDER BY score
                LIMIT %s
            """, (q_embedding, top_k))
            rows = cur.fetchall()

    docs = [{"title": r[0], "url": r[1], "content": r[2], "score": float(r[3]), "type": "web"} for r in rows]
    return docs