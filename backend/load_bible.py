"""
load_bible.py — 개역한글 txt → PostgreSQL bible_krv 테이블 적재

기대하는 줄 형식 (대부분의 개역한글 txt 배포본):
    창1:1 태초에 하나님이 천지를 창조하시니라
    창1:1 <천지 창조> 태초에 ...        ← <소제목>은 기본적으로 제거

사용:
    python load_bible.py --file data/bible_krv.txt --dry-run   # 파싱 결과만 확인
    python load_bible.py --file data/bible_krv.txt             # DB 적재
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from psycopg2.extras import execute_values

from bible_tool import BOOKS, resolve_book
from config import get_conn

LINE_RE = re.compile(r"^\s*([가-힣]+)\s*(\d+)\s*:\s*(\d+)\s*(.*)$")
HEADING_RE = re.compile(r"^\s*<[^>]*>\s*")

DDL = """
CREATE TABLE IF NOT EXISTS bible_krv (
    book_no   SMALLINT NOT NULL,
    book_abbr TEXT     NOT NULL,
    book_name TEXT     NOT NULL,
    chapter   SMALLINT NOT NULL,
    verse     SMALLINT NOT NULL,
    text      TEXT     NOT NULL,
    PRIMARY KEY (book_no, chapter, verse)
);
"""

UPSERT = """
INSERT INTO bible_krv (book_no, book_abbr, book_name, chapter, verse, text)
VALUES %s
ON CONFLICT (book_no, chapter, verse) DO UPDATE SET text = EXCLUDED.text
"""


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("인코딩을 판별할 수 없습니다 (utf-8 / cp949 / euc-kr 모두 실패)")


def parse(text: str, strip_headings: bool):
    rows: dict[tuple, list] = {}
    last_key = None
    unknown_books: Counter = Counter()
    skipped = continued = 0

    for line in text.splitlines():
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            if last_key:  # 줄바꿈된 본문 → 직전 절에 이어붙임
                rows[last_key][5] += " " + line.strip()
                continued += 1
            else:
                skipped += 1
            continue

        abbr, ch, vs, body = m.groups()
        book_no = resolve_book(abbr)
        if book_no is None:
            unknown_books[abbr] += 1
            last_key = None
            continue
        if strip_headings:
            body = HEADING_RE.sub("", body)

        key = (book_no, int(ch), int(vs))
        rows[key] = [book_no, BOOKS[book_no - 1][0], BOOKS[book_no - 1][1],
                     int(ch), int(vs), body.strip()]
        last_key = key

    return list(rows.values()), unknown_books, skipped, continued


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="개역한글 txt 경로")
    ap.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 파싱 결과만 출력")
    ap.add_argument("--keep-headings", action="store_true", help="<소제목> 유지")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"❌ 파일 없음: {path}")

    text, enc = read_text(path)
    rows, unknown, skipped, continued = parse(text, strip_headings=not args.keep_headings)

    books_found = {r[0] for r in rows}
    print(f"✅ 인코딩: {enc}")
    print(f"✅ 파싱된 절: {len(rows):,}개 (보통 3만1천 절 안팎)")
    print(f"✅ 책 수: {len(books_found)}/66")
    if missing := [BOOKS[i - 1][1] for i in range(1, 67) if i not in books_found]:
        print(f"⚠️ 누락된 책: {missing}")
    if unknown:
        print(f"⚠️ 알 수 없는 책 약어: {dict(unknown)}  → bible_tool.py 별칭 추가 필요")
    print(f"ℹ️ 형식 불일치로 건너뛴 줄: {skipped}, 이어붙인 줄: {continued}")
    for r in sorted(rows)[:3]:
        print(f"   {r[2]} {r[3]}:{r[4]} {r[5][:50]}")

    if args.dry_run:
        print("\n(dry-run) DB에는 쓰지 않았습니다.")
        return
    if not rows:
        sys.exit("❌ 파싱된 절이 없습니다. 파일 형식을 확인하세요 (head -5 파일).")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        execute_values(cur, UPSERT, rows, page_size=1000)
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM bible_krv")
        print(f"\n🎉 bible_krv 적재 완료: 총 {cur.fetchone()[0]:,}절")


if __name__ == "__main__":
    main()
