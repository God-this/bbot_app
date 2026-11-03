"""성경 구절 검증 — 답변 생성 LLM을 mock으로 바꾼 파이프라인 테스트

    cd backend && python -m pytest test_verse_pipeline.py          # 전체 + 항목별 점수
    python -m pytest test_verse_pipeline.py -k 2-3                  # 한 항목만
    python -m pytest test_verse_pipeline.py -k 2-3-07 -vv           # 케이스 하나 자세히

왜 mock인가 (2026-11-02 랩미팅)
  질문을 하나씩 넣어 보면 오래 걸리고, 같은 질문에도 답변이 매번 달라 결과가 보장되지 않는다.
  그래서 답변 LLM을 "어떤 질문이 와도 정해 둔 답을 하는" 가짜(mock)로 바꾸고,
  그 답이 실제 generate() / generate_stream()을 거쳐 사용자에게 어떻게 나가는지 확인한다.
  예) 무조건 '창세기 100:100'(없는 구절)을 인용하는 답 → 실제로 지워져서 나가는지

구성
  - 가짜: 답변 LLM(MockAnswerLLM), 판정 LLM(MockJudge), 검색·가드레일·캐시·DB·Langfuse
  - 진짜: 구절 검출 → 원문 대조 → 삭제·교체 → 전송 (bbot_graph, bible_verify)
  - 케이스: verse_test_cases.py (조합 생성, 정답은 성경 데이터와 규칙에서)
  - 점수: conftest.py가 항목별로 모아 마지막에 표시

케이스 하나는 일반 응답 1번 + 스트리밍 3번(토큰을 자르는 위치를 바꿔 가며)으로 돌리고,
네 결과가 모두 같고 정답지와 맞아야 통과한다.

필요한 것: pytest, 그리고 backend/bible.txt (성경 원문. 저장소에는 없으니 각자 로컬에 둔다 — 없으면 건너뜀)
API·DB·Redis·Langfuse는 필요 없다.
"""
import os
os.environ["BIBLE_SOURCE"] = "file"     # 원문은 DB 대신 bible.txt (DB와 31,101절 동일)

import random
import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from verse_test_cases import BIBLE_AVAILABLE, build_cases

if not BIBLE_AVAILABLE:
    pytest.skip("backend/bible.txt가 없어 성경 구절 검증 테스트를 건너뜀", allow_module_level=True)

import bible_verify as bv
import bible_verse_judge  # noqa: F401  (bbot_graph보다 먼저 진짜 모듈을 올려 둔다)

STREAM_SEEDS = (0, 1, 2)


# ==================== 성경 원문 ====================

@pytest.fixture(autouse=True)
def bible_from_file(monkeypatch):
    """다른 테스트가 bible_verify를 먼저 불러왔어도 원문은 bible.txt에서 보게 한다"""
    monkeypatch.setattr(bv, "BIBLE_SOURCE", "file")


# ==================== 외부 모듈 가짜 ====================

class FakeLangfuse:
    """Langfuse 대신 — 기록된 span 내용을 모아 두고 테스트에서 확인한다"""

    def __init__(self):
        self.updates: list[dict] = []

    def update_current_span(self, **kw):
        self.updates.append(kw)

    def flush(self):
        pass

    def metadata_for(self, path: str) -> dict | None:
        for u in reversed(self.updates):
            md = u.get("metadata") or {}
            if md.get("path") == path:
                return md
        return None

    def shadow_result(self) -> dict | None:
        for u in reversed(self.updates):
            if isinstance(u.get("input"), dict) and "raw_answer" in u["input"]:
                return u["output"]
        return None


LANGFUSE = FakeLangfuse()


def _observe(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]
    return lambda fn: fn


@contextmanager
def _propagate_attributes(**kwargs):
    yield


def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m


class _Anything:
    def __init__(self, *a, **k):
        pass


