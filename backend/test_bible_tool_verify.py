"""bible_tool_verify (tool 방식) 테스트 — 실제 LLM 대신 가짜 클라이언트로 흐름을 검증한다.

    python test_bible_tool_verify.py
"""
import os
os.environ.setdefault("BIBLE_SOURCE", "file")   # DB 없이 bible.txt로 테스트 (BIBLE_SOURCE=db로 DB 테스트)

import json
import random
from types import SimpleNamespace as NS

import bible_verify
from bible_verify import VerseStreamFilter, verify_answer, APPENDIX_HEADER, REF_RE, parse_ref
from bible_tool_verify import get_bible_verses, make_llm_verifier, EMPTY_MARK


class FakeClient:
    """1라운드: 검증할 부분의 구절마다 도구 호출 / 2라운드: answer_fn(segment, 도구결과)을 답으로."""

    def __init__(self, answer_fn, fail=False):
        self.answer_fn, self.fail, self.calls = answer_fn, fail, []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("LLM 서버 오류")
        msgs = kw["messages"]
        segment = msgs[1]["content"].split("[검증할 부분]\n", 1)[1]
        if msgs[-1]["role"] != "tool":
            calls = []
            for i, m in enumerate(REF_RE.finditer(segment)):
                r = parse_ref(m)
                args = {"book": r.name, "chapter": r.chapter}
                if r.v1:
                    args.update(verse_start=r.v1, verse_end=r.v2)
                calls.append(NS(id=f"c{i}", function=NS(name="get_bible_verses", arguments=json.dumps(args, ensure_ascii=False))))
            if calls:
                return NS(choices=[NS(message=NS(content="", tool_calls=calls))])
        results = [json.loads(m["content"]) for m in msgs if m["role"] == "tool"]
        return NS(choices=[NS(message=NS(content=self.answer_fn(segment, results), tool_calls=None))])


def run(text, client, seed=None):
    vf = VerseStreamFilter(mode="tool", llm=make_llm_verifier(client, "fake"))
    if seed is None:
        pieces = [text]
    else:
        rnd, pieces, i = random.Random(seed), [], 0
        while i < len(text):
            n = rnd.randint(1, 4)
            pieces.append(text[i:i + n]); i += n
    streamed = [vf.feed(p) for p in pieces]
    tail = vf.finish()
    return "".join(streamed), tail, vf


GOOD = '"하나님이 세상을 이처럼 사랑하사 독생자를 주셨으니" (요한복음 3:16, 개역한글)'


def test_tool_function():
    assert get_bible_verses("요한복음", 3, 16)["verses"][0]["text"].startswith("하나님이 세상을")
    assert "error" in get_bible_verses("창세기", 51)
    assert "error" in get_bible_verses("창세기", 1, 40)
    assert get_bible_verses("시편", 23)["verse_count"] == 6
    assert get_bible_verses("요", 3, 16)["reference"] == "요한복음 3:16"


def test_no_verse_no_llm_call():
    c = FakeClient(lambda s, r: s)
    text = "생명은 우연히 생기지 않습니다. 창세기 1장이 이를 말합니다."
    streamed, tail, vf = run(text, c)
    assert c.calls == [] and streamed + tail == text
    assert vf.summary()["tool_status"] == "not_called"


def test_prefix_streams_before_hold_and_llm_sees_context():
    seen = {}
    def answer(seg, results):
        seen["seg"], seen["results"] = seg, results
        return seg
    c = FakeClient(answer)
    text = "하나님은 사랑이십니다. " + GOOD + " 아멘."
    streamed, tail, vf = run(text, c, seed=3)
    assert streamed == "하나님은 사랑이십니다."          # 구절 전까지는 바로 나감
    assert seen["seg"].strip().startswith('"하나님이 세상을') and seen["seg"].endswith("아멘.")
    assert "하나님은 사랑이십니다." in c.calls[0]["messages"][1]["content"]   # 앞부분을 맥락으로 받음
    assert c.calls[0]["tool_choice"] == "required"
    assert streamed + tail == text and vf.summary()["tool_status"] == "ok"


def test_llm_fixes_quote():
    def answer(seg, results):
        orig = results[0]["verses"][0]["text"]
        return seg.replace("하늘과 땅을 만드셨다", orig)
    c = FakeClient(answer)
    out = "".join(run('마지막으로 "태초에 하나님께서 하늘과 땅을 만드셨다" (창세기 1:1)', c)[:2])
    assert "태초에 하나님이 천지를 창조하시니라" in out


def test_safety_net_catches_llm_miss():
    c = FakeClient(lambda s, r: s)                     # LLM이 아무것도 안 고침
    text = '끝으로 "없는 말씀" (창세기 51:3) 을 기억합시다.'
    streamed, tail, vf = run(text, c)
    assert "없는 말씀" not in streamed + tail           # 안전장치(code)가 지움
    assert any(r["status"] == "missing" for r in vf.report)


def test_llm_error_falls_back_to_code():
    text = "요한복음 3:16에서 말하듯, " + '"엉터리" (창세기 1:1)'
    out_tool = "".join(run(text, FakeClient(None, fail=True))[:2])
    out_code, _ = verify_answer(text, mode="code")
    assert out_tool == out_code


def test_empty_mark():
    c = FakeClient(lambda s, r: EMPTY_MARK)
    streamed, tail, _ = run("설명입니다." + ' "없는 말씀" (창세기 51:3)', c)
    assert streamed + tail == "설명입니다."


def test_chapter_only_not_held():
    c = FakeClient(lambda s, r: s)
    text = "창세기 1장의 하루는 24시간입니다. 출애굽기 20:11도 같습니다."
    streamed, tail, _ = run(text, c, seed=1)
    assert streamed.startswith("창세기 1장의 하루는 24시간입니다.")
    assert len(c.calls) == 2                           # 도구 호출 1번 + 최종 답 1번


def test_chunking_invariance():
    text = "서론입니다. 요한복음 3:16 말씀처럼. " + GOOD + "\n\n결론."
    base = None
    for seed in range(20):
        streamed, tail, _ = run(text, FakeClient(lambda s, r: s), seed=seed)
        base = base or streamed + tail
        assert streamed + tail == base


def test_appendix_in_tool_mode():
    out = "".join(run("로마서 8:28 말씀을 기억하세요.", FakeClient(lambda s, r: s))[:2])
    assert APPENDIX_HEADER in out and "로마서 8:28 — 우리가 알거니와" in out


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
