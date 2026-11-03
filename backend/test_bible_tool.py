"""
test_bible_tool.py — 성경 tool calling 일괄 테스트 & 인용 검증

여러 질문으로 generate()를 캐시 없이 실행하고, 답변 속 성경 인용을 개역한글 DB 원문과 대조한다.

검사 항목 (인용 1건마다)
  - 장절 존재      : 인용한 책/장/절이 DB에 있는지
  - 본문 일치      : 따옴표 안 문구가 DB 원문에 그대로 들어 있는지 (공백·문장부호 무시)
  - 도구 조회 여부 : 그 구절을 이번 답변에서 도구로 실제 조회했는지 (조회 안 했으면 기억으로 쓴 것)
  - 관련성        : 자동 판단 불가 → CSV의 '관련성(수동)' 칸에 사람이 O/X 기입

사용
  python test_bible_tool.py                              # 내장 질문 20개
  python test_bible_tool.py --limit 5                    # 앞 5개만
  python test_bible_tool.py --questions q.txt            # 한 줄에 질문 하나
  python test_bible_tool.py --xlsx eval_data.xlsx --column question --limit 50

출력
  bible_test_logs/bible_test_YYYYMMDD_HHMM_answers.csv  (질문별 요약)
  bible_test_logs/bible_test_YYYYMMDD_HHMM_quotes.csv   (인용별 검증)
"""
import argparse
import csv
import difflib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import bible_tool
from bible_tool import BOOKS, get_bible_verses, resolve_book

DEFAULT_QUESTIONS = [
    # 창조
    "하나님은 세상을 며칠 만에 창조하셨나요?",
    "창세기 1장의 하루는 문자 그대로 24시간인가요?",
    "사람은 어떻게 창조되었나요?",
    "하와는 왜 아담의 갈빗대로 만들어졌나요?",
    # 홍수·방주
    "노아의 홍수는 실제 있었던 사건인가요?",
    "노아의 방주에 모든 동물이 들어갈 수 있었나요?",
    "홍수 이후 무지개는 어떤 의미인가요?",
    # 지구 나이·지질
    "지구의 나이는 몇 년인가요?",
    "그랜드캐니언은 어떻게 만들어졌나요?",
    "화석은 어떻게 만들어지나요?",
    # 진화론
    "진화론은 과학적으로 증명된 사실인가요?",
    "사람과 원숭이는 공통 조상에서 나왔나요?",
    "유신론적 진화론은 성경과 맞나요?",
    # 생물·설계
    "공룡은 사람과 같은 시대에 살았나요?",
    "DNA의 정보는 설계의 증거인가요?",
    "사람의 눈은 진화로 설명할 수 있나요?",
    # 기타
    "바벨탑 사건 이후 언어는 어떻게 나뉘었나요?",
    "죽음은 언제부터 세상에 들어왔나요?",
    # 영어 / 인용 직접 요청
    "Did God create the universe in six days?",
    "창조에 관한 성경 구절 세 개를 정확히 인용해 주세요",
]

# "본문" (요한복음 3:16, 개역한글) / “본문”(요 3:16) / '본문' (창세기 1:1-2)
QUOTE_RE = re.compile(
    r"[\"“'‘]([^\"”'’]{4,}?)[\"”'’]\s*\(\s*"
    r"([1-3]?\s?[가-힣A-Za-z]+)\s*(\d+)\s*[:장]\s*(\d+)\s*절?"
    r"(?:\s*[-~]\s*(\d+)\s*절?)?"
    r"[^)]*\)"
)
# 참조가 앞에 오는 인용: 창세기 7장 11절에서 "본문" / 요한복음 3:16은 "본문"
QUOTE_AFTER_RE = re.compile(
    r"([1-3]?\s?[가-힣]{1,8})\s*(\d+)\s*(?::|장\s*)(\d+)\s*절?"
    r"(?:\s*[-~]\s*(\d+)\s*절?)?"
    r"[^\"“'‘\n]{0,15}[\"“'‘]([^\"”'’]{4,}?)[\"”'’]"
)
# 따옴표 없는 장절 언급: (창세기 6:8) / 창세기 7장 11절
REF_RE = re.compile(
    r"([1-3]?\s?[가-힣]{1,8})\s*(\d+)\s*(?::|장\s*)(\d+)\s*절?"
)


def norm_text(s: str) -> str:
    return re.sub(r"[\s\"'“”‘’.,;:!?·…\-~()\[\]]", "", s)


