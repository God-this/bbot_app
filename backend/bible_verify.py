"""
bible_verify.py — 생성된 답변 속 성경 구절을 개역한글 원문과 대조해 검증한다.

흐름 (프로젝트 문서 design/답변생성후_구절검색.md, 교수님 피드백 반영)
  1. 답변은 도구 없이 생성·스트리밍한다.
  2. 답변에 성경 구절이 있는지 정규식으로 확인한다. 없으면 아무것도 하지 않는다.
  3. 구절 주소로 원문을 조회한다. 운영 DB의 bible_krv(개역한글)에서 장 단위로 가져와
     캐시한다. DB에 접속할 수 없으면 bible.txt로 대신한다. LLM 호출은 없다.
  4. 검증
     - 장만 언급        (창세기 5장)        : 장이 존재하는지만 확인
     - 3절 이하         (창세기 1:1, 1:1-3) : 존재 확인 + 인용 본문이 원문과 다르면 원문으로 교체
     - 4절 이상         (창세기 1:1-10)     : 존재 확인만. 인용 본문이 원문과 다르면 본문은 빼고 주소만 남김
     - 존재하지 않는 구절                    : 제거. 문장 속 언급은 '성경'으로 바꿔 문장이 깨지지 않게 함
     - 본문 없이 주소만 쓴 경우              : 답변 안에서는 그대로 둔다
  5. 답변 끝 '참고 구절' — 본문 없이 주소만 언급된 3절 이하 구절의 원문을 붙인다.

스트리밍 중에는 VerseStreamFilter가 구절 인용이 시작될 만한 지점(따옴표, 여는 괄호,
책 이름)에서 출력을 잠시 붙잡았다가, 인용이 끝나면 검증한 결과를 내보낸다.
구절이 아닌 것으로 판명되면 붙잡았던 글자를 그대로 내보낸다.

설정 (.env)
  VERSE_VERIFY_MODE       code(기본) / off — 위 검증을 할지
  APPEND_REFERENCE_VERSES true(기본) / false — 답변 끝 참고 구절
  BIBLE_SOURCE            db(기본) / file — 원문을 DB에서 볼지 bible.txt에서 볼지
  VERSE_JUDGE_MODE        shadow(기본) / apply / off — 맥락·주소 판정 (bible_verse_judge.py)
  VERSE_CONTEXT_ACTION    log(기본) / remove — apply일 때 맥락이 안 맞는 인용 처리

  (LLM이 답변 텍스트를 다시 쓰게 하던 tool 방식은 2026-10-21 비교 실험에서 출처·문단을
   지우는 문제가 확인되어 제거했다 — experiments/구절검증_방식비교_20261021.md)

맥락·주소 판정 (VERSE_JUDGE_MODE, bible_verse_judge.py) — code 방식 위에 얹는다
  1. 구절 검출 (코드)  2. 존재·본문 확인 (코드, 표시만)  3. 맥락·주소 판정 (LLM + 툴, 판정만 JSON)
  4. 수정 (코드: apply_verdicts → code 검증)
  LLM은 텍스트를 다시 쓰지 않고 구절별 판정만 돌려준다. 실제 수정은 이 파일의 코드가 한다.

나중에 할 일
  - 없는 구절 대신 올바른 구절 찾아 넣기
  - 맥락 판정 결과를 답변에 반영할지 결정 (지금은 shadow로 기록만)

단독 실행:
    python bible_verify.py '"태초에 하나님이 천지를 창조하시니라" (창세기 1:1, 개역한글)'
"""
import os
import re
import threading
import difflib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from logging_config import get_logger

logger = get_logger(__name__)

VERSE_VERIFY_MODE = os.getenv("VERSE_VERIFY_MODE", "code").lower()     # code / off
APPEND_REFERENCE_VERSES = os.getenv("APPEND_REFERENCE_VERSES", "true").lower() == "true"

MAX_TEXT_VERSES = 3      # 본문까지 다루는 최대 절 수 (이보다 길면 주소만 확인)
MAX_APPENDIX = 3         # '참고 구절'에 붙일 최대 구절 수
TRANSLATION = "개역한글"
APPENDIX_HEADER = f"**참고 구절 ({TRANSLATION})**"
BIBLE_FILE = Path(__file__).parent / "bible.txt"

# 문장 속 없는 구절 언급을 대신할 말 ("창세기 51장에서 말하듯" → "성경에서 말하듯")
MISSING_INLINE_REPLACEMENT = "성경"

