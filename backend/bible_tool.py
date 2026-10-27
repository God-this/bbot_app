"""
bible_tool.py — 개역한글 성경 구절 조회 Tool (OpenAI 호환 function calling)

- get_bible_verses : 책/장/절로 정확한 본문 조회
- search_bible     : 키워드로 구절 검색 (장절이 기억나지 않을 때)
- chat_with_tools  : 동기 답변용 tool-calling 루프  (generate)
- stream_with_tools: 스트리밍 답변용 tool-calling 루프 (generate_stream)

사전 준비: load_bible.py 로 bible_krv 테이블을 만들어 두어야 함
단독 테스트:
    python bible_tool.py 요 3 16
    python bible_tool.py 시편 23
    python bible_tool.py --search 태초
    python bible_tool.py --llm "창세기 1장 1절 말씀 알려줘"
"""
import json
import os
import re
import sys
from typing import Iterator

from config import get_conn

ENABLE_BIBLE_TOOL = os.getenv("ENABLE_BIBLE_TOOL", "true").lower() == "true"
# 첫 LLM 호출에서 도구 호출을 강제 (tool_choice="required") — 곁들이는 인용까지 원문 보장
FORCE_FIRST_TOOL = os.getenv("FORCE_FIRST_TOOL", "true").lower() == "true"
MAX_VERSES = 30          # 한 번에 반환할 최대 절 수 (토큰 폭주 방지)
MAX_SEARCH_RESULTS = 10
MAX_TOOL_ROUNDS = 3      # tool 호출 왕복 최대 횟수
TRANSLATION = "개역한글"

# (약어, 정식 이름, 영어 이름) — 인덱스+1 = book_no
BOOKS = [
    ("창", "창세기", "Genesis"), ("출", "출애굽기", "Exodus"), ("레", "레위기", "Leviticus"),
    ("민", "민수기", "Numbers"), ("신", "신명기", "Deuteronomy"), ("수", "여호수아", "Joshua"),
    ("삿", "사사기", "Judges"), ("룻", "룻기", "Ruth"), ("삼상", "사무엘상", "1 Samuel"),
    ("삼하", "사무엘하", "2 Samuel"), ("왕상", "열왕기상", "1 Kings"), ("왕하", "열왕기하", "2 Kings"),
    ("대상", "역대상", "1 Chronicles"), ("대하", "역대하", "2 Chronicles"), ("스", "에스라", "Ezra"),
    ("느", "느헤미야", "Nehemiah"), ("에", "에스더", "Esther"), ("욥", "욥기", "Job"),
    ("시", "시편", "Psalms"), ("잠", "잠언", "Proverbs"), ("전", "전도서", "Ecclesiastes"),
    ("아", "아가", "Song of Songs"), ("사", "이사야", "Isaiah"), ("렘", "예레미야", "Jeremiah"),
    ("애", "예레미야애가", "Lamentations"), ("겔", "에스겔", "Ezekiel"), ("단", "다니엘", "Daniel"),
    ("호", "호세아", "Hosea"), ("욜", "요엘", "Joel"), ("암", "아모스", "Amos"),
    ("옵", "오바댜", "Obadiah"), ("욘", "요나", "Jonah"), ("미", "미가", "Micah"),
    ("나", "나훔", "Nahum"), ("합", "하박국", "Habakkuk"), ("습", "스바냐", "Zephaniah"),
    ("학", "학개", "Haggai"), ("슥", "스가랴", "Zechariah"), ("말", "말라기", "Malachi"),
    ("마", "마태복음", "Matthew"), ("막", "마가복음", "Mark"), ("눅", "누가복음", "Luke"),
    ("요", "요한복음", "John"), ("행", "사도행전", "Acts"), ("롬", "로마서", "Romans"),
    ("고전", "고린도전서", "1 Corinthians"), ("고후", "고린도후서", "2 Corinthians"),
    ("갈", "갈라디아서", "Galatians"), ("엡", "에베소서", "Ephesians"), ("빌", "빌립보서", "Philippians"),
    ("골", "골로새서", "Colossians"), ("살전", "데살로니가전서", "1 Thessalonians"),
    ("살후", "데살로니가후서", "2 Thessalonians"), ("딤전", "디모데전서", "1 Timothy"),
    ("딤후", "디모데후서", "2 Timothy"), ("딛", "디도서", "Titus"), ("몬", "빌레몬서", "Philemon"),
    ("히", "히브리서", "Hebrews"), ("약", "야고보서", "James"), ("벧전", "베드로전서", "1 Peter"),
    ("벧후", "베드로후서", "2 Peter"), ("요일", "요한일서", "1 John"), ("요이", "요한이서", "2 John"),
    ("요삼", "요한삼서", "3 John"), ("유", "유다서", "Jude"), ("계", "요한계시록", "Revelation"),
]


def _norm(s) -> str:
    return re.sub(r"[\s.\-_]", "", str(s)).lower()


_ALIAS: dict[str, int] = {}
for _i, (_abbr, _name, _en) in enumerate(BOOKS, start=1):
    for _k in (_abbr, _name, _en):
        _ALIAS[_norm(_k)] = _i
