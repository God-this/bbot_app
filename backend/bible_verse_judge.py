"""
bible_verse_judge.py — 성경 인용의 맥락·주소 판정 (LLM 툴콜링, 3단계)

    1. 구절 검출 (코드)              bible_verify.find_citations
    2. 존재·본문 확인 (코드, 표시만)  bible_verify.find_citations
    3. 맥락·주소 판정 (LLM + 툴)     ← 이 파일. 구절별 판정만 JSON으로 받는다
    4. 수정 (코드)                   bible_verify.apply_verdicts → code 검증

LLM은 답변 텍스트를 다시 쓰지 않는다. (지난 실험에서 텍스트를 통째로 다시 쓰게 했더니
출처를 지우고 문단까지 삭제했다 — experiments/구절검증_방식비교_20261021.md)

판정 값
  ok               주소·인용·맥락 모두 맞음
  wrong_ref        인용문(내용)이 다른 구절의 것 → suggested_ref (코드가 확인 후에만 반영)
  quote_wrong      주소는 맞고 인용문이 원문과 다르게 쓰임 → code 방식대로 원문 교체
  context_mismatch 구절은 정확하지만 문맥의 주장을 뒷받침하지 않음 → 기본은 기록만
  not_found        존재하지 않는 구절 (코드가 처리)

도구
  get_bible_verses : 장절로 원문 조회 (bible_tool_verify와 같은 함수)
  search_bible     : 키워드로 구절 찾기 (맞는 주소를 찾을 때)

사용 모드 (VERSE_JUDGE_MODE)
  off    : 판정하지 않음
  shadow : (기본) 답변은 code 방식으로 바로 내보내고, 전송이 끝난 뒤 판정해 로그만 남긴다
           (사용자 응답 속도 영향 없음. 판정이 맞는지 판단이 서기 전까지는 기록만 한다)
  apply  : 판정 결과를 답변에 반영한다. 첫 절 단위 구절부터 답변 끝까지 붙잡는다.
"""
import json
import os
import re

from bible_verify import (
    BIBLE_SOURCE, BOOKS, TRANSLATION, _file_chapters, _load_file,
    _SUPERSCRIPTION_RE, apply_verdicts, find_citations, verify_answer,
)
from bible_tool_verify import get_bible_verses
from logging_config import get_logger

logger = get_logger(__name__)

VERSE_JUDGE_MODE = os.getenv("VERSE_JUDGE_MODE", "shadow").lower()   # off / shadow(기본) / apply
MAX_JUDGE_ROUNDS = 4
MAX_SEARCH_RESULTS = 10
VERDICTS = {"ok", "wrong_ref", "quote_wrong", "context_mismatch", "not_found"}


# ==================== 도구 ====================

def search_bible(keyword: str, book: str | None = None) -> dict:
    """키워드(공백으로 나누면 AND)가 모두 들어간 구절을 찾는다."""
    words = [w for w in re.sub(r"[%_]", "", str(keyword or "")).split() if w]
    if not words:
        return {"error": "키워드가 비어 있습니다."}
    book_no = None
    if book:
        b = re.sub(r"\s", "", str(book))
        book_no = next((i for i, (abbr, name) in enumerate(BOOKS, start=1) if b in (abbr, name)), None)
        if book_no is None:
            return {"error": f"알 수 없는 책 이름: {book}"}

    rows = None
    if BIBLE_SOURCE == "db":
        try:
            from config import get_conn
            sql = "SELECT book_no, chapter, verse, text FROM bible_krv WHERE " + " AND ".join(
                ["text LIKE %s"] * len(words))
            params = [f"%{w}%" for w in words]
            if book_no:
                sql += " AND book_no = %s"
                params.append(book_no)
            sql += " ORDER BY book_no, chapter, verse LIMIT %s"
            params.append(MAX_SEARCH_RESULTS)
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        except Exception as e:
            logger.warning("[VerseJudge] search_bible DB 실패 → bible.txt 사용: %s", e)
    if rows is None:
        _load_file()
        rows = []
        for (b, ch), verses in sorted(_file_chapters.items()):
            if book_no and b != book_no:
                continue
            for v, t in sorted(verses.items()):
                if all(w in t for w in words):
                    rows.append((b, ch, v, t))
                    if len(rows) >= MAX_SEARCH_RESULTS:
                        break
            if len(rows) >= MAX_SEARCH_RESULTS:
                break
    return {
        "translation": TRANSLATION,
        "results": [
            {"reference": f"{BOOKS[b - 1][1]} {ch}:{v}", "text": _SUPERSCRIPTION_RE.sub("", t)}
            for b, ch, v, t in rows
        ],
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_bible_verses",
            "description": f"{TRANSLATION} 성경에서 장절로 구절을 조회한다. 없는 구절이면 error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book": {"type": "string", "description": "책 이름. 예: 창세기"},
                    "chapter": {"type": "integer"},
                    "verse_start": {"type": "integer"},
                    "verse_end": {"type": "integer"},
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
                f"{TRANSLATION} 성경에서 키워드가 모두 들어간 구절을 찾는다 (최대 {MAX_SEARCH_RESULTS}건). "
                "인용문이 실제로 어느 구절의 것인지 찾을 때 쓴다. 키워드는 원문에 나올 법한 짧은 단어 1~3개."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "공백으로 나누면 AND. 예: '보시기에 좋았더라'"},
                    "book": {"type": "string", "description": "책 이름으로 범위 제한 (선택)"},
                },
                "required": ["keyword"],
            },
        },
    },
]
_TOOL_FUNCS = {"get_bible_verses": get_bible_verses, "search_bible": search_bible}