# (bible.txt 약어, 정식 이름) — 인덱스+1 = book_no
BOOKS = [
    ("창", "창세기"), ("출", "출애굽기"), ("레", "레위기"), ("민", "민수기"), ("신", "신명기"),
    ("수", "여호수아"), ("삿", "사사기"), ("룻", "룻기"), ("삼상", "사무엘상"), ("삼하", "사무엘하"),
    ("왕상", "열왕기상"), ("왕하", "열왕기하"), ("대상", "역대상"), ("대하", "역대하"), ("스", "에스라"),
    ("느", "느헤미야"), ("에", "에스더"), ("욥", "욥기"), ("시", "시편"), ("잠", "잠언"),
    ("전", "전도서"), ("아", "아가"), ("사", "이사야"), ("렘", "예레미야"), ("애", "예레미야애가"),
    ("겔", "에스겔"), ("단", "다니엘"), ("호", "호세아"), ("욜", "요엘"), ("암", "아모스"),
    ("옵", "오바댜"), ("욘", "요나"), ("미", "미가"), ("나", "나훔"), ("합", "하박국"),
    ("습", "스바냐"), ("학", "학개"), ("슥", "스가랴"), ("말", "말라기"),
    ("마", "마태복음"), ("막", "마가복음"), ("눅", "누가복음"), ("요", "요한복음"), ("행", "사도행전"),
    ("롬", "로마서"), ("고전", "고린도전서"), ("고후", "고린도후서"), ("갈", "갈라디아서"),
    ("엡", "에베소서"), ("빌", "빌립보서"), ("골", "골로새서"), ("살전", "데살로니가전서"),
    ("살후", "데살로니가후서"), ("딤전", "디모데전서"), ("딤후", "디모데후서"), ("딛", "디도서"),
    ("몬", "빌레몬서"), ("히", "히브리서"), ("약", "야고보서"), ("벧전", "베드로전서"),
    ("벧후", "베드로후서"), ("요일", "요한일서"), ("요이", "요한이서"), ("요삼", "요한삼서"),
    ("유", "유다서"), ("계", "요한계시록"),
]
_ABBR_TO_NO = {abbr: i for i, (abbr, _) in enumerate(BOOKS, start=1)}
_NAME_TO_NO = {name: i for i, (_, name) in enumerate(BOOKS, start=1)}
# 모델이 섞어 쓰는 별칭. 약어(창/요/시 등)는 '약 3:1'(대략) 같은 일반 문장과
# 헷갈리므로 받지 않는다 — 프롬프트가 정식 명칭을 쓰도록 요구한다.
_NAME_TO_NO.update({"아가서": 22, "요한1서": 62, "요한2서": 63, "요한3서": 64, "계시록": 66})

# ==================== 원문 조회 ====================
# 원문은 운영 DB의 bible_krv 테이블(개역한글, PK (book_no, chapter, verse))에서 가져온다.
# 장 단위로 한 번에 조회해 메모리에 캐시하므로, 같은 장의 구절은 DB를 다시 부르지 않는다.
# DB에 접속할 수 없으면 bible.txt로 대신한다 (두 데이터는 31,101절 모두 동일함을 확인).
#   BIBLE_SOURCE=db (기본) / file (bible.txt만 사용 — DB 없이 테스트할 때)

BIBLE_SOURCE = os.getenv("BIBLE_SOURCE", "db").lower()
CHAPTER_CACHE_SIZE = 512     # 캐시할 장 수 (성경 전체 1,189장)

_file_chapters: dict[tuple[int, int], dict[int, str]] = {}
_load_lock = threading.Lock()
_LINE_RE = re.compile(r"^(\D+?)(\d+):(\d+)\s+(.*)$")


def _load_file() -> None:
    """bible.txt를 {(책 번호, 장): {절: 본문}} 형태로 메모리에 올린다 (DB 대체용)."""
    if _file_chapters:
        return
    with _load_lock:
        if _file_chapters:
            return
        count = 0
        with open(BIBLE_FILE, encoding="utf-8") as f:
            for line in f:
                m = _LINE_RE.match(line.strip())
                if not m:
                    continue
                book_no = _ABBR_TO_NO.get(m.group(1))
                if book_no is None:
                    continue
                ch, v = int(m.group(2)), int(m.group(3))
                _file_chapters.setdefault((book_no, ch), {})[v] = m.group(4).strip()
                count += 1
        logger.info("성경 원문 로드 (bible.txt): %d절", count)


def _fetch_chapter_db(book_no: int, chapter: int) -> dict[int, str]:
    from config import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT verse, text FROM bible_krv WHERE book_no=%s AND chapter=%s ORDER BY verse",
            (book_no, chapter),
        )
        return {int(v): t for v, t in cur.fetchall()}


@lru_cache(maxsize=CHAPTER_CACHE_SIZE)
def _chapter(book_no: int, chapter: int) -> dict[int, str]:
    """한 장의 {절: 본문}. 없는 장이면 빈 dict. (돌려받은 dict는 수정하지 말 것)"""
    if BIBLE_SOURCE == "db":
        try:
            return _fetch_chapter_db(book_no, chapter)
        except Exception as e:
            logger.warning("[Bible] DB 조회 실패 → bible.txt 사용: %s", e)
    _load_file()
    return _file_chapters.get((book_no, chapter), {})