_ALIAS.update({
    _norm(k): v for k, v in {
        "아가서": 22, "요한1서": 62, "요한2서": 63, "요한3서": 64, "계시록": 66,
        "Psalm": 19, "Song of Solomon": 22, "Revelations": 66,
    }.items()
})


def resolve_book(book) -> int | None:
    """'요', '요한복음', 'John' 등 → book_no(1~66)"""
    return _ALIAS.get(_norm(book)) if book else None


# ==================== Tool 구현 ====================

def get_bible_verses(book: str, chapter: int, verse_start: int | None = None,
                     verse_end: int | None = None) -> dict:
    book_no = resolve_book(book)
    if book_no is None:
        return {"error": f"알 수 없는 책 이름: {book}. 예: '창세기', '요한복음', '롬'"}
    try:
        chapter = int(chapter)
        vs = int(verse_start) if verse_start not in (None, "") else None
        ve = int(verse_end) if verse_end not in (None, "") else vs
    except (TypeError, ValueError):
        return {"error": "chapter/verse는 정수여야 합니다."}
    if vs is not None and ve is not None and ve < vs:
        vs, ve = ve, vs

    with get_conn() as conn, conn.cursor() as cur:
        if vs is None:
            cur.execute(
                "SELECT verse, text FROM bible_krv WHERE book_no=%s AND chapter=%s "
                "ORDER BY verse LIMIT %s",
                (book_no, chapter, MAX_VERSES + 1),
            )
        else:
            cur.execute(
                "SELECT verse, text FROM bible_krv WHERE book_no=%s AND chapter=%s "
                "AND verse BETWEEN %s AND %s ORDER BY verse LIMIT %s",
                (book_no, chapter, vs, ve, MAX_VERSES + 1),
            )
        rows = cur.fetchall()

    truncated = len(rows) > MAX_VERSES
    rows = rows[:MAX_VERSES]
    name = BOOKS[book_no - 1][1]
    if not rows:
        return {"error": f"{name} {chapter}장{'' if vs is None else f' {vs}절'}은(는) 존재하지 않습니다."}

    first, last = rows[0][0], rows[-1][0]
    ref = f"{name} {chapter}:{first}" + (f"-{last}" if last != first else "")
    return {
        "translation": TRANSLATION,
        "reference": ref,
        "verses": [{"verse": v, "text": t} for v, t in rows],
        "truncated": truncated,
    }


def search_bible(keyword: str, book: str | None = None) -> dict:
    terms = [t.replace("%", "").replace("_", "") for t in str(keyword).split()]
    terms = [t for t in terms if t]
    if not terms:
        return {"error": "검색어가 비어 있습니다."}

    where = " AND ".join(["text LIKE %s"] * len(terms))
    params: list = [f"%{t}%" for t in terms]
    if book:
        book_no = resolve_book(book)
        if book_no is None:
            return {"error": f"알 수 없는 책 이름: {book}"}
        where += " AND book_no = %s"
        params.append(book_no)
    params.append(MAX_SEARCH_RESULTS)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT book_no, chapter, verse, text FROM bible_krv WHERE {where} "
            "ORDER BY book_no, chapter, verse LIMIT %s",
            params,
        )
        rows = cur.fetchall()

    return {
        "translation": TRANSLATION,
        "results": [
            {"reference": f"{BOOKS[b - 1][1]} {c}:{v}", "text": t} for b, c, v, t in rows
        ],
    }


# ==================== Tool 스키마 ====================

BIBLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_bible_verses",
            "description": (
                "개역한글 성경에서 책/장/절로 정확한 본문을 조회한다. "
                "성경 구절을 인용하기 전에 반드시 호출한다. "
                "verse_start를 생략하면 장 전체(최대 30절)를 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book": {"type": "string", "description": "책 이름. 예: '창세기', '요한복음', '롬'"},
                    "chapter": {"type": "integer", "description": "장"},
                    "verse_start": {"type": "integer", "description": "시작 절 (선택)"},
                    "verse_end": {"type": "integer", "description": "끝 절 (선택, 생략 시 시작 절만)"},
                },
                "required": ["book", "chapter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_bible",
            "description": (
                "장절이 확실하지 않을 때 개역한글 본문에서 키워드로 구절을 찾는다. "
                "여러 단어는 공백으로 구분하며 모두 포함된 구절을 반환한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "검색어. 예: '태초 천지'"},
                    "book": {"type": "string", "description": "특정 책으로 제한 (선택)"},
                },
                "required": ["keyword"],
            },
        },
    },
]

_TOOL_FUNCS = {"get_bible_verses": get_bible_verses, "search_bible": search_bible}

BIBLE_TOOL_PROMPT = """

[성경 인용 규칙]
- 성경 구절을 인용할 때는 반드시 get_bible_verses 도구로 개역한글 본문을 조회한 뒤, 조회 결과의 문구를 한 글자도 바꾸지 말고 인용하십시오. 기억에 의존해 본문을 쓰지 마십시오.
- 답변 마무리에 붙이는 한 줄 인용도 예외가 아닙니다. 본문 설명에 쓸 구절과 마무리 구절을 답변 작성 전에 모두 조회하십시오.
- 도구로 조회하지 않은 구절은 본문을 쓰지 말고, 장절만 언급하십시오.
- 장절이 확실하지 않으면 search_bible 도구로 먼저 검색하십시오.
- 도구가 error를 반환하면 그 구절은 인용하지 마십시오.
- 인용 형식: "본문" (요한복음 3:16, 개역한글)
"""


def execute_tool_call(name: str, arguments: str) -> str:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "arguments JSON 파싱 실패"}, ensure_ascii=False)

    allowed = fn.__code__.co_varnames[: fn.__code__.co_argcount]
    args = {k: v for k, v in args.items() if k in allowed}
    try:
        result = fn(**args)
    except TypeError as e:
        result = {"error": f"인자 오류: {e}"}
    except Exception as e:  # DB 오류 등
        result = {"error": f"조회 중 오류: {e}"}

    print(f"📖 [Tool] {name}({args}) → {result.get('reference') or len(result.get('results', [])) or result.get('error')}")
    return json.dumps(result, ensure_ascii=False)


# ==================== Tool-calling 루프 ====================

def _append_tool_results(msgs: list, content: str | None, calls: list[dict]) -> None:
    msgs.append({
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
            for c in calls
        ],
    })
    for c in calls:
        msgs.append({
            "role": "tool",
            "tool_call_id": c["id"],
            "content": execute_tool_call(c["name"], c["arguments"]),
        })


def _tool_choice(round_idx: int) -> str:
    """첫 라운드는 도구 호출 강제, 이후는 모델 자율 판단"""
    return "required" if (FORCE_FIRST_TOOL and round_idx == 0) else "auto"


def chat_with_tools(client, model: str, messages: list[dict], **kwargs) -> str:
    """동기 버전: 최종 답변 문자열 반환"""
    msgs = list(messages)
    if ENABLE_BIBLE_TOOL:
        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                res = client.chat.completions.create(
                    model=model, messages=msgs, tools=BIBLE_TOOLS,
                    tool_choice=_tool_choice(round_idx), **kwargs
                )
            except Exception as e:  # 모델이 tools 미지원 등
                print(f"⚠️ [Tool] tools 호출 실패 → 도구 없이 진행: {e}")
                break
            msg = res.choices[0].message
            if not msg.tool_calls:
                return msg.content or ""
            calls = [
                {"id": tc.id or f"call_{i}", "name": tc.function.name,
                 "arguments": tc.function.arguments}
                for i, tc in enumerate(msg.tool_calls)
            ]
            _append_tool_results(msgs, msg.content, calls)

    res = client.chat.completions.create(model=model, messages=msgs, **kwargs)
    return res.choices[0].message.content or ""


def stream_with_tools(client, model: str, messages: list[dict], **kwargs) -> Iterator[str]:
    """스트리밍 버전: 텍스트 토큰을 yield. tool_call 델타는 내부에서 모아 실행."""
    msgs = list(messages)
    if ENABLE_BIBLE_TOOL:
        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                stream = client.chat.completions.create(
                    model=model, messages=msgs, tools=BIBLE_TOOLS,
                    tool_choice=_tool_choice(round_idx), stream=True, **kwargs
                )
            except Exception as e:
                print(f"⚠️ [Tool] tools 호출 실패 → 도구 없이 진행: {e}")
                break

            slots: dict[int, dict] = {}
            content_parts: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    yield delta.content
                for tc in delta.tool_calls or []:
                    idx = tc.index if tc.index is not None else len(slots)
                    slot = slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

            if not slots:
                return  # 도구 호출 없이 답변 완료
            calls = [
                {**s, "id": s["id"] or f"call_{i}"} for i, s in sorted(slots.items())
            ]
            _append_tool_results(msgs, "".join(content_parts), calls)

    stream = client.chat.completions.create(model=model, messages=msgs, stream=True, **kwargs)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# ==================== 단독 테스트 ====================

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    if args[0] == "--search":
        print(json.dumps(search_bible(" ".join(args[1:])), ensure_ascii=False, indent=2))
    elif args[0] == "--llm":
        from config import LLM_MODEL
        from llm_factory import get_client

        q = " ".join(args[1:]) or "창세기 1장 1절 말씀 알려줘"
        msgs = [
            {"role": "system", "content": "당신은 성경 도우미입니다." + BIBLE_TOOL_PROMPT},
            {"role": "user", "content": q},
        ]
        for tok in stream_with_tools(get_client(), LLM_MODEL, msgs, temperature=0):
            print(tok, end="", flush=True)
        print()
    else:
        book, chapter, *verses = args
        vs = verses[0] if len(verses) > 0 else None
        ve = verses[1] if len(verses) > 1 else None
        print(json.dumps(get_bible_verses(book, chapter, vs, ve), ensure_ascii=False, indent=2))