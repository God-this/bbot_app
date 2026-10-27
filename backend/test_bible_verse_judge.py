"""맥락·주소 판정 테스트 — 실제 LLM 대신 가짜 클라이언트로 흐름을 검증한다.

    python test_bible_verse_judge.py
"""
import os
os.environ.setdefault("BIBLE_SOURCE", "file")   # DB 없이 bible.txt로 테스트

import json
import random
from types import SimpleNamespace as NS

from bible_verify import (
    VerseStreamFilter, find_citations, apply_verdicts, best_matching_span, verify_answer, APPENDIX_HEADER,
)
from bible_verse_judge import search_bible, judge_citations, make_judge, run_shadow

SAMPLE = ('서론입니다. 요한복음 3:16에서 말하듯 사랑하십니다. '
          '끝으로 "하나님이 보시기에 좋았더라" (창세기 1:31, 개역한글) 아멘. '
          '방주에는 "모든 육체의 호흡이 있는 것"(창세기 6:17)을 태웠습니다.')


class FakeJudgeClient:
    """1라운드: tool_calls(있으면) / 2라운드: verdicts JSON"""

    def __init__(self, verdicts, tool_calls=None, raw=None, fail=False):
        self.verdicts, self.tool_calls, self.raw, self.fail = verdicts, tool_calls or [], raw, fail
        self.calls = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("LLM 서버 오류")
        if self.tool_calls and kw["messages"][-1]["role"] != "tool":
            calls = [NS(id=f"c{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                     for i, (n, a) in enumerate(self.tool_calls)]
            return NS(choices=[NS(message=NS(content="", tool_calls=calls))])
        content = self.raw if self.raw is not None else json.dumps({"verdicts": self.verdicts}, ensure_ascii=False)
        return NS(choices=[NS(message=NS(content=content, tool_calls=None))])


def ids_by_ref(cits):
    return {c.ref.label: c.id for c in cits}


# ---------- 1·2단계: 검출·표시 (코드) ----------

def test_find_citations_spans_and_labels():
    cits = find_citations(SAMPLE)
    assert [c.kind for c in cits] == ["inline", "quoted", "quoted"]
    q = cits[1]
    assert SAMPLE[q.ref_start:q.ref_end] == "창세기 1:31"
    assert SAMPLE[q.quote_start:q.quote_end] == "하나님이 보시기에 좋았더라"
    assert q.exists and q.quote_match is False and "심히 좋았더라" in q.original
    assert cits[0].quote_match is None and "요한복음 3:16" in cits[0].context


def test_find_citations_does_not_change_text_and_matches_code_detection():
    text = SAMPLE + " (창세기 51:1; 로마서 8:28) 창세기 5장과 시편 23편 1절."
    cits = find_citations(text)
    _, report = verify_answer(text)
    assert len(cits) == len(report)                       # code 방식과 같은 구절을 찾는다
    missing = [c for c in cits if not c.exists]
    assert [c.ref.label for c in missing] == ["창세기 51:1"]


def test_best_matching_span():
    orig = "하나님이 뭍을 땅이라 칭하시고 모인 물을 바다라 칭하시니라 하나님의 보시기에 좋았더라"
    assert best_matching_span("하나님이 보시기에 좋았더라", orig) == "하나님의 보시기에 좋았더라"
    assert best_matching_span("전혀 다른 문장입니다", orig) is None


# ---------- 4단계: 수정 (코드) ----------

def test_apply_wrong_ref_accepted_when_quote_fits():
    cits = find_citations(SAMPLE)
    v = [{"id": ids_by_ref(cits)["창세기 1:31"], "verdict": "wrong_ref", "suggested_ref": "창세기 1:10"}]
    new, log = apply_verdicts(SAMPLE, cits, v)
    assert '"하나님의 보시기에 좋았더라" (창세기 1:10, 개역한글)' in new
    assert verify_answer(new)[0].split(APPENDIX_HEADER)[0].count("창세기 1:10") == 1   # code 검증도 통과
    assert any(e["applied"] == "ref→창세기 1:10" for e in log)


def test_apply_wrong_ref_rejected_when_quote_differs_or_ref_missing():
    cits = find_citations(SAMPLE)
    i = ids_by_ref(cits)["창세기 1:31"]
    for sug in ("요한복음 3:16", "창세기 51:1", "창세기 1:1-10"):
        new, log = apply_verdicts(SAMPLE, cits, [{"id": i, "verdict": "wrong_ref", "suggested_ref": sug}])
        assert new == SAMPLE and log[1]["applied"].startswith("rejected"), (sug, log)


def test_apply_context_mismatch_log_vs_remove():
    cits = find_citations(SAMPLE)
    v = [{"id": ids_by_ref(cits)["창세기 6:17"], "verdict": "context_mismatch", "reason": "멸절 내용"}]
    same, _ = apply_verdicts(SAMPLE, cits, v, context_action="log")
    assert same == SAMPLE
    removed, _ = apply_verdicts(SAMPLE, cits, v, context_action="remove")
    assert "모든 육체의 호흡" not in removed and "창세기 6:17" not in removed


def test_apply_ignores_missing_and_quote_wrong_for_code():
    text = '"없는 말씀" (창세기 51:3) 그리고 "하나님이 보시기에 좋았더라" (창세기 1:31)'
    cits = find_citations(text)
    v = [{"id": c.id, "verdict": "quote_wrong"} for c in cits]
    new, log = apply_verdicts(text, cits, v)
    assert new == text                                       # 코드 검증에 맡긴다
    assert log[0]["applied"] == "code(missing)"


# ---------- 3단계: 판정 (LLM) ----------

def test_search_bible_file():
    r = search_bible("보시기에 좋았더라", book="창세기")
    refs = [x["reference"] for x in r["results"]]
    assert {"창세기 1:4", "창세기 1:10", "창세기 1:31"} <= set(refs)   # 두 단어가 모두 들어간 구절
    assert "error" in search_bible("")


def test_judge_parses_and_filters_verdicts():
    cits = find_citations(SAMPLE)
    c = FakeJudgeClient(
        [{"id": 1, "verdict": "ok"}, {"id": 2, "verdict": "wrong_ref", "suggested_ref": "창세기 1:10"},
         {"id": 3, "verdict": "엉뚱한값"}, {"id": 99, "verdict": "ok"}],
        tool_calls=[("search_bible", {"keyword": "보시기에 좋았더라"})],
    )
    verdicts, log = judge_citations(c, "fake", SAMPLE, cits)
    assert [v["id"] for v in verdicts] == [1, 2]                 # 잘못된 값·없는 id는 버림
    assert log[0]["tool"] == "search_bible" and log[0]["result"].endswith("건")
    assert "[인용 2]" in c.calls[0]["messages"][1]["content"]
    assert "원문(개역한글)" in c.calls[0]["messages"][1]["content"]


def test_judge_invalid_json_raises():
    cits = find_citations(SAMPLE)
    try:
        judge_citations(FakeJudgeClient([], raw="판정할 수 없습니다"), "fake", SAMPLE, cits)
        assert False, "예외가 나야 함"
    except ValueError:
        pass


# ---------- apply 모드 (스트리밍) ----------

def stream_with_judge(text, client, seed=None):
    vf = VerseStreamFilter(mode="code", judge=make_judge(client, "fake"))
    pieces = [text]
    if seed is not None:
        rnd, pieces, i = random.Random(seed), [], 0
        while i < len(text):
            n = rnd.randint(1, 4)
            pieces.append(text[i:i + n]); i += n
    streamed = "".join(vf.feed(p) for p in pieces)
    return streamed, vf.finish(), vf


def test_apply_mode_holds_from_first_verse_and_applies():
    def verdicts_for(text):
        cits = find_citations(text)
        return [{"id": ids_by_ref(cits)["창세기 1:31"], "verdict": "wrong_ref", "suggested_ref": "창세기 1:10"}]
    c = FakeJudgeClient(verdicts_for(SAMPLE))
    streamed, tail, vf = stream_with_judge(SAMPLE, c, seed=2)
    assert streamed.strip() == "서론입니다."                      # 첫 절 단위 구절 전까지는 바로 나감
    out = streamed + tail
    assert "(창세기 1:10, 개역한글)" in out
    assert len([m for m in c.calls]) == 1
    s = vf.summary()["judge"]
    assert s["status"] == "ok" and s["verdicts"][1]["applied"] == "ref→창세기 1:10"


def test_apply_mode_chunk_invariance():
    base = None
    for seed in range(15):
        c = FakeJudgeClient([{"id": 2, "verdict": "wrong_ref", "suggested_ref": "창세기 1:10"}])
        s, t, _ = stream_with_judge(SAMPLE, c, seed=seed)
        base = base or s + t
        assert s + t == base


def test_apply_mode_judge_error_equals_code():
    s, t, vf = stream_with_judge(SAMPLE, FakeJudgeClient([], fail=True))
    assert s + t == verify_answer(SAMPLE)[0]
    assert vf.summary()["judge"]["status"] == "error"


def test_apply_mode_no_verse_no_call():
    c = FakeJudgeClient([])
    s, t, vf = stream_with_judge("창세기 1장의 하루는 24시간입니다.", c)
    assert c.calls == [] and vf.summary()["judge"]["status"] == "not_called"


# ---------- shadow 모드 ----------

def test_run_shadow():
    c = FakeJudgeClient([{"id": 2, "verdict": "wrong_ref", "suggested_ref": "창세기 1:10"},
                         {"id": 3, "verdict": "context_mismatch", "reason": "멸절"}])
    r = run_shadow(SAMPLE, make_judge(c, "fake"))
    assert r["status"] == "ok" and r["would_change"] is True
    assert r["counts"]["wrong_ref"] == 1 and r["counts"]["context_mismatch"] == 1
    assert "(창세기 1:10, 개역한글)" in r["would_be_answer"]
    assert run_shadow("구절 없는 답변", make_judge(c, "fake"))["status"] == "no_citations"
    assert run_shadow(SAMPLE, make_judge(FakeJudgeClient([], fail=True), "fake"))["status"] == "error"


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