def get_verse(book_no: int, chapter: int, verse: int) -> str | None:
    return _chapter(book_no, chapter).get(verse)


def chapter_exists(book_no: int, chapter: int) -> bool:
    return bool(_chapter(book_no, chapter))


def verse_count(book_no: int, chapter: int) -> int:
    verses = _chapter(book_no, chapter)
    return max(verses) if verses else 0


# ==================== 구절 표기 인식 ====================

_BOOK_NAMES = sorted(_NAME_TO_NO, key=len, reverse=True)   # '예레미야애가'가 '예레미야'보다 먼저
_BOOK_ALT = "|".join(_BOOK_NAMES)
_DASH = r"[-~–—]"

# 지원 표기: 요한복음 3:16 / 창세기 1:1-3 / 창세기 1:31-2:3 / 창세기 5장 / 창세기 1장 6절 / 창세기 1장 6-8절 / 시편 23편 1절
#           / 창세기 9장 12절에서 17절(까지)
REF_RE = re.compile(
    rf"(?P<book>{_BOOK_ALT})\s*(?P<ch>\d{{1,3}})\s*"
    r"(?:"
    rf"[:：]\s*(?P<v1>\d{{1,3}})(?:\s*{_DASH}\s*(?:(?P<ch2>\d{{1,3}})\s*[:：]\s*)?(?P<v2>\d{{1,3}}))?"
    r"|"
    rf"[장편](?:\s*(?P<kv1>\d{{1,3}})\s*절?(?:\s*(?:{_DASH}|에서)\s*(?P<kv2>\d{{1,3}}))?\s*절)?"
    r")"
)
# 구절 표기가 아직 이어질 수 있는 글자 (이것만 뒤에 왔으면 더 기다린다)
# "9장 12절에서 17절까지"처럼 '에서'로 범위를 잇는 경우도 기다린다
_CONTINUATION_RE = re.compile(rf"[\s\d:：장편절]*(?:(?:{_DASH}|에서?)[\s\d:：장편절]*)?")
# 책 이름이 막 쓰이는 중일 수 있는 접두어 ('요한' → 요한복음/요한일서…)
_BOOK_PREFIXES = {name[:k] for name in _NAME_TO_NO for k in range(1, len(name) + 1)}
_BOOK_FIRST_CHARS = {name[0] for name in _NAME_TO_NO}
_PARTIAL_REF_RE = re.compile(rf"(?:{_BOOK_ALT})\s*(?:\d{{1,3}}\s*(?:[:：장편]\s*(?:\d{{1,3}}\s*{_DASH}?\s*)?)?)?")

_OPEN_QUOTES = {'"': '"', "“": "”\"", "「": "」", "『": "』", "‘": "’'"}
_HANGUL_RE = re.compile(r"[가-힣]")

MAX_QUOTE_HOLD = 600     # 따옴표가 이만큼 안 닫히면 구절 인용이 아니라고 보고 내보낸다
MAX_PAREN_HOLD = 60      # 괄호도 마찬가지


@dataclass
class Ref:
    book_no: int
    chapter: int
    v1: int | None = None      # None이면 장만 언급
    v2: int | None = None
    chapter2: int | None = None

    @property
    def name(self) -> str:
        return BOOKS[self.book_no - 1][1]

    @property
    def label(self) -> str:
        if self.v1 is None:
            return f"{self.name} {self.chapter}{'편' if self.book_no == 19 else '장'}"
        s = f"{self.name} {self.chapter}:{self.v1}"
        if self.chapter2 not in (None, self.chapter):
            return s + f"-{self.chapter2}:{self.v2}"
        return s + (f"-{self.v2}" if self.v2 != self.v1 else "")

    @property
    def key(self) -> tuple:
        return (self.book_no, self.chapter, self.v1, self.v2, self.chapter2)

    @property
    def is_short(self) -> bool:
        """본문까지 다루는 범위인지 (같은 장 안의 3절 이하)"""
        return (
            self.v1 is not None
            and self.chapter2 in (None, self.chapter)
            and self.v2 - self.v1 + 1 <= MAX_TEXT_VERSES
        )


def parse_ref(m: re.Match) -> Ref:
    book_no = _NAME_TO_NO[m.group("book")]
    ch = int(m.group("ch"))
    if m.group("v1"):
        v1 = int(m.group("v1"))
        v2 = int(m.group("v2")) if m.group("v2") else v1
        ch2 = int(m.group("ch2")) if m.group("ch2") else ch
        return Ref(book_no, ch, v1, v2, ch2)
    if m.group("kv1"):
        v1 = int(m.group("kv1"))
        v2 = int(m.group("kv2")) if m.group("kv2") else v1
        return Ref(book_no, ch, v1, v2, ch)
    return Ref(book_no, ch)


