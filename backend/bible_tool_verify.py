"""
bible_tool_verify.py — 성경 구절 검증의 'tool 방식' (LLM 툴콜링)

bible_verify.py의 VerseStreamFilter가 답변에서 구절을 검출하면(코드), 붙잡아 둔 부분을
LLM에게 넘기고, LLM이 get_bible_verses 도구로 구절을 조회해 확인·수정한다.

    답변 생성 (도구 없음, 스트리밍)
      └ 구절 검출 (코드, 정규식)          ← 구절이 없으면 여기서 끝, 추가 LLM 호출 없음
          └ LLM 검증 (툴콜링)             ← 구절이 있을 때만
              └ get_bible_verses 조회    ← DB(bible_krv) 원문 (접속 실패 시 bible.txt)

사용 (bbot_graph.py):
    verifier = make_llm_verifier(client, LLM_MODEL, name="verse-verify-tool")
    vf = VerseStreamFilter(mode="tool", llm=verifier)

LLM이 실패하거나 결과가 이상하면 원래 부분을 그대로 돌려주고, VerseStreamFilter가
code 방식으로 대신 검증한다.
"""
import json
import re

from bible_verify import (
    BOOKS, MAX_TEXT_VERSES, TRANSLATION, _ABBR_TO_NO, _NAME_TO_NO,
    _SUPERSCRIPTION_RE, chapter_exists, get_verse, verse_count,
)
from logging_config import get_logger

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 4          # 도구 호출 왕복 최대 횟수
MAX_VERSES_PER_CALL = 30     # 한 번에 돌려줄 최대 절 수 (토큰 폭주 방지)
EMPTY_MARK = "<EMPTY>"       # 검증 결과 전부 지워져야 할 때 LLM이 쓰는 표시

# ==================== 도구 ====================

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_bible_verses",
        "description": (
            f"{TRANSLATION} 성경에서 구절을 조회한다. 구절이 존재하지 않으면 error를 돌려준다. "
            "절을 생략하면 장이 존재하는지와 절 수만 돌려준다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "book": {"type": "string", "description": "책 이름. 예: 창세기, 요한복음"},
                "chapter": {"type": "integer", "description": "장 (시편은 편)"},
                "verse_start": {"type": "integer", "description": "시작 절 (생략하면 장만 확인)"},
                "verse_end": {"type": "integer", "description": "끝 절 (생략하면 시작 절 하나)"},
            },
            "required": ["book", "chapter"],
        },
    },
}]


def _resolve_book(book) -> int | None:
    b = re.sub(r"\s", "", str(book or ""))
    return _NAME_TO_NO.get(b) or _ABBR_TO_NO.get(b)


def get_bible_verses(book, chapter, verse_start=None, verse_end=None) -> dict:
    book_no = _resolve_book(book)
    if book_no is None:
        return {"error": f"알 수 없는 책 이름: {book}"}
    try:
        chapter = int(chapter)
        vs = int(verse_start) if verse_start not in (None, "") else None
        ve = int(verse_end) if verse_end not in (None, "") else vs
    except (TypeError, ValueError):
        return {"error": "chapter/verse는 정수여야 합니다."}
    name = BOOKS[book_no - 1][1]
    unit = "편" if book_no == 19 else "장"

    if not chapter_exists(book_no, chapter):
        return {"error": f"{name} {chapter}{unit}은(는) 존재하지 않습니다."}
    count = verse_count(book_no, chapter)
    if vs is None:
        return {"reference": f"{name} {chapter}{unit}", "exists": True, "verse_count": count}

    if ve < vs:
        vs, ve = ve, vs
    if vs < 1 or ve > count:
        return {"error": f"{name} {chapter}:{vs}" + (f"-{ve}" if ve != vs else "")
                + f"은(는) 존재하지 않습니다. ({name} {chapter}{unit}은 {count}절까지 있습니다)"}
    end = min(ve, vs + MAX_VERSES_PER_CALL - 1)
    verses = [
        {"verse": v, "text": _SUPERSCRIPTION_RE.sub("", get_verse(book_no, chapter, v))}
        for v in range(vs, end + 1)
    ]
    result = {
        "reference": f"{name} {chapter}:{vs}" + (f"-{ve}" if ve != vs else ""),
        "translation": TRANSLATION,
        "verses": verses,
    }
    if end < ve:
        result["truncated"] = True
    return result


_TOOL_FUNCS = {"get_bible_verses": get_bible_verses}


def execute_tool_call(name: str, arguments: str) -> dict:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"알 수 없는 도구: {name}"}
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments JSON 파싱 실패"}
    allowed = {"book", "chapter", "verse_start", "verse_end"}
    try:
        return fn(**{k: v for k, v in args.items() if k in allowed})
    except TypeError as e:
        return {"error": f"인자 오류: {e}"}


# ==================== LLM 검증 ====================