_STUBS = {
    "config": _module("config", LLM_MODEL="mock-llm", PROVIDER="openai", OPENAI_API_KEY="test"),
    "llm_factory": _module("llm_factory", get_client=lambda *a, **k: None),
    "langfuse": _module("langfuse", observe=_observe, propagate_attributes=_propagate_attributes,
                        get_client=lambda: LANGFUSE),
    "langfuse.langchain": _module("langfuse.langchain", CallbackHandler=_Anything),
    "sentence_transformers": _module("sentence_transformers", CrossEncoder=_Anything),
    "langchain_core": _module("langchain_core"),
    "langchain_core.prompts": _module("langchain_core.prompts", ChatPromptTemplate=_Anything),
    "langchain_core.runnables": _module("langchain_core.runnables", RunnableLambda=_Anything),
    "langchain_core.output_parsers": _module("langchain_core.output_parsers", StrOutputParser=_Anything),
    "langgraph": _module("langgraph"),
    "langgraph.graph": _module("langgraph.graph", StateGraph=_Anything, END="__end__"),
    "bbot_web": _module("bbot_web", retrieve_web_documents=lambda *a, **k: []),
    "bbot_book": _module("bbot_book", retrieve_pages=lambda *a, **k: []),
    "bbot_video": _module("bbot_video", retrieve_video_segments=lambda *a, **k: []),
    "moderation": _module("moderation", is_safe_input=lambda *a, **k: (True, ""),
                          check_document_sufficiency=lambda *a, **k: True),
    "redis_cache": None,     # None → import 시 ImportError → 캐시 끔
    "eval_queue": None,
    "scripture_strip": None,
}

with mock.patch.dict(sys.modules, _STUBS):
    sys.modules.pop("bbot_graph", None)
    sys.modules.pop("utils", None)
    import bbot_graph as bg


# ==================== 가짜 LLM ====================

class MockAnswerLLM:
    """어떤 질문이 와도 정해 둔 answer를 돌려주는 답변 LLM (교수님 예시의 func A').
    stream=True면 answer를 1~4글자씩 임의로 잘라 보낸다 (seed로 재현 가능)."""

    def __init__(self, answer: str, seed: int = 0):
        self.answer, self.seed = answer, seed
        self.calls: list[dict] = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            return self._stream()
        return NS(choices=[NS(message=NS(content=self.answer))])

    def _stream(self):
        rnd = random.Random(self.seed)
        i = 0
        yield NS(choices=[])                        # usage 청크처럼 choices가 빈 청크
        while i < len(self.answer):
            n = rnd.randint(1, 4)
            yield NS(choices=[NS(delta=NS(content=self.answer[i:i + n]))])
            i += n


class MockJudge:
    """맥락·주소 판정 LLM 대신. 모든 구절에 같은 판정을 내리거나, verdict="error"면 예외를 낸다."""

    def __init__(self, verdict: str):
        self.verdict = verdict
        self.calls = 0

    def __call__(self, text, citations):
        self.calls += 1
        if self.verdict == "error":
            raise RuntimeError("판정 LLM 오류 (mock)")
        return [{"id": c.id, "verdict": self.verdict, "suggested_ref": None, "reason": "mock"}
                for c in citations], []


class _SyncThread:
    """generate()의 shadow 판정 스레드를 바로 실행해 결과를 확정적으로 만든다"""

    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


# ==================== 실행 도우미 ====================

QUESTION = "하나님은 세상을 어떻게 창조하셨나요?"


@pytest.fixture
def pipeline(monkeypatch):
    """bbot_graph의 바깥 의존성(검색·가드레일·캐시)을 정해진 값으로 고정하고, LLM만 바꿔 끼운다."""
    state = NS(safe=(True, ""), cached=None, graph=None)

    def run_graph(question, resolved_question, recent_turns):
        return state.graph or {
            "final_messages": [{"role": "user", "content": question}],
            "reranked_documents": [], "sources": {},
        }

    monkeypatch.setattr(bg, "is_safe_input", lambda q, t=None: state.safe)
    monkeypatch.setattr(bg, "lookup_answer_cache",
                        lambda q, n, u: ("exact", state.cached) if state.cached else (None, None))
    monkeypatch.setattr(bg, "persist_answer_cache", lambda *a, **k: False)
    monkeypatch.setattr(bg, "enqueue_answer_eval", lambda *a, **k: None)
    monkeypatch.setattr(bg, "_run_graph", run_graph)
    monkeypatch.setattr(bg.threading, "Thread", _SyncThread)
    monkeypatch.setattr(bg, "reasoning_kwargs", lambda: {})   # 호출 시점에 config를 import하므로

    def configure(answer: str, seed: int = 0, judge_mode: str = "off", judge=None):
        llm = MockAnswerLLM(answer, seed)
        monkeypatch.setattr(bg, "client", llm)
        monkeypatch.setattr(bg, "VERSE_JUDGE_MODE", judge_mode)
        monkeypatch.setattr(bg, "_verse_judge", judge)
        monkeypatch.setattr(bg, "_filter_judge", judge if judge_mode == "apply" else None)
        return llm

    state.configure = configure
    return state


def run_generate() -> str:
    answer, _sources, _resolved = bg.generate(QUESTION, use_cache=True)
    return answer