def _execute(name: str, arguments: str) -> dict:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"알 수 없는 도구: {name}"}
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"error": "arguments JSON 파싱 실패"}
    allowed = fn.__code__.co_varnames[: fn.__code__.co_argcount]
    try:
        return fn(**{k: v for k, v in args.items() if k in allowed})
    except TypeError as e:
        return {"error": f"인자 오류: {e}"}


# ==================== 판정 ====================

JUDGE_SYSTEM_PROMPT = f"""당신은 성경 인용 판정기입니다.
답변에 나온 성경 인용 목록을 보고, 각 인용이 (1) 올바른 주소인지, (2) 답변 문맥의 주장을 뒷받침하는지 판정합니다.
답변 텍스트를 고쳐 쓰지 말고, 판정만 JSON으로 출력하십시오.

각 인용에는 코드가 {TRANSLATION} 원문을 미리 조회한 결과(존재 여부, 원문, 본문 일치 여부)가 붙어 있습니다. 이 정보는 정확합니다.

[판정 값]
- ok: 주소와 인용이 맞고, 문맥의 주장도 뒷받침함
- wrong_ref: 인용문(또는 언급한 내용)이 적힌 주소가 아니라 다른 구절의 것임. suggested_ref에 맞는 주소를 쓰십시오.
  맞는 주소는 search_bible로 찾고 get_bible_verses로 원문을 확인한 뒤에만 쓰십시오. 확인하지 못했으면 quote_wrong으로 판정하십시오.
- quote_wrong: 주소는 맞는데 인용문이 원문과 다르게 쓰임
- context_mismatch: 구절 자체는 정확하지만, 그 구절의 내용이 문맥의 주장을 뒷받침하지 않음
- not_found: 존재하지 않는 구절 (존재 여부가 '아니오'인 경우)

[주의]
- 본문 일치가 '아니오'라고 해서 무조건 wrong_ref가 아닙니다. 인용문이 적힌 주소의 원문을 줄이거나 풀어 쓴 것이면 quote_wrong입니다.
- 장만 언급한 인용은 맥락만 보십시오.
- reason은 한국어 한 문장으로 쓰십시오.

[출력 형식] JSON만 출력하십시오.
{{"verdicts": [{{"id": 1, "verdict": "ok", "suggested_ref": null, "reason": "..."}}]}}"""

_KIND_KO = {"quoted": "따옴표 인용", "paren": "괄호 출처", "inline": "문장 속 언급"}


def _citation_block(c) -> str:
    yn = lambda b: "해당 없음" if b is None else ("예" if b else "아니오")
    lines = [
        f"[인용 {c.id}]",
        f"- 형태: {_KIND_KO.get(c.kind, c.kind)}",
        f"- 주소: {c.ref.label}",
        f"- 인용문: {c.quote if c.quote else '없음'}",
        f"- 존재: {yn(c.exists)}",
    ]
    if c.original:
        lines.append(f"- 원문({TRANSLATION}): {c.original}")
    lines += [f"- 본문 일치: {yn(c.quote_match)}", f"- 문맥: {c.context}"]
    return "\n".join(lines)