def ref_exists(ref: Ref) -> bool:
    if ref.v1 is None:
        return chapter_exists(ref.book_no, ref.chapter)
    ch2 = ref.chapter2 or ref.chapter
    if (ch2, ref.v2) < (ref.chapter, ref.v1):
        return False
    return (
        get_verse(ref.book_no, ref.chapter, ref.v1) is not None
        and get_verse(ref.book_no, ch2, ref.v2) is not None
    )


# 시편 표제 등 원문 앞의 {다윗의 시} 같은 머리글 — 보여줄 때는 뺀다
_SUPERSCRIPTION_RE = re.compile(r"^\{[^}]*\}\s*")


def ref_text(ref: Ref) -> str:
    """같은 장 안의 구절 범위 원문 (is_short인 경우에만 호출)"""
    return " ".join(
        _SUPERSCRIPTION_RE.sub("", get_verse(ref.book_no, ref.chapter, v) or "")
        for v in range(ref.v1, ref.v2 + 1)
    ).strip()


def ref_range_text(ref: Ref) -> str:
    """범위 전체 원문 (긴 범위의 인용 본문 대조용)"""
    if ref.v1 is None:
        return ""
    ch2 = ref.chapter2 or ref.chapter
    parts = []
    for ch in range(ref.chapter, ch2 + 1):
        v = ref.v1 if ch == ref.chapter else 1
        while True:
            if ch == ch2 and v > ref.v2:
                break
            t = get_verse(ref.book_no, ch, v)
            if t is None:
                break
            parts.append(t)
            v += 1
    return " ".join(parts)


def _norm_text(s: str) -> str:
    return re.sub(r"[\W_]", "", s)


def quote_matches(quote: str, original: str) -> bool:
    """인용문이 원문(의 일부)과 같은지. 공백·문장부호는 무시한다."""
    q, o = _norm_text(quote), _norm_text(original)
    return bool(q) and q in o


# ==================== 스트리밍 필터 ====================