VERIFY_SYSTEM_PROMPT = f"""당신은 성경 인용 검증기입니다.
[검증할 부분]에 나오는 모든 성경 구절을 get_bible_verses 도구로 조회해 확인하고, 아래 규칙대로 고친 [검증할 부분]만 출력하십시오.

[규칙]
1. 존재하지 않는 구절(도구가 error를 돌려준 구절)
   - "본문" (출처) 형태이면 본문과 출처를 통째로 지우십시오.
   - (출처)만 있으면 괄호째 지우십시오.
   - 문장 속 언급(예: "창세기 51장 3절에서 말하듯")이면 그 장절 표기만 '성경'으로 바꾸십시오.
2. {MAX_TEXT_VERSES}절 이하 구절의 인용 본문이 조회 결과와 다르면 조회 결과 원문으로 바꾸십시오.
   띄어쓰기·문장부호 차이는 무시하고, 원문의 일부만 정확히 인용한 경우는 그대로 두십시오.
3. {MAX_TEXT_VERSES + 1}절 이상 범위의 인용 본문이 원문과 다르면 본문은 빼고 출처만 남기십시오.
4. 장만 언급한 경우는 장이 존재하는지만 확인하십시오.
5. 본문 없이 장절만 언급한 구절은 존재하면 그대로 두십시오.
6. 성경 구절이 아닌 부분은 한 글자도 바꾸지 마십시오. 줄바꿈과 마크다운도 그대로 두십시오.

[출력]
- 고친 [검증할 부분]만 출력하십시오. 설명, 머리말, 따옴표로 감싸기, 코드 블록을 쓰지 마십시오.
- [앞부분]은 맥락 참고용이므로 출력하지 마십시오.
- 모두 지워져 남는 내용이 없으면 {EMPTY_MARK} 만 출력하십시오."""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")
_LABEL_RE = re.compile(r"^\s*\[검증할 부분\]\s*\n?")


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", text or "").strip()
    text = _FENCE_RE.sub("", text).strip()
    return _LABEL_RE.sub("", text)


def _create(client, tool_choice, **kwargs):
    try:
        return client.chat.completions.create(tools=TOOLS, tool_choice=tool_choice, **kwargs)
    except Exception as e:
        if tool_choice != "required":
            raise
        # 일부 모델/프로바이더는 tool_choice="required"를 지원하지 않는다
        logger.info("[VerseTool] tool_choice=required 미지원 → auto로 재시도: %s", e)
        return client.chat.completions.create(tools=TOOLS, tool_choice="auto", **kwargs)


def llm_verify(client, model: str, context: str, segment: str, **llm_kwargs) -> tuple[str | None, list[dict]]:
    """segment 속 성경 구절을 LLM이 도구로 조회·검증한다.

    반환: (고친 segment, 도구 호출 내역). 결과를 믿을 수 없으면 (None, 내역).
    """
    messages = [
        {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
        {"role": "user", "content": f"[앞부분]\n{context[-1500:]}\n\n[검증할 부분]\n{segment}"},
    ]
    log: list[dict] = []
    text = None
    for round_idx in range(MAX_TOOL_ROUNDS):
        res = _create(
            client, "required" if round_idx == 0 else "auto",
            model=model, messages=messages, temperature=0, **llm_kwargs,
        )
        msg = res.choices[0].message
        if not msg.tool_calls:
            text = msg.content or ""
            break
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id or f"call_{round_idx}_{i}", "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for i, tc in enumerate(msg.tool_calls)
            ],
        })
        for i, tc in enumerate(msg.tool_calls):
            result = execute_tool_call(tc.function.name, tc.function.arguments)
            log.append({
                "args": tc.function.arguments,
                "result": result.get("reference") or result.get("error"),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id or f"call_{round_idx}_{i}",
                "content": json.dumps(result, ensure_ascii=False),
            })
    if text is None:
        # 왕복 한도를 다 쓰면 도구 없이 한 번 더 불러 결과를 받는다
        res = client.chat.completions.create(model=model, messages=messages, temperature=0, **llm_kwargs)
        text = res.choices[0].message.content or ""

    text = _clean(text)
    logger.info("[VerseTool] 도구 호출 %d회: %s", len(log), [c["result"] for c in log])

    if text.strip() == EMPTY_MARK:
        return "", log
    if not text.strip():
        logger.warning("[VerseTool] LLM 결과가 비어 있음 → 원문 유지")
        return None, log
    if len(text) > 3 * len(segment) + 300:
        logger.warning("[VerseTool] LLM 결과가 비정상적으로 김 (%d → %d) → 원문 유지", len(segment), len(text))
        return None, log

    # LLM이 앞뒤 공백·줄바꿈을 지우는 경우가 많아 원래 것을 되살린다
    lead = segment[: len(segment) - len(segment.lstrip())]
    trail = segment[len(segment.rstrip()):]
    return lead + text.strip() + trail, log


def make_llm_verifier(client, model: str, **llm_kwargs):
    """VerseStreamFilter(llm=...)에 넘길 검증 함수를 만든다."""
    def verifier(context: str, segment: str):
        return llm_verify(client, model, context, segment, **llm_kwargs)
    return verifier