class ToolRecorder:
    """bible_tool.execute_tool_call을 감싸서 이번 질문에서 조회한 구절 범위를 기록"""

    def __init__(self):
        self.calls: list[dict] = []
        self._orig = bible_tool.execute_tool_call

    def __enter__(self):
        def wrapped(name, arguments):
            out = self._orig(name, arguments)
            try:
                args = json.loads(arguments or "{}")
                res = json.loads(out)
            except json.JSONDecodeError:
                args, res = {}, {}
            self.calls.append({"name": name, "args": args, "result": res})
            return out

        bible_tool.execute_tool_call = wrapped
        return self

    def __exit__(self, *exc):
        bible_tool.execute_tool_call = self._orig

    def fetched(self, book_no: int, chapter: int, verse: int) -> bool:
        for c in self.calls:
            res = c["result"]
            if c["name"] == "get_bible_verses" and "verses" in res:
                if resolve_book(c["args"].get("book")) != book_no:
                    continue
                if int(c["args"].get("chapter", -1)) != chapter:
                    continue
                if any(v["verse"] == verse for v in res["verses"]):
                    return True
            elif c["name"] == "search_bible":
                for r in res.get("results", []):
                    m = re.match(r"(.+) (\d+):(\d+)$", r["reference"])
                    if m and resolve_book(m.group(1)) == book_no \
                            and int(m.group(2)) == chapter and int(m.group(3)) == verse:
                        return True
        return False

    def summary(self) -> str:
        parts = []
        for c in self.calls:
            res = c["result"]
            parts.append(res.get("reference")
                         or f"search({c['args'].get('keyword')})→{len(res.get('results', []))}건"
                         if "error" not in res else f"ERROR:{res['error']}")
        return " | ".join(parts)


def verify_quote(quote: str, book: str, ch: int, vs: int, ve: int | None, rec: ToolRecorder) -> dict:
    book_no = resolve_book(book)
    row = {
        "인용 문구": quote, "참조": f"{book} {ch}:{vs}" + (f"-{ve}" if ve else ""),
        "장절 존재": "", "본문 일치": "", "유사도": "", "DB 원문": "", "도구 조회": "",
    }
    if book_no is None:
        row.update({"장절 존재": "X(책 이름 인식 불가)", "본문 일치": "-", "도구 조회": "-"})
        return row

    res = get_bible_verses(book, ch, vs, ve or vs)
    if "error" in res:
        row.update({"장절 존재": "X", "본문 일치": "-", "도구 조회": "-"})
        return row

    db_text = " ".join(v["text"] for v in res["verses"])
    q, d = norm_text(quote), norm_text(db_text)
    exact = q in d
    ratio = difflib.SequenceMatcher(None, q, d).ratio() if not exact else 1.0
    fetched = all(rec.fetched(book_no, ch, v) for v in range(vs, (ve or vs) + 1))

    row.update({
        "장절 존재": "O",
        "본문 일치": "O" if exact else "X",
        "유사도": f"{ratio:.2f}",
        "DB 원문": db_text,
        "도구 조회": "O" if fetched else "X(기억으로 작성)",
    })
    return row


def extract_quotes(answer: str) -> list[tuple]:
    """(인용문, 책, 장, 시작절, 끝절) 목록. 두 형식에서 추출하고 중복 제거"""
    found: dict[tuple, tuple] = {}
    for m in QUOTE_RE.finditer(answer):
        item = (m.group(1).strip(), m.group(2).strip(), int(m.group(3)), int(m.group(4)),
                int(m.group(5)) if m.group(5) else None)
        found[(norm_text(item[0]), item[2], item[3])] = item
    for m in QUOTE_AFTER_RE.finditer(answer):
        if not resolve_book(m.group(1).strip()):
            continue
        item = (m.group(5).strip(), m.group(1).strip(), int(m.group(2)), int(m.group(3)),
                int(m.group(4)) if m.group(4) else None)
        found.setdefault((norm_text(item[0]), item[2], item[3]), item)
    return list(found.values())