def _parse_verdicts(content: str, citations) -> list[dict]:
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not m:
        raise ValueError("판정 JSON을 찾지 못함")
    data = json.loads(m.group(0))
    items = data.get("verdicts", []) if isinstance(data, dict) else data
    ids = {c.id for c in citations}
    out = []
    for v in items:
        if not isinstance(v, dict) or v.get("id") not in ids:
            continue
        verdict = str(v.get("verdict", "")).strip()
        if verdict not in VERDICTS:
            continue
        out.append({
            "id": v["id"], "verdict": verdict,
            "suggested_ref": v.get("suggested_ref") or None,
            "reason": str(v.get("reason", ""))[:300],
        })
    return out


def judge_citations(client, model: str, text: str, citations, **llm_kwargs) -> tuple[list[dict], list[dict]]:
    """구절별 판정. 반환: (판정 목록, 도구 호출 내역)"""
    if not citations:
        return [], []
    user = (
        f"[답변]\n{text[-3000:]}\n\n"
        + "\n\n".join(_citation_block(c) for c in citations)
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    log: list[dict] = []
    content = None
    for round_idx in range(MAX_JUDGE_ROUNDS):
        res = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS, tool_choice="auto",
            temperature=0, **llm_kwargs,
        )
        msg = res.choices[0].message
        if not msg.tool_calls:
            content = msg.content or ""
            break
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id or f"call_{round_idx}_{i}", "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for i, tc in enumerate(msg.tool_calls)
            ],
        })
        for i, tc in enumerate(msg.tool_calls):
            result = _execute(tc.function.name, tc.function.arguments)
            log.append({
                "tool": tc.function.name, "args": tc.function.arguments,
                "result": result.get("reference") or result.get("error")
                          or f"{len(result.get('results', []))}건",
            })
            messages.append({
                "role": "tool", "tool_call_id": tc.id or f"call_{round_idx}_{i}",
                "content": json.dumps(result, ensure_ascii=False),
            })
    if content is None:
        res = client.chat.completions.create(model=model, messages=messages, temperature=0, **llm_kwargs)
        content = res.choices[0].message.content or ""
    verdicts = _parse_verdicts(content, citations)
    logger.info("[VerseJudge] 판정 %d건, 도구 호출 %d회", len(verdicts), len(log))
    return verdicts, log


def make_judge(client, model: str, **llm_kwargs):
    """VerseStreamFilter(judge=...)와 run_shadow에 넘길 판정 함수"""
    def judge(text: str, citations):
        return judge_citations(client, model, text, citations, **llm_kwargs)
    return judge


def run_shadow(raw_answer: str, judge, served_answer: str | None = None) -> dict:
    """shadow 모드: 원래 답변을 판정하고 '반영했다면 어떻게 바뀌었을지'를 기록만 한다.

    served_answer: 실제로 사용자에게 나간 답변 (code 방식 결과). 없으면 여기서 계산한다.
    """
    cits = find_citations(raw_answer)
    if not cits:
        return {"status": "no_citations"}
    try:
        verdicts, tool_log = judge(text=raw_answer, citations=cits)
    except Exception as e:
        logger.warning("[VerseJudge:shadow] 판정 실패: %s", e)
        return {"status": "error", "error": str(e)}
    applied, applied_log = apply_verdicts(raw_answer, cits, verdicts)
    would_be, _ = verify_answer(applied)
    served = served_answer if served_answer is not None else verify_answer(raw_answer)[0]
    by_id = {e["id"]: e for e in applied_log}
    result = {
        "status": "ok",
        "citations": [{**c.to_dict(), **by_id.get(c.id, {})} for c in cits],
        "tool_calls": tool_log,
        "would_change": would_be != served,
        "counts": {k: sum(1 for e in applied_log if e["verdict"] == k) for k in sorted(VERDICTS)},
    }
    if result["would_change"]:
        result["would_be_answer"] = would_be
    logger.info("[VerseJudge:shadow] %s · 반영 시 답변 변경=%s",
                ", ".join(f"{e['ref']}={e['verdict']}" for e in applied_log), result["would_change"])
    return result
