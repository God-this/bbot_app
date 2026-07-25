import os
from config import get_conn
from llm_factory import get_embedding

embedding_model = get_embedding()

BASE_URL = "https://api.bebot.co.kr"

def _to_image_url(file_path: str) -> str:
    return f"{BASE_URL}/images/{os.path.basename(file_path)}"


def _book_images_table_exists(cur) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables WHERE table_name = 'book_images'
        );
    """)
    return cur.fetchone()[0]


def retrieve_pages(question: str, top_k: int = 5):
    q_emb = embedding_model.embed_query(question)

    with get_conn() as conn:
        with conn.cursor() as cur:
            has_images_table = _book_images_table_exists(cur)

            if has_images_table:
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
            else:
                # book_images 테이블이 없는 환경(예: 아직 마이그레이션 안 된 운영 DB)
                # → 이미지 없이 텍스트 검색만 수행
                print("⚠️ book_images 테이블이 없습니다. 이미지 없이 검색합니다.")
                cur.execute("""
                    SELECT
                        t.book_name,
                        t.page_num,
                        MIN(t.content) AS content,
                        MIN(t.embedding <=> %s::vector) AS score
                    FROM (
                        SELECT book_name, page_num, content, embedding FROM book_en
                        UNION ALL
                        SELECT book_name, page_num, content, embedding FROM book_ko
                    ) t
                    GROUP BY t.book_name, t.page_num
                    ORDER BY score
                    LIMIT %s;
                """, (q_emb, top_k))

            rows = cur.fetchall()

    results = []
    for row in rows:
        if has_images_table:
            book_name, page_num, content, score, images = row
        else:
            book_name, page_num, content, score = row
            images = None

        results.append({
            "book": book_name,
            "page": page_num,
            "content": content,
            "score": float(score),
            "type": "book",
            "images": [_to_image_url(p) for p in images] if images else []
        })
    return results