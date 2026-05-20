from config import get_conn
from llm_factory import get_embedding

embedding_model = get_embedding()


def retrieve_pages(question: str, top_k: int = 5):
    print(f"\n🔎 [Book] 질문: {question}")
    q_emb = embedding_model.embed_query(question)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.book_name,
                    t.page_num,
                    MIN(t.content) AS content,
                    MIN(t.embedding <=> %s::vector) AS score,
                    ARRAY_AGG(DISTINCT i.file_path)
                        FILTER (WHERE i.file_path IS NOT NULL) AS images
                FROM (
                    SELECT book_name, page_num, content, embedding FROM book_en
                    UNION ALL
                    SELECT book_name, page_num, content, embedding FROM book_ko
                ) t
                LEFT JOIN book_images i
                  ON t.book_name = i.book_name
                 AND t.page_num = i.page_num
                GROUP BY t.book_name, t.page_num
                ORDER BY score
                LIMIT %s;
            """, (q_emb, top_k))
            rows = cur.fetchall()

    print(f"📄 통합 검색 결과: {len(rows)}개")
    results = []
    for book_name, page_num, content, score, images in rows:
        print(f"   📘 [{book_name}] 페이지 {page_num}")
        print(f"      ⭐ score: {score}")
        if images:
            for img in images:
                if img:
                    print(f"      🖼️ {img}")
        results.append({
            "book": book_name,
            "page": page_num,
            "content": content,
            "score": float(score),
            "type": "book",
            "images": images or []
        })
    return results