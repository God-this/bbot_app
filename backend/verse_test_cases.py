"""성경 구절 검증 테스트 케이스 — 조합 생성 (test_verse_pipeline.py가 사용)

케이스 = 입력(가짜 LLM이 할 답변) + 정답지(나가야 하는 글자, 나가면 안 되는 글자, 구절별 처리 결과)

정답은 검증 코드(bible_verify.py)로 계산하지 않는다.
코드가 틀리면 정답도 같이 틀려서 테스트가 항상 통과해 버리기 때문이다.
  - 원문: bible.txt(개역한글 전체, 운영 DB bible_krv와 31,101절 동일)에서 직접 꺼낸다
  - 기대 결과: 규칙표(프로젝트 문서 design/답변생성후_구절검색.md)에 정한 대로 적는다

케이스 나무 (2026-11-02 랩미팅)
  test1  답변에 성경 구절 없음                 → 그대로
  2-1-a  존재 + 본문 일치 + 문맥 맞음          → 그대로
  2-1-b  존재 + 본문 일치 + 문맥 불일치        → 기본(shadow)은 기록만, apply+remove면 삭제
  2-2-a  본문 불일치 (3절 이하)                → 원문으로 교체 (다른 구절 본문이어도 주소를 믿음)
  2-2-b  본문 불일치 (4절 이상)                → 본문 빼고 주소만
  2-3    없는 구절                             → 삭제 (문장 속 언급은 '성경'으로)
  2-4    주소만 (본문 없음)                    → 그대로 + 끝에 참고 구절
  2-5    장만 언급                             → 있으면 그대로, 없으면 '성경'으로
  2-6    여러 구절 섞임                        → 각각 처리
  safety 안전장치 (판정 LLM 오류, 캐시, 차단, fallback, 마크다운)
  todo   아직 못 하는 것 (xfail — 고치면 통과하게 됨)

케이스는 '문장 틀 × 구절 × 쓰는 모양'을 곱해서 만든다.
새 케이스를 넣으려면 해당 항목의 생성 함수에 구절·문장 틀을 추가하거나, EXTRA_CASES에 직접 적는다.

성경 원문은 backend/bible.txt를 쓴다. 저작권·용량 문제로 저장소에 올리지 않으므로(.gitignore)
각자 로컬에 있어야 한다. 없으면 테스트는 건너뛴다.
케이스에 다른 책을 쓰려면 아래 BOOK_ABBR에 그 책을 추가한다.
"""
import random
import re
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

# ==================== 항목 (점수표 순서) ====================

GROUPS = {
    "test1": "구절 없음",
    "2-1-a": "존재 + 본문 일치 + 문맥 맞음",
    "2-1-b": "존재 + 본문 일치 + 문맥 불일치",
    "2-2-a": "본문 불일치 (3절 이하) → 원문 교체",
    "2-2-b": "본문 불일치 (4절 이상) → 주소만",
    "2-3": "없는 구절 → 삭제",
    "2-4": "주소만 → 참고 구절",
    "2-5": "장만 언급",
    "2-6": "여러 구절 섞임",
    "safety": "안전장치",
    "todo": "아직 못 하는 것",
}

APPENDIX = "참고 구절"   # 답변 끝 참고 구절 머리글에 들어가는 말


@dataclass
class Case:
    id: str
    group: str
    note: str                                   # 무엇을 확인하는지 (실패 시 표시)
    answer: str                                 # 가짜 LLM의 답변 (path=cache면 캐시에 든 답변)
    must: list[str] = field(default_factory=list)       # 출력에 있어야 하는 글자
    must_not: list[str] = field(default_factory=list)   # 출력에 없어야 하는 글자
    exact: str | None = None                    # 출력 전체가 이것과 같아야 할 때
    counts: dict[str, int] = field(default_factory=dict)  # 글자가 정확히 몇 번 나와야 하는지
    statuses: list[str] | None = None           # 구절별 code 검증 결과 (None이면 확인 안 함)
    path: str = "llm"                           # llm / cache / blocked / fallback
    block_reason: str = ""
    judge_mode: str = "off"                     # off / shadow / apply
    judge: str | None = None                    # 판정 LLM이 내릴 판정, "error"면 오류를 냄
    context_action: str = "log"                 # log / remove
    judge_called: bool | None = None            # 판정 LLM이 불려야 하는지
    shadow_status: str | None = None            # shadow 기록 status (ok / error / no_citations)
    shadow_counts: dict[str, int] = field(default_factory=dict)
    todo: str | None = None                     # 아직 못 하는 것: 이유