class VerseStreamFilter:
    """스트리밍 토큰을 받아, 성경 구절 부분만 붙잡았다가 검증한 뒤 내보낸다.

        vf = VerseStreamFilter()
        for delta in llm_stream:
            out = vf.feed(delta)      # 지금 내보내도 되는 글자 (빈 문자열일 수 있음)
        out = vf.finish()             # 남은 글자 + 참고 구절
        vf.report                     # 구절별 검증 결과 (code 방식)
        vf.summary()                  # 로그·Langfuse용 요약 (판정을 쓰면 판정 내역 포함)

    맥락·주소 판정(apply)은 judge에 판정 함수를 넘긴다 — bible_verse_judge.make_judge(client, model)
        judge(text=전체 텍스트, citations=[Citation]) -> (판정 목록, 도구 호출 내역)
        code 방식에서만 쓴다. 절 단위 구절이 처음 나온 지점부터 답변 끝까지 붙잡았다가
        판정 → apply_verdicts → code 검증 순서로 처리해 내보낸다.

    mode="label"은 아무것도 고치지 않고 구절 위치만 기록한다 (find_citations에서 사용).
    """

    def __init__(self, append_references: bool = APPEND_REFERENCE_VERSES,
                 mode: str | None = None, judge=None):
        mode = (mode or VERSE_VERIFY_MODE).lower()
        if mode not in ("code", "off", "label"):
            logger.warning("[VerseCheck] 알 수 없는 VERSE_VERIFY_MODE=%s → code로 진행", mode)
            mode = "code"
        if judge is not None and mode != "code":
            logger.warning("[VerseCheck] 맥락·주소 판정은 code 방식에서만 쓴다 (현재 %s) → 판정 끔", mode)
            judge = None
        self.mode = mode
        self.judge = judge
        self.buf = ""
        self.prev_char = ""
        self.append_references = append_references
        self.report: list[dict] = []
        # 판정(apply) 붙잡기 상태
        self.holding = False                     # 붙잡기 시작했는지
        self.held = ""                           # 붙잡아 둔 원문 (판정할 부분)
        self._hold_raw = ""
        self._emitted: list[str] = []            # 이미 내보낸 글자 (판정에 맥락으로 줌)
        self._shown: set[tuple] = set()          # 답변 안에 원문이 이미 보이는 구절
        self._shown_refs: list[Ref] = []
        self._appendix: list[Ref] = []           # 주소만 언급된 3절 이하 구절
        # label 모드 / 판정 상태
        self._abs = 0                            # 원문에서 지금 buf[0]의 위치
        self._new_cits: list["Citation"] = []
        self.citations: list["Citation"] = []
        self.judge_log: list[dict] = []
        self.judge_status = ""                   # ok / error / no_citations
        self.judge_tool_log: list[dict] = []

    # ---------- 공개 API ----------

    def feed(self, delta: str) -> str:
        if self.mode == "off":
            return delta
        if self.holding:
            self.held += delta
            return ""
        self.buf += delta
        return self._drain(final=False)

    def finish(self) -> str:
        if self.mode == "off":
            out, self.buf = self.buf, ""
            return out
        out = self._drain(final=True)
        if self.holding:
            out += self._judge_held()
        if self.report:
            logger.info(
                "[VerseCheck:%s] %s", self.mode,
                ", ".join(f"{r['ref']}={r['status']}" for r in self.report),
            )
        return out + self._appendix_text()

    def summary(self) -> dict:
        s = {"mode": self.mode, "code": self.report}
        if self.judge is not None:
            s["judge"] = {
                "status": self.judge_status or "not_called",
                "verdicts": self.judge_log,
                "tool_calls": self.judge_tool_log,
            }
        return s

    # ---------- 판정(apply) ----------

    def _start_hold(self, refs: list[Ref], raw: str) -> bool:
        """판정(apply)에서 절 단위 구절이 처음 나오면 여기서부터 답변 끝까지 붙잡는다.
        장만 언급한 구절(창세기 1장)은 대조할 본문이 없어 붙잡지 않는다
        — 창조 관련 답변 앞부분에 자주 나와서, 여기서 붙잡으면 답변 대부분이 멈춘다."""
        if self.holding or self.judge is None:
            return False
        if not any(r.v1 is not None for r in refs):
            return False
        self.holding = True
        self._hold_raw = raw
        return True

    def _judge_held(self) -> str:
        """붙잡은 부분: 구절 검출·표시(코드) → 맥락·주소 판정(LLM) → 수정(코드) → code 검증"""
        segment, self.held = self.held, ""
        context = "".join(self._emitted)
        full = context + segment
        cits = [c for c in find_citations(full) if c.start >= len(context)]
        applied = segment
        if not cits:
            self.judge_status = "no_citations"
        else:
            try:
                verdicts, self.judge_tool_log = self.judge(text=full, citations=cits)
                self.judge_status = "ok"
                new_full, self.judge_log = apply_verdicts(full, cits, verdicts)
                applied = new_full[len(context):]
            except Exception as e:
                logger.warning("[VerseJudge] 판정 실패 → code 방식으로 처리: %s", e)
                self.judge_status = "error"
                self.judge_tool_log = [{"error": str(e)}]
        # 존재하지 않는 구절·틀린 본문 등 나머지는 code 방식 그대로 처리 (판정 실패 시에도 동일)
        net = VerseStreamFilter(append_references=False, mode="code")
        net.prev_char = self.prev_char
        out = net.feed(applied) + net.finish()
        self.report.extend(net.report)
        self._appendix.extend(net._appendix)
        self._shown |= net._shown
        self._shown_refs.extend(net._shown_refs)
        return out

    # ---------- 내부 ----------

    def _drain(self, final: bool) -> str:
        out: list[str] = []
        while self.buf:
            t, kind = self._find_trigger()
            if t is None:
                # 끝의 공백은 다음 글자를 볼 때까지 붙잡는다 — 바로 뒤에 지워질 인용이
                # 오면 공백도 같이 지워야 "지으셨습니다 ." 같은 찌꺼기가 안 남는다.
                keep = self.buf if final else self.buf.rstrip(" \t")
                self._emit(out, keep)
                self.buf = self.buf[len(keep):]
                self._abs += len(keep)
                break
            lead = ""
            if kind in ("quote", "paren"):
                ws = t
                while ws > 0 and self.buf[ws - 1] in " \t":
                    ws -= 1
                lead, head = self.buf[ws:t], self.buf[:ws]
            else:
                head = self.buf[:t]
            self._emit(out, head)
            self.buf = self.buf[t:]
            self._abs += t
            handler = {"quote": self._handle_quote, "paren": self._handle_paren, "book": self._handle_book}[kind]
            res = handler(final)
            if res is None:      # 더 기다려야 함
                self.buf = lead + self.buf
                self._abs -= len(lead)
                self._new_cits = []
                break
            text, consumed = res
            for c in self._new_cits:     # label 모드: 상대 위치 → 원문 위치
                c.shift(self._abs)
                self.citations.append(c)
            self._new_cits = []
            if self.holding:     # 판정(apply): 이 구절부터 끝까지 판정으로 넘긴다
                self.held = lead + self._hold_raw + self.buf[consumed:]
                self.buf = ""
                break
            if text:             # 통째로 지워진 인용이면 앞 공백도 함께 버린다
                self._emit(out, lead + text)
            self.buf = self.buf[consumed:]
            self._abs += consumed
        return "".join(out)

    def _emit(self, out: list[str], text: str) -> None:
        if text:
            out.append(text)
            self._emitted.append(text)
            self.prev_char = text[-1]

    def _find_trigger(self) -> tuple[int | None, str | None]:
        prev = self.prev_char
        for i, c in enumerate(self.buf):
            if c in _OPEN_QUOTES:
                return i, "quote"
            if c == "(":
                return i, "paren"
            if c in _BOOK_FIRST_CHARS and not _HANGUL_RE.match(prev or " "):
                return i, "book"
            prev = c
        return None, None

    # 책 이름으로 시작하는 문장 속 언급: "요한복음 3:16에서", "창세기 5장은"
    def _handle_book(self, final: bool):
        s = self.buf
        m = REF_RE.match(s)
        if m:
            rest = s[m.end():]
            if not final and _CONTINUATION_RE.fullmatch(rest) and len(rest) < 12:
                return None
            ref = parse_ref(m)
            if self.mode == "label":
                self._new_cits.append(Citation(kind="inline", ref=ref, raw=m.group(0),
                                               start=0, end=m.end(), ref_start=0, ref_end=m.end()))
                return m.group(0), m.end()
            if self._start_hold([ref], m.group(0)):
                return "", m.end()
            if ref_exists(ref):
                self._record(ref, "inline", "ok")
                self._maybe_appendix(ref)
                return m.group(0), m.end()
            self._record(ref, "inline", "missing")
            return MISSING_INLINE_REPLACEMENT, m.end()
        if not final and (s in _BOOK_PREFIXES or _PARTIAL_REF_RE.fullmatch(s)):
            return None
        return s[0], 1

    # 괄호 출처: "(창세기 1:24, 개역한글)", "(요한복음 3:16; 로마서 8:28)"
    def _handle_paren(self, final: bool):
        s = self.buf
        e = s.find(")")
        if e == -1:
            inner = s[1:].lstrip()
            if final or len(s) > MAX_PAREN_HOLD:
                return "(", 1
            if not inner or inner in _BOOK_PREFIXES or _PARTIAL_REF_RE.fullmatch(inner) or REF_RE.match(inner):
                return None
            return "(", 1
        inner = s[1:e]
        if not REF_RE.match(inner.lstrip()):
            return "(", 1
        if self.mode == "label":
            group = list(REF_RE.finditer(inner))
            for m in group:
                self._new_cits.append(Citation(kind="paren", ref=parse_ref(m), raw=s[: e + 1],
                                               start=0, end=e + 1, ref_start=1 + m.start(),
                                               ref_end=1 + m.end(), group_size=len(group)))
            return s[: e + 1], e + 1
        if self._start_hold([parse_ref(m) for m in REF_RE.finditer(inner)], s[: e + 1]):
            return "", e + 1
        return self._process_paren(inner), e + 1

    def _process_paren(self, inner: str, kind: str = "paren") -> str:
        refs = list(REF_RE.finditer(inner))
        valid = []
        for m in refs:
            ref = parse_ref(m)
            if ref_exists(ref):
                valid.append(m.group(0))
                self._record(ref, kind, "ok")
                if kind == "paren":
                    self._maybe_appendix(ref)
            else:
                self._record(ref, kind, "missing")
        if len(valid) == len(refs):
            return f"({inner})"
        if not valid:
            return ""
        return "(" + "; ".join(valid) + ")"

    # 인용문 + 출처: "\"본문\" (요한복음 3:16, 개역한글)"
    def _handle_quote(self, final: bool):
        s = self.buf
        closers = _OPEN_QUOTES[s[0]]
        j = next((k for k in range(1, len(s)) if s[k] in closers), -1)
        if j == -1:
            if final or len(s) > MAX_QUOTE_HOLD:
                return s[0], 1
            return None
        k = j + 1
        while k < len(s) and s[k] in " \t":
            k += 1
        if k == len(s):
            return (s[: j + 1], j + 1) if final else None
        if s[k] != "(":
            return s[: j + 1], j + 1
        e = s.find(")", k)
        if e == -1:
            if final or len(s) - k > MAX_PAREN_HOLD:
                return s[: j + 1], j + 1
            return None
        inner = s[k + 1 : e]
        m = REF_RE.match(inner.lstrip())
        if not m:
            return s[: j + 1], j + 1
        if self.mode == "label":
            off = k + 1 + (len(inner) - len(inner.lstrip()))
            self._new_cits.append(Citation(kind="quoted", ref=parse_ref(m), raw=s[: e + 1],
                                           start=0, end=e + 1, ref_start=off, ref_end=off + m.end(),
                                           quote=s[1:j], quote_start=1, quote_end=j, paren_start=k))
            return s[: e + 1], e + 1
        if self._start_hold([parse_ref(m)], s[: e + 1]):
            return "", e + 1
        quote = s[1:j]
        return self._process_quoted(s[0], quote, s[j], s[j + 1 : k], inner, m), e + 1

    def _process_quoted(self, open_q, quote, close_q, gap, inner, m) -> str:
        ref = parse_ref(m)
        if not ref_exists(ref):
            self._record(ref, "quoted", "missing")
            return ""
        paren = f"({inner})"
        if ref.v1 is None:
            # 장만 쓴 출처에는 대조할 본문이 없다 → 존재 확인만
            self._record(ref, "quoted", "ok")
            return f"{open_q}{quote}{close_q}{gap}{paren}"
        if ref.is_short:
            original = ref_text(ref)
            self._shown.add(ref.key)
            self._shown_refs.append(ref)
            if quote_matches(quote, original):
                self._record(ref, "quoted", "ok")
                return f"{open_q}{quote}{close_q}{gap}{paren}"
            self._record(ref, "quoted", "replaced", quote=quote)
            return f"{open_q}{original}{close_q}{gap}{paren}"
        # 4절 이상: 본문이 원문과 맞으면 두고, 다르면 주소만 남긴다
        if quote_matches(quote, ref_range_text(ref)):
            self._record(ref, "quoted", "ok")
            return f"{open_q}{quote}{close_q}{gap}{paren}"
        self._record(ref, "quoted", "quote_dropped", quote=quote)
        return paren

    def _record(self, ref: Ref, kind: str, status: str, **extra) -> None:
        self.report.append({"ref": ref.label, "kind": kind, "status": status, **extra})

    def _maybe_appendix(self, ref: Ref) -> None:
        if ref.is_short:
            self._appendix.append(ref)

    def _appendix_text(self) -> str:
        if not self.append_references:
            return ""
        def covers(a: Ref, b: Ref) -> bool:   # a가 b를 포함하는지 (같은 장 안)
            return (
                (a.book_no, a.chapter) == (b.book_no, b.chapter)
                and a.v1 <= b.v1 and b.v2 <= a.v2 and a.key != b.key
            )

        # 다른 후보나 이미 원문이 보인 인용에 포함되는 구절(6:19 ⊂ 6:19-20)은 뺀다
        covering = self._appendix + [r for r in self._shown_refs]
        lines, seen = [], set(self._shown)
        for ref in self._appendix:
            if ref.key in seen or any(covers(o, ref) for o in covering):
                continue
            seen.add(ref.key)
            lines.append(f"- {ref.label} — {ref_text(ref)}")
            if len(lines) >= MAX_APPENDIX:
                break
        if not lines:
            return ""
        return "\n\n" + APPENDIX_HEADER + "\n" + "\n".join(lines)


# ==================== 구절 위치·표시 (판정용) ====================

@dataclass
class Citation:
    """답변 속 구절 인용 하나. 위치는 원문 텍스트 기준 [start, end)."""
    kind: str                    # quoted / paren / inline
    ref: Ref
    raw: str
    start: int
    end: int
    ref_start: int
    ref_end: int
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None
    paren_start: int | None = None
    group_size: int = 1          # 괄호 하나에 여러 구절이 있을 때 그 수
    id: int = 0
    # 2단계(코드) 표시
    exists: bool = False
    quote_match: bool | None = None   # 인용문이 없거나 장만 언급이면 None
    original: str = ""
    context: str = ""

    def shift(self, base: int) -> None:
        self.start += base
        self.end += base
        self.ref_start += base
        self.ref_end += base
        if self.quote_start is not None:
            self.quote_start += base
            self.quote_end += base
        if self.paren_start is not None:
            self.paren_start += base

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "ref": self.ref.label, "written": self.raw,
            "quote": self.quote, "exists": self.exists, "quote_match": self.quote_match,
            "original": self.original, "context": self.context,
        }


_SENT_END = ".!?\n"


def _context_of(text: str, start: int, end: int, max_len: int = 300) -> str:
    """구절이 들어 있는 문장 + 바로 앞 문장"""
    left = max((text.rfind(ch, 0, start) for ch in _SENT_END), default=-1)
    left2 = max((text.rfind(ch, 0, left) for ch in _SENT_END), default=-1) if left > 0 else -1
    rights = [i for i in (text.find(ch, end) for ch in _SENT_END) if i != -1]
    right = min(rights) + 1 if rights else len(text)
    lo = max(left2 + 1, start - max_len)
    hi = min(right, end + max_len)
    return text[lo:hi].strip()


def find_citations(text: str) -> list[Citation]:
    """텍스트 속 구절 인용을 찾아 위치와 코드 확인 결과(존재·본문 일치·원문)를 붙인다. 고치지 않는다."""
    vf = VerseStreamFilter(append_references=False, mode="label")
    vf.feed(text)
    vf.finish()
    for i, c in enumerate(vf.citations, start=1):
        c.id = i
        c.exists = ref_exists(c.ref)
        if c.exists and c.ref.v1 is not None:
            c.original = ref_text(c.ref) if c.ref.is_short else ref_range_text(c.ref)[:500]
            if c.quote is not None:
                c.quote_match = quote_matches(c.quote, c.original if c.ref.is_short else ref_range_text(c.ref))
        c.context = _context_of(text, c.start, c.end)
    return vf.citations


def best_matching_span(quote: str, original: str, threshold: float = 0.75) -> str | None:
    """원문에서 인용문과 가장 비슷한 연속 구간(어절 단위)을 찾는다. 비슷하지 않으면 None."""
    q = _norm_text(quote)
    words = original.split()
    if not q or not words:
        return None
    n = len(quote.split())
    best, best_ratio = None, 0.0
    for i in range(len(words)):
        for j in range(i + 1, min(len(words), i + n + 3) + 1):
            cand = " ".join(words[i:j])
            r = difflib.SequenceMatcher(None, q, _norm_text(cand)).ratio()
            if r > best_ratio:
                best, best_ratio = cand, r
    return best if best_ratio >= threshold else None


VERSE_CONTEXT_ACTION = os.getenv("VERSE_CONTEXT_ACTION", "log").lower()   # log / remove


def apply_verdicts(text: str, citations: list[Citation], verdicts: list[dict],
                   context_action: str | None = None) -> tuple[str, list[dict]]:
    """LLM 판정 중 코드가 확인할 수 있는 것만 텍스트에 반영한다. (4단계, 코드)

    - wrong_ref + 추천 주소: 추천 주소가 존재하고 인용문이 그 원문과 비슷할 때만
      주소를 바꾸고, 인용문은 새 원문의 해당 구간으로 맞춘다.
    - context_mismatch: context_action=remove일 때만 인용을 지운다 (기본 log: 기록만).
    - 그 밖(없는 구절, 틀린 본문 등)은 손대지 않는다 → 이후 code 검증이 처리한다.
    반환: (새 텍스트, 구절별 처리 기록)
    """
    action = (context_action or VERSE_CONTEXT_ACTION).lower()
    by_id = {v.get("id"): v for v in verdicts if isinstance(v, dict)}
    edits: list[tuple[int, int, str]] = []
    log: list[dict] = []
    for c in citations:
        v = by_id.get(c.id, {})
        verdict = str(v.get("verdict") or "ok")
        entry = {"id": c.id, "ref": c.ref.label, "verdict": verdict,
                 "suggested_ref": v.get("suggested_ref"), "reason": v.get("reason", ""), "applied": "none"}
        if not c.exists:
            entry["applied"] = "code(missing)"
        elif verdict == "wrong_ref" and v.get("suggested_ref"):
            m = REF_RE.search(str(v["suggested_ref"]))
            new = parse_ref(m) if m else None
            if new is None or not ref_exists(new) or new.v1 is None or not new.is_short:
                entry["applied"] = "rejected(추천 주소가 없거나 범위가 김)"
            elif c.quote is None:
                entry["applied"] = "logged(인용문이 없어 확인 불가)"
            else:
                span = best_matching_span(c.quote, ref_text(new))
                if span is None:
                    entry["applied"] = "rejected(인용문이 추천 구절과 다름)"
                else:
                    edits.append((c.ref_start, c.ref_end, new.label))
                    edits.append((c.quote_start, c.quote_end, span))
                    entry["applied"] = f"ref→{new.label}"
        elif verdict == "context_mismatch":
            if action == "remove" and c.group_size == 1:
                start = c.start
                while start > 0 and text[start - 1] in " \t" and c.kind != "inline":
                    start -= 1
                edits.append((start, c.end, MISSING_INLINE_REPLACEMENT if c.kind == "inline" else ""))
                entry["applied"] = "removed"
            else:
                entry["applied"] = "logged"
        log.append(entry)

    for start, end, rep_text in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + rep_text + text[end:]
    if log:
        logger.info("[VerseJudge] %s", ", ".join(f"{e['ref']}={e['verdict']}/{e['applied']}" for e in log))
    return text, log


def verify_answer(answer: str, append_references: bool = APPEND_REFERENCE_VERSES,
                  mode: str | None = "code") -> tuple[str, list[dict]]:
    """스트리밍이 아닌 답변을 한 번에 검증. (검증된 답변, 구절별 결과)"""
    vf = VerseStreamFilter(append_references=append_references, mode=mode)
    out = vf.feed(answer) + vf.finish()
    return out, vf.report


def strip_appendix(answer: str) -> str:
    """답변 끝의 '참고 구절' 블록을 뗀 본문"""
    return answer.split("\n\n" + APPENDIX_HEADER)[0]


def reverify_cached(answer: str) -> str:
    """캐시에서 꺼낸 답변을 code 방식으로 다시 검증한다.

    검증 기능을 넣기 전에 저장된 캐시 답변에는 틀린 구절이 남아 있을 수 있다.
    code 방식은 LLM 호출이 없어 캐시 응답 속도를 거의 해치지 않는다.
    이미 검증된 답변이면 결과가 그대로다 (참고 구절은 떼고 다시 만든다).
    """
    if VERSE_VERIFY_MODE == "off" or not answer:
        return answer
    out, report = verify_answer(strip_appendix(answer), mode="code")
    if out != answer:
        logger.info("[VerseCheck] 캐시 답변 재검증으로 변경됨: %s",
                    ", ".join(f"{r['ref']}={r['status']}" for r in report))
    return out


if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) or '"태초에 하나님이 천지를 창조하시니라" (창세기 1:1, 개역한글)'
    result, report = verify_answer(text)
    print(result)
    for r in report:
        print(r)