def run_stream() -> str:
    """SSE를 사용자 화면에 보이는 텍스트로 되돌린다 ([RESOLVED] 제외, [DONE]까지).
    [DONE] 뒤의 캐시 저장·shadow 판정도 실행되도록 서버처럼 끝까지 소비한다."""
    out, done = [], False
    for event in bg.generate_stream(QUESTION, use_cache=True):
        assert event.startswith("data: ") and event.endswith("\n\n"), event
        body = event[len("data: "):-2]
        if done or body.startswith("[RESOLVED]"):
            continue
        if body == "[DONE]":
            done = True
            continue
        out.append(body.replace("\\n", "\n"))
    assert done, "[DONE] 이벤트 없음"
    return "".join(out)


# ==================== 케이스 실행 ====================

CASES = build_cases()
PARAMS = [
    pytest.param(c, id=c.id, marks=[pytest.mark.xfail(strict=True, reason=c.todo)] if c.todo else [])
    for c in CASES
]


def _fail(case, msg: str, out: str | None = None):
    detail = f"\n  입력: {case.answer!r}" + (f"\n  출력: {out!r}" if out is not None else "")
    pytest.fail(f"[{case.id}] {case.note} — {msg}{detail}", pytrace=False)


@pytest.mark.parametrize("case", PARAMS)
def test_case(pipeline, monkeypatch, case):
    monkeypatch.setattr(bv, "VERSE_CONTEXT_ACTION", case.context_action)
    if case.path == "cache":
        pipeline.cached = {"answer": case.answer, "sources": {}}
    elif case.path == "blocked":
        pipeline.safe = (False, case.block_reason)
    elif case.path == "fallback":
        pipeline.graph = {"fallback_message": case.answer}
    llm_answer = case.answer if case.path == "llm" else "쓰이면 안 되는 답변"

    runs = [("일반 응답", run_generate, 0)] + [(f"스트리밍(seed {s})", run_stream, s) for s in STREAM_SEEDS]
    outputs, statuses = [], None
    for name, run, seed in runs:
        LANGFUSE.updates.clear()
        judge = MockJudge(case.judge) if case.judge else None
        llm = pipeline.configure(llm_answer, seed=seed, judge_mode=case.judge_mode, judge=judge)
        out = run()
        outputs.append(out)

        expected_calls = 1 if case.path == "llm" else 0
        if len(llm.calls) != expected_calls:
            _fail(case, f"{name}: 답변 LLM 호출 {len(llm.calls)}번 (기대 {expected_calls}번)", out)
        if case.judge_called is not None and judge is not None and (judge.calls > 0) != case.judge_called:
            _fail(case, f"{name}: 판정 LLM 호출 {judge.calls}번 (기대: {'호출' if case.judge_called else '호출 안 함'})", out)
        if case.shadow_status is not None:
            shadow = LANGFUSE.shadow_result() or {}
            if shadow.get("status") != case.shadow_status:
                _fail(case, f"{name}: shadow 기록 status={shadow.get('status')} (기대 {case.shadow_status})", out)
            for k, v in case.shadow_counts.items():
                if shadow.get("counts", {}).get(k) != v:
                    _fail(case, f"{name}: shadow 판정 {k} {shadow.get('counts', {}).get(k)}개 (기대 {v}개)", out)
        if name == "일반 응답" and case.statuses is not None:
            md = LANGFUSE.metadata_for("rag") or {}
            statuses = [x["status"] for x in md.get("verse_check", {}).get("code", [])]

    whole = outputs[0]
    for (name, _, _), out in zip(runs[1:], outputs[1:]):
        if out != whole:
            _fail(case, f"{name} 결과가 일반 응답과 다름\n  일반: {whole!r}", out)

    expected_exact = case.exact
    if case.path == "blocked":
        expected_exact = bg.get_block_message(case.block_reason)
    if expected_exact is not None and whole != expected_exact:
        _fail(case, f"출력이 기대와 다름\n  기대: {expected_exact!r}", whole)
    for s in case.must:
        if s not in whole:
            _fail(case, f"있어야 할 글자가 없음: {s!r}", whole)
    for s in case.must_not:
        if s in whole:
            _fail(case, f"없어야 할 글자가 남아 있음: {s!r}", whole)
    for s, n in case.counts.items():
        if whole.count(s) != n:
            _fail(case, f"{s!r}가 {whole.count(s)}번 나옴 (기대 {n}번)", whole)
    if case.statuses is not None and statuses != case.statuses:
        _fail(case, f"구절별 처리 결과 {statuses} (기대 {case.statuses})", whole)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
