import os
from config import get_conn
from llm_factory import get_embedding

embedding_model = get_embedding()

BASE_URL = "https://api.bebot.co.kr"

def _to_image_url(file_path: str) -> str:
    return f"{BASE_URL}/images/{os.path.basename(file_path)}"


def retrieve_pages(question: str, top_k: int = 5):
    q_emb = embedding_model.embed_query(question)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH top_chunks AS (
                    (
                        SELECT book_name, page_num, content, embedding <=> %s::vector AS score
                        FROM book_en
                        ORDER BY score ASC
                        LIMIT %s
                    )
                    UNION ALL
                    (
                        SELECT book_name, page_num, content, embedding <=> %s::vector AS score
                        FROM book_ko
                        ORDER BY score ASC
                        LIMIT %s
                    )
                ),
                sorted_top AS (
                    SELECT book_name, page_num, content, score
                    FROM top_chunks
                    ORDER BY score ASC
                    LIMIT %s
                )
                SELECT
                    st.book_name,
                    st.page_num,
                    st.content,
                    st.score,
                    ARRAY_AGG(DISTINCT i.file_path) FILTER (WHERE i.file_path IS NOT NULL) AS images
                FROM sorted_top st
                LEFT JOIN book_images i
                  ON st.book_name = i.book_name
                 AND st.page_num = i.page_num
                GROUP BY st.book_name, st.page_num, st.content, st.score
                ORDER BY st.score ASC;
            """, (q_emb, top_k, q_emb, top_k, top_k))
            # /* MODIFIED CODE END */

            rows = cur.fetchall()

    results = []
    for row in rows:
        book_name, page_num, content, score, images = row

        results.append({
            "book": book_name,
            "page": page_num,
            "content": content,
            "score": float(score),
            "type": "book",
            "images": [_to_image_url(p) for p in images] if images else []
        })
    return results