# ==================== 성경 원문 (고정 데이터) ====================

BIBLE_FILE = Path(__file__).parent / "bible.txt"
BIBLE_AVAILABLE = BIBLE_FILE.exists()

# 케이스에 쓰는 책 (정식 이름 → bible.txt 약어). 다른 책을 쓰려면 여기에 추가
BOOK_ABBR = {"창세기": "창", "시편": "시", "요한복음": "요", "로마서": "롬"}
_SUPERSCRIPTION = re.compile(r"^\{[^}]*\}\s*")   # 시편 표제 {다윗의 시}는 보여주지 않음


def _load_bible() -> dict[tuple[str, int], dict[int, str]]:
    """bible.txt에서 케이스에 쓰는 책만 읽는다 (검증 코드와 별개로 읽어서 정답을 만든다)"""
    if not BIBLE_AVAILABLE:
        return {}
    wanted = {abbr: name for name, abbr in BOOK_ABBR.items()}
    line_re = re.compile(r"^(\D+?)(\d+):(\d+)\s+(.*)$")
    out: dict[tuple[str, int], dict[int, str]] = {}
    for line in BIBLE_FILE.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line.strip())
        if m and m.group(1) in wanted:
            out.setdefault((wanted[m.group(1)], int(m.group(2))), {})[int(m.group(3))] = m.group(4).strip()
    return out


_CH = _load_bible()


@dataclass(frozen=True)
class R:
    """구절 주소. v1이 없으면 장만 언급."""
    book: str
    ch: int
    v1: int | None = None
    v2: int | None = None
    ch2: int | None = None      # 장을 넘는 범위 (창세기 1:31-2:3)

    @property
    def unit(self) -> str:
        return "편" if self.book == "시편" else "장"

    @property
    def label(self) -> str:
        """답변 끝 참고 구절에 표시되는 정식 표기"""
        if self.v1 is None:
            return f"{self.book} {self.ch}{self.unit}"
        if self.ch2:
            return f"{self.book} {self.ch}:{self.v1}-{self.ch2}:{self.v2}"
        return f"{self.book} {self.ch}:{self.v1}" + (f"-{self.v2}" if self.v2 != self.v1 else "")

    def write(self, style: str = "colon") -> str:
        """LLM이 쓸 법한 여러 표기
        colon 창세기 1:1-3 / tilde 창세기 1:1~3 / korean 창세기 1장 1-3절 / eseo 창세기 1장 1절에서 3절"""
        b, c, u = self.book, self.ch, self.unit
        if self.v1 is None:
            return f"{b} {c}{u}"
        if self.ch2:
            return self.label
        rng = self.v2 != self.v1
        if style == "tilde":
            return f"{b} {c}:{self.v1}" + (f"~{self.v2}" if rng else "")
        if style == "korean":
            return f"{b} {c}{u} {self.v1}" + (f"-{self.v2}" if rng else "") + "절"
        if style == "eseo":
            return f"{b} {c}{u} {self.v1}절" + (f"에서 {self.v2}절" if rng else "")
        return self.label

    @property
    def text(self) -> str:
        """원문 (같은 장 안의 범위)"""
        verses = _CH[(self.book, self.ch)]
        return " ".join(_SUPERSCRIPTION.sub("", verses[v]) for v in range(self.v1, self.v2 + 1)).strip()


def r(book, ch, v1=None, v2=None, ch2=None) -> R:
    return R(book, ch, v1, v2 if v2 is not None else v1, ch2)


# ==================== 재료 ====================

# 존재하는 짧은 구절 (3절 이하)
SHORT = [
    r("창세기", 1, 1), r("창세기", 1, 3), r("창세기", 1, 27), r("창세기", 1, 31), r("창세기", 2, 7),
    r("요한복음", 3, 16), r("로마서", 8, 28), r("창세기", 1, 1, 3), r("요한복음", 3, 16, 17), r("창세기", 2, 1, 3),
]
# 존재하는 긴 범위 (4절 이상) — 앞의 두 개는 딱 4절인 경계 케이스
LONG = [r("창세기", 1, 1, 4), r("로마서", 8, 28, 31),
        r("창세기", 1, 1, 10), r("창세기", 1, 26, 31), r("창세기", 2, 1, 7), r("요한복음", 3, 1, 15), r("로마서", 8, 1, 11)]
# 존재하지 않는 구절 (실제 성경에도 없음)
MISSING = [r("창세기", 1, 99), r("창세기", 100, 100), r("요한복음", 3, 99), r("로마서", 8, 50), r("요한복음", 30, 1)]
CH_OK = [r("창세기", 1), r("창세기", 2), r("요한복음", 3), r("로마서", 8), r("시편", 23)]
CH_MISSING = [r("창세기", 60), r("요한복음", 30), r("로마서", 20), r("시편", 151), r("창세기", 100)]

QUOTES = [('"', '"'), ("“", "”"), ("「", "」"), ("『", "』")]

# 원문과 다른 인용문 (어떤 구절의 원문에도 들어 있지 않은 문장)
PARAPHRASE = [
    "하나님께서 하늘과 땅을 만드셨다",
    "빛이 생겨라 하시니 빛이 생겼다",
    "하나님은 우리를 끝까지 지키신다",
    "모든 것이 아주 보기 좋았다",
    "사람을 하나님의 모습으로 만드셨다",
]

# 문장 틀 — 책 이름이나 숫자가 들어가지 않게 쓴다
QUOTE_TPL = [
    "성경은 이렇게 말합니다. {X}",
    "{X} 이 말씀이 창조의 근거입니다.",
    "하나님을 기억합시다. {X} 그러므로 감사합니다.",
    "핵심 말씀은 다음과 같습니다.\n\n{X}\n\n함께 묵상해 봅시다.",
]
INLINE_TPL = [
    "{R}에서 말하듯 하나님은 창조주이십니다.",
    "{R}을 보면 하나님의 뜻을 알 수 있습니다.",
    "우리는 {R}의 말씀을 기억해야 합니다.",
    "이 내용은 {R}에 기록되어 있습니다.",
]
PAREN_SENTENCES = [
    "하나님이 사람을 지으셨습니다",
    "빛이 처음 창조되었습니다",
    "하나님은 세상을 사랑하십니다",
    "모든 것이 합력하여 선을 이룹니다",
    "하나님이 천지를 창조하셨습니다",
]
CH_TPL = ["{R}에 그 이야기가 나옵니다.", "{R}을 읽어 보면 창조의 순서가 보입니다."]

STYLES = ["colon", "korean", "tilde", "eseo"]
INLINE_STYLES = ["colon", "korean", "tilde"]   # 문장 속에서 '…절에서 3절에서'처럼 어색한 eseo는 뺀다


def quoted(quote: str, ref_written: str, q=QUOTES[0], version: bool = False) -> str:
    return f"{q[0]}{quote}{q[1]} ({ref_written}{', 개역한글' if version else ''})"


def other_verse(ref: R) -> R:
    """다른 책의 짧은 구절 (본문을 잘못 가져온 경우용)"""
    return next(o for o in SHORT if o.book != ref.book and o.v1 == o.v2)


def tweak(text: str) -> str:
    """원문에 말 한마디를 끼워 넣어 원문과 다르게 만든다"""
    words = text.split()
    return " ".join([words[0], "참으로", *words[1:]])


# ==================== 항목별 생성 ====================

def g_test1() -> list[Case]:
    sentences = [
        "창조는 6일 동안 이루어졌다고 봅니다.",
        "지구의 나이는 약 6천 년으로 봅니다.",
        "두 이론은 약 3:1 비율로 논의됩니다.",
        "요한은 이사를 갔고 시간이 흘러 마가 끼었습니다.",
        '"빅뱅"(대폭발) 이론은 한계가 있습니다.',
        '"지적 설계"는 중요한 개념입니다.',
        "공룡 화석은 (흔히 말하는 수천만 년과 달리) 젊은 지구를 지지합니다.",
        "전도서를 쓴 사람은 솔로몬으로 알려져 있습니다.",
        "요한복음은 하나님의 사랑을 강조합니다.",
        "마가와 누가는 복음서를 기록했습니다.",
        "아가서는 사랑의 노래입니다.",
        "앞의 1장에서 설명했듯이 창조는 중요합니다.",
        "노아의 방주는 길이가 약 135미터였습니다.",
    ]
    cases = []
    for i, (s, mode) in enumerate(product(sentences, ["off", "shadow"]), 1):
        cases.append(Case(
            f"test1-{i:02d}", "test1", "구절 없는 답변은 그대로" + (" + 판정 LLM 호출 없음" if mode == "shadow" else ""),
            s, exact=s, statuses=[],
            judge_mode=mode, judge="ok" if mode == "shadow" else None,
            judge_called=False if mode == "shadow" else None,
            shadow_status="no_citations" if mode == "shadow" else None,
        ))
    return cases


def g_21a() -> list[Case]:
    cases, n = [], 0

    def add(note, ans):
        nonlocal n
        n += 1
        cases.append(Case(f"2-1-a-{n:02d}", "2-1-a", note, ans, exact=ans, statuses=["ok"]))

    for i, (ref, q) in enumerate(product(SHORT, QUOTES[:2])):
        w = ref.write(STYLES[i % 4])
        add(f"정확한 인용 {w}", QUOTE_TPL[i % 4].format(X=quoted(ref.text, w, q, version=i % 3 == 0)))
    for i, q in enumerate(QUOTES[2:]):            # 「」 『』 따옴표
        for ref in (SHORT[1], SHORT[6]):
            add(f"정확한 인용 {q[0]}{q[1]} {ref.label}", QUOTE_TPL[i].format(X=quoted(ref.text, ref.label, q)))
    # 원문 일부만 정확히 인용 (원문에 그대로 들어 있으면 일치로 본다)
    add("원문 일부 인용 창세기 1:3", QUOTE_TPL[0].format(X=quoted("하나님이 가라사대 빛이 있으라", "창세기 1:3")))
    add("원문 일부 인용 요한복음 3:16", QUOTE_TPL[1].format(X=quoted("하나님이 세상을 이처럼 사랑하사", "요한복음 3:16")))
    # 4절 이상 범위인데 인용이 원문 일부와 일치
    add("4절 이상 + 일치 창세기 1:1-10", QUOTE_TPL[2].format(X=quoted(r("창세기", 1, 1).text, "창세기 1:1-10")))
    add("4절 이상 + 일치 창세기 1장 26절에서 31절", QUOTE_TPL[0].format(X=quoted(r("창세기", 1, 27).text, r("창세기", 1, 26, 31).write("eseo"))))
    return cases


def g_21b() -> list[Case]:
    cases = []
    tpl = "사람은 귀합니다. {X} 그러므로 서로 사랑합시다."
    refs = SHORT[:7]
    for i, (ref, mode) in enumerate(product(refs, ["shadow", "apply-log", "apply-remove"]), 1):
        w = ref.write(STYLES[i % 2])
        ans = tpl.format(X=quoted(ref.text, w))
        base = dict(id=f"2-1-b-{i:02d}", group="2-1-b", answer=ans, judge="context_mismatch",
                    judge_called=True, statuses=["ok"])
        if mode == "shadow":
            cases.append(Case(note=f"shadow: 답변 그대로, 판정만 기록 ({w})", exact=ans, judge_mode="shadow",
                              shadow_status="ok", shadow_counts={"context_mismatch": 1}, **base))
        elif mode == "apply-log":
            cases.append(Case(note=f"apply + log: 답변 그대로 ({w})", exact=ans, judge_mode="apply", **base))
        else:
            cases.append(Case(note=f"apply + remove: 인용 삭제 ({w})", judge_mode="apply", context_action="remove",
                              must=["사람은 귀합니다.", "그러므로 서로 사랑합시다."], must_not=[w, ref.text],
                              **{**base, "statuses": []}))
    return cases


def g_22a() -> list[Case]:
    cases = []
    kinds = ["paraphrase", "other", "tweak"]
    for i, (ref, kind) in enumerate(product(SHORT, kinds), 1):
        w = ref.write(STYLES[i % 4])
        q = QUOTES[i % 2]
        if kind == "paraphrase":
            wrong, note = PARAPHRASE[i % 5], "다른 말로 바꿔 쓴 인용"
        elif kind == "other":
            o = other_verse(ref)
            wrong, note = o.text, f"다른 구절({o.label}) 본문을 가져옴 → 주소를 믿고 교체"
        else:
            wrong, note = tweak(ref.text), "원문에 말을 끼워 넣은 인용"
        ans = QUOTE_TPL[i % 4].format(X=quoted(wrong, w, q))
        cases.append(Case(f"2-2-a-{i:02d}", "2-2-a", f"{note} {w}", ans,
                          must=[f"{q[0]}{ref.text}{q[1]} ({w})"], must_not=[wrong], statuses=["replaced"]))
    gen131 = r("창세기", 1, 31)
    ans = QUOTE_TPL[0].format(X=quoted("하나님이 보시기에 좋았더라", "창세기 1:31"))
    cases.append(Case(f"2-2-a-{len(cases) + 1:02d}", "2-2-a", "축약 인용 → 원문 교체 창세기 1:31", ans,
                      must=[f'"{gen131.text}" (창세기 1:31)'], must_not=['"하나님이 보시기에 좋았더라"'],
                      statuses=["replaced"]))
    return cases


def g_22b() -> list[Case]:
    cases = []
    for i, (ref, kind, style) in enumerate(product(LONG, ["paraphrase", "other"], ["colon", "eseo"]), 1):
        w = ref.write(style)
        wrong = PARAPHRASE[i % 5] if kind == "paraphrase" else other_verse(ref).text
        ans = QUOTE_TPL[i % 4].format(X=quoted(wrong, w))
        cases.append(Case(f"2-2-b-{i:02d}", "2-2-b", f"4절 이상 + 틀린 본문 → 주소만 {w}", ans,
                          must=[f"({w})"], must_not=[wrong], statuses=["quote_dropped"]))
    cross = r("창세기", 1, 31, 3, ch2=2)
    for wrong in PARAPHRASE[:2]:
        ans = QUOTE_TPL[0].format(X=quoted(wrong, cross.write()))
        cases.append(Case(f"2-2-b-{len(cases) + 1:02d}", "2-2-b", "장을 넘는 범위 + 틀린 본문 창세기 1:31-2:3", ans,
                          must=[f"({cross.write()})"], must_not=[wrong], statuses=["quote_dropped"]))
    return cases


def g_23() -> list[Case]:
    cases = []
    for i, (ref, shape, style) in enumerate(product(MISSING, ["quoted", "paren", "inline"], ["colon", "korean"]), 1):
        w = ref.write(style)
        if shape == "quoted":
            p = PARAPHRASE[i % 5]
            ans = QUOTE_TPL[i % 4].format(X=quoted(p, w))
            c = Case("", "2-3", f"없는 구절 · 따옴표 인용 → 통째로 삭제 {w}", ans, must_not=[p, w])
        elif shape == "paren":
            s = PAREN_SENTENCES[i % 5]
            ans = f"{s} ({w})."
            c = Case("", "2-3", f"없는 구절 · 괄호 출처 → 괄호 삭제 {w}", ans, must=[f"{s}."], must_not=[w])
        else:
            tpl = INLINE_TPL[i % 4]
            ans = tpl.format(R=w)
            c = Case("", "2-3", f"없는 구절 · 문장 속 → '성경'으로 {w}", ans,
                     must=[tpl.format(R="성경")], must_not=[w])
        c.id, c.statuses = f"2-3-{i:02d}", ["missing"]
        cases.append(c)
    return cases


def g_24() -> list[Case]:
    cases = []
    for i, (ref, shape) in enumerate(product(SHORT, ["inline", "paren"]), 1):
        w = ref.write(INLINE_STYLES[i % 3])
        ans = INLINE_TPL[i % 4].format(R=w) if shape == "inline" else f"{PAREN_SENTENCES[i % 5]} ({w})."
        cases.append(Case(f"2-4-{i:02d}", "2-4", f"주소만 ({'문장 속' if shape == 'inline' else '괄호'}) → 참고 구절 {w}",
                          ans, must=[ans, APPENDIX, f"{ref.label} — {ref.text}"], statuses=["ok"]))
    n = len(cases)
    extra = [
        Case("", "2-4", "시편 '편' 표기 → 참고 구절", "시편 23편 1절처럼 우리는 부족함이 없습니다.",
             must=["시편 23편 1절처럼", APPENDIX, "시편 23:1 — 여호와는 나의 목자시니"], must_not=["{다윗의 시}"],
             statuses=["ok"]),
        Case("", "2-4", "4절 이상 주소 → 참고 구절 안 붙음", "창세기 1:1-10을 읽어 보세요.",
             exact="창세기 1:1-10을 읽어 보세요.", statuses=["ok"]),
        Case("", "2-4", "딱 4절 주소 (경계) → 참고 구절 안 붙음", "창세기 1:1-4에서 빛과 어둠이 나뉩니다.",
             exact="창세기 1:1-4에서 빛과 어둠이 나뉩니다.", statuses=["ok"]),
        Case("", "2-4", "딱 3절 주소 (경계) → 참고 구절 붙음", "로마서 8:28-30에서 말하듯 모든 것이 합력합니다.",
             must=[APPENDIX, f"로마서 8:28-30 — {r('로마서', 8, 28, 30).text}"], statuses=["ok"]),
        Case("", "2-4", "4절 이상 주소(한글 표기) → 참고 구절 안 붙음", "요한복음 3장 1절에서 15절까지 니고데모 이야기가 나옵니다.",
             exact="요한복음 3장 1절에서 15절까지 니고데모 이야기가 나옵니다.", statuses=["ok"]),
        Case("", "2-4", "같은 주소 두 번 → 참고 구절 한 번만", "요한복음 3:16에서 말하듯, 다시 요한복음 3:16을 보면 사랑을 알 수 있습니다.",
             counts={"요한복음 3:16 —": 1}, statuses=["ok", "ok"]),
        Case("", "2-4", "주소 4개 → 참고 구절 최대 3개", "창세기 1:1, 창세기 1:27, 요한복음 3:16, 로마서 8:28을 기억합시다.",
             must=[APPENDIX], counts={"\n- ": 3}, statuses=["ok"] * 4),
    ]
    for j, c in enumerate(extra, n + 1):
        c.id = f"2-4-{j:02d}"
        cases.append(c)
    return cases


def g_25() -> list[Case]:
    cases = []
    for ref, tpl in product(CH_OK, CH_TPL):
        ans = tpl.format(R=ref.write())
        cases.append(Case("", "2-5", f"있는 장 → 그대로 {ref.write()}", ans, exact=ans, statuses=["ok"]))
    for ref, tpl in product(CH_MISSING, CH_TPL):
        ans = tpl.format(R=ref.write())
        cases.append(Case("", "2-5", f"없는 장 → '성경'으로 {ref.write()}", ans,
                          must=[tpl.format(R="성경")], must_not=[ref.write()], statuses=["missing"]))
    for ref in (r("창세기", 1), r("요한복음", 3)):
        ans = QUOTE_TPL[0].format(X=quoted(PARAPHRASE[0], ref.write()))
        cases.append(Case("", "2-5", f"인용 + 장만 쓴 출처 → 대조할 본문이 없어 그대로 {ref.write()}", ans,
                          exact=ans, statuses=["ok"]))
    for i, c in enumerate(cases, 1):
        c.id = f"2-5-{i:02d}"
    return cases


# ---------- 2-6: 여러 구절 조각을 섞는다 ----------

def _piece(kind: str, ref: R, para: str) -> dict:
    """한 구절 조각과 그 정답. 조각을 이어 붙이면 정답도 이어 붙인다."""
    w = ref.label
    if kind == "ok":
        f = quoted(ref.text, w)
        return dict(frag=f, must=[f], must_not=[], status="ok")
    if kind == "wrong":
        return dict(frag=quoted(para, w), must=[quoted(ref.text, w)], must_not=[para], status="replaced")
    if kind == "missing":
        return dict(frag=quoted(para, w), must=[], must_not=[para, w], status="missing")
    if kind == "address":
        f = f"{w}을 기억합시다."
        return dict(frag=f, must=[f, f"{ref.label} — "], must_not=[], status="ok")
    if kind == "missing_inline":
        return dict(frag=f"{w}에서 말하듯 하나님은 선하십니다.", must=["성경에서 말하듯 하나님은 선하십니다."],
                    must_not=[w], status="missing")
    raise ValueError(kind)


def mixed(pieces: list[tuple[str, R]], connectors=("첫째,", "둘째,", "셋째,", "넷째,")) -> dict:
    paras = list(PARAPHRASE)
    parts = [_piece(k, ref, paras.pop()) for k, ref in pieces]
    ans = " ".join(f"{connectors[i]} {p['frag']}" for i, p in enumerate(parts))
    return dict(answer=ans,
                must=[m for p in parts for m in p["must"]],
                must_not=[m for p in parts for m in p["must_not"]],
                statuses=[p["status"] for p in parts])


def g_26() -> list[Case]:
    rnd = random.Random(20261102)
    short_single = [s for s in SHORT if s.v1 == s.v2]
    cases = []
    while len(cases) < 20:
        size = rnd.randint(2, 4)
        kinds = [rnd.choice(["ok", "wrong", "missing", "address", "missing_inline"]) for _ in range(size)]
        if kinds.count("address") > 2 or len(set(kinds)) < 2:
            continue
        oks = rnd.sample(short_single, size)
        miss = rnd.sample(MISSING, size)
        pieces = [(k, miss[i] if k.startswith("missing") else oks[i]) for i, k in enumerate(kinds)]
        m = mixed(pieces)
        cases.append(Case(f"2-6-{len(cases) + 1:02d}", "2-6", "섞임: " + " + ".join(kinds), **m))
    paren = [
        ("(창세기 1:1; 로마서 8:28)", ["(창세기 1:1; 로마서 8:28)", "창세기 1:1 —", "로마서 8:28 —"], [], ["ok", "ok"],
         "한 괄호에 여러 구절 (모두 있음)"),
        ("(창세기 1:99; 로마서 8:28)", ["(로마서 8:28)"], ["창세기 1:99"], ["missing", "ok"],
         "한 괄호에 여러 구절 (없는 구절만 삭제)"),
        ("(창세기 1:99; 요한복음 3:99)", ["하나님은 창조주이십니다."], ["창세기 1:99", "요한복음 3:99"], ["missing", "missing"],
         "한 괄호에 여러 구절 (모두 없음 → 괄호 삭제)"),
        ("(요한복음 3:16; 창세기 100:100; 로마서 8:28)", ["(요한복음 3:16; 로마서 8:28)"], ["창세기 100:100"],
         ["ok", "missing", "ok"], "한 괄호에 세 구절 (가운데만 없음)"),
        ("(창세기 1장; 시편 151편)", ["(창세기 1장)"], ["시편 151편"], ["ok", "missing"], "한 괄호에 장 두 개 (없는 장만 삭제)"),
    ]
    for p, must, must_not, st, note in paren:
        cases.append(Case(f"2-6-{len(cases) + 1:02d}", "2-6", note, f"하나님은 창조주이십니다 {p}.",
                          must=must, must_not=must_not, statuses=st))
    return cases


def g_safety() -> list[Case]:
    g11, g13, j316 = r("창세기", 1, 1), r("창세기", 1, 3), r("요한복음", 3, 16)
    samples = [
        mixed([("wrong", g11)]),
        mixed([("missing", MISSING[1])]),
        mixed([("address", j316), ("wrong", g13)]),
        mixed([("ok", g11), ("missing_inline", MISSING[0]), ("wrong", j316)]),
    ]
    cases = []
    for mode in ("shadow", "apply"):
        for m in samples:
            cases.append(Case("", "safety", f"판정 LLM 오류({mode}) → code 검증 결과 그대로", judge_mode=mode, judge="error",
                              judge_called=True, shadow_status="error" if mode == "shadow" else None, **m))
    cache_samples = samples + [mixed([("missing_inline", MISSING[3])])]
    for m in cache_samples:
        cases.append(Case("", "safety", "캐시 답변 → 꺼낼 때 재검증 (LLM 호출 없음)", path="cache",
                          answer=m["answer"], must=m["must"], must_not=m["must_not"]))
    for reason in ("off_topic:관련 없는 질문", "jailbreak:규칙 변경 시도"):
        cases.append(Case("", "safety", f"차단된 질문 → 안내 문구, LLM 호출 없음 ({reason.split(':')[0]})",
                          answer="", path="blocked", block_reason=reason))
    cases.append(Case("", "safety", "자료 부족 fallback → 메시지 그대로, LLM 호출 없음",
                      answer="자료를 찾지 못했어요.", path="fallback", exact="자료를 찾지 못했어요."))
    p = PARAPHRASE[0]
    markdown = [
        (f'**"{p}" (창세기 1:1)**', [f'**"{g11.text}" (창세기 1:1)**'], [p], ["replaced"], "굵은 글씨 속 인용"),
        (f'- "{p}" (창세기 1:3)\n- 두 번째 항목', [f'- "{g13.text}" (창세기 1:3)\n- 두 번째 항목'], [p], ["replaced"],
         "목록 속 인용"),
        ("### 창세기 1:99에서 배우는 점\n\n본문입니다.", ["### 성경에서 배우는 점\n\n본문입니다."], ["창세기 1:99"], ["missing"],
         "제목 속 없는 구절"),
        (f'첫 문단입니다.\n\n"{p}" (요한복음 3:16)\n\n둘째 문단입니다.',
         [f'첫 문단입니다.\n\n"{j316.text}" (요한복음 3:16)\n\n둘째 문단입니다.'], [p], ["replaced"], "문단 사이 인용"),
        ("1. 하나님이 사람을 지으셨습니다 (창세기 100:100).\n2. 감사합시다.",
         ["1. 하나님이 사람을 지으셨습니다.\n2. 감사합시다."], ["창세기 100:100"], ["missing"], "번호 목록 속 없는 구절"),
    ]
    for ans, must, must_not, st, note in markdown:
        cases.append(Case("", "safety", f"마크다운: {note}", ans, must=must, must_not=must_not, statuses=st))
    for i, c in enumerate(cases, 1):
        c.id = f"safety-{i:02d}"
    return cases


def g_todo() -> list[Case]:
    p = PARAPHRASE[0]
    items = [
        (f'창세기 1:1에서 "{p}"라고 말합니다.', [p], "주소 뒤 인용(주소에서 \"…\"라고)은 대조하지 않음"),
        (f'창세기 1장 1절에 따르면 "{p}"입니다.', [p], "주소 뒤 인용(…에 따르면 \"…\")은 대조하지 않음"),
        (f'요한복음 3:16은 "{p}"라고 기록합니다.', [p], "주소 뒤 인용(…은 \"…\"라고)은 대조하지 않음"),
        ('God is good. "I will keep you" (Genesis 100:100)', ["Genesis 100:100"], "영어 책 이름은 검출하지 않음"),
        (f'"{p}"\n(창세기 1:1)', [p], "인용과 출처 사이에 줄바꿈이 있으면 대조하지 않음"),
    ]
    return [Case(f"todo-{i:02d}", "todo", reason, ans, must_not=must_not, todo=reason)
            for i, (ans, must_not, reason) in enumerate(items, 1)]


# 직접 적는 케이스 (필요하면 여기에 추가)
EXTRA_CASES: list[Case] = []


def build_cases() -> list[Case]:
    if not BIBLE_AVAILABLE:
        return []
    cases = (g_test1() + g_21a() + g_21b() + g_22a() + g_22b() + g_23() + g_24() + g_25() + g_26()
             + g_safety() + g_todo() + EXTRA_CASES)
    ids = [c.id for c in cases]
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, f"케이스 id 중복: {dup}"
    assert all(c.group in GROUPS for c in cases)
    return cases


if __name__ == "__main__":
    # 케이스 목록 보기: python verse_test_cases.py
    from collections import Counter
    cs = build_cases()
    for c in cs:
        print(f"{c.id:12} {c.note}\n             {c.answer!r}")
    print()
    for g, n in Counter(c.group for c in cs).items():
        print(f"{g:7} {GROUPS[g]:32} {n}개")
    print(f"총 {len(cs)}개")