def load_questions(args) -> list[str]:
    if args.questions:
        qs = [l.strip() for l in Path(args.questions).read_text(encoding="utf-8").splitlines() if l.strip()]
    elif args.xlsx:
        import pandas as pd
        df = pd.read_excel(args.xlsx)
        if args.column not in df.columns:
            raise SystemExit(f"❌ '{args.column}' 컬럼 없음. 컬럼 목록: {list(df.columns)}")
        qs = [str(q).strip() for q in df[args.column].dropna()]
    else:
        qs = DEFAULT_QUESTIONS
    return qs[: args.limit] if args.limit and args.limit > 0 else qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", help="질문 txt (한 줄에 하나)")
    ap.add_argument("--xlsx", help="질문이 들어있는 엑셀")
    ap.add_argument("--column", default="question", help="엑셀 질문 컬럼명")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (0=전체)")
    args = ap.parse_args()

    from bbot_graph import generate  # 무거운 import는 인자 확인 후

    questions = load_questions(args)
    out_dir = Path("bible_test_logs")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    ans_path = out_dir / f"bible_test_{stamp}_answers.csv"
    quo_path = out_dir / f"bible_test_{stamp}_quotes.csv"

    print(f"🧪 질문 {len(questions)}개 테스트 (캐시 OFF)")
    print(f"   FORCE_FIRST_TOOL={bible_tool.FORCE_FIRST_TOOL}, ENABLE_BIBLE_TOOL={bible_tool.ENABLE_BIBLE_TOOL}\n")

    answer_rows, quote_rows = [], []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q}")
        t0 = time.time()
        with ToolRecorder() as rec:
            try:
                answer, _ = generate(q, use_cache=False)
                err = ""
            except Exception as e:
                answer, err = "", f"{type(e).__name__}: {e}"
        elapsed = time.time() - t0

        quotes = [verify_quote(qt, bk, ch, vs, ve, rec) for qt, bk, ch, vs, ve in extract_quotes(answer)]
        refs = sorted({f"{b.strip()} {c}:{v}" for b, c, v in REF_RE.findall(answer)
                       if resolve_book(b.strip())})
        bad = [x for x in quotes if x["본문 일치"] != "O" or x["도구 조회"] != "O"]

        for x in quotes:
            quote_rows.append({"번호": i, "질문": q, **x, "관련성(수동)": ""})

        answer_rows.append({
            "번호": i, "질문": q, "응답시간(초)": f"{elapsed:.1f}",
            "도구 호출 수": len(rec.calls), "도구 조회 내역": rec.summary(),
            "인용 수": len(quotes), "문제 인용 수": len(bad),
            "장절 언급": ", ".join(refs),
            "마지막 문단": answer.strip().split("\n")[-1][:300] if answer else "",
            "답변": answer, "에러": err,
        })

        status = "❌" if err else ("⚠️" if bad else ("➖" if not quotes else "✅"))
        print(f"   {status} {elapsed:.1f}s | 도구 {len(rec.calls)}회 | 인용 {len(quotes)}건, 문제 {len(bad)}건"
              + (f" | {err}" if err else ""))
        for x in bad:
            print(f"      · {x['참조']} 일치={x['본문 일치']} 조회={x['도구 조회']} \"{x['인용 문구'][:40]}\"")

    for path, rows in ((ans_path, answer_rows), (quo_path, quote_rows)):
        if rows:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    total_q = len(quote_rows)
    exact = sum(r["본문 일치"] == "O" for r in quote_rows)
    fetched = sum(r["도구 조회"] == "O" for r in quote_rows)
    no_quote = sum(r["인용 수"] == 0 for r in answer_rows)
    errors = sum(bool(r["에러"]) for r in answer_rows)
    avg_t = sum(float(r["응답시간(초)"]) for r in answer_rows) / max(len(answer_rows), 1)

    print("\n" + "=" * 60)
    print("📊 요약")
    print("=" * 60)
    print(f"질문 수            : {len(answer_rows)} (에러 {errors})")
    print(f"평균 응답 시간     : {avg_t:.1f}초")
    print(f"인용 없는 답변     : {no_quote}개")
    print(f"전체 인용          : {total_q}건")
    if total_q:
        print(f"  본문 일치율      : {exact}/{total_q} ({exact / total_q:.0%})")
        print(f"  도구 조회율      : {fetched}/{total_q} ({fetched / total_q:.0%})")
    print(f"\n📁 {ans_path}\n📁 {quo_path if quote_rows else '(인용 없음)'}")
    print("👉 quotes.csv의 '관련성(수동)' 칸에 질문과 구절이 어울리는지 O/X로 기입하세요.")


if __name__ == "__main__":
    main()
