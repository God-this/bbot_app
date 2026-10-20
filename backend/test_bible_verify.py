"""bible_verify 단위 테스트 — python -m pytest test_bible_verify.py (또는 python test_bible_verify.py)"""
import os
os.environ.setdefault("BIBLE_SOURCE", "file")   # DB 없이 bible.txt로 테스트 (BIBLE_SOURCE=db로 DB 테스트)

import random
from bible_verify import VerseStreamFilter, verify_answer, reverify_cached, APPENDIX_HEADER

GEN11 = "태초에 하나님이 천지를 창조하시니라"

def stream(text, seed=0):
    """토큰이 임의로 쪼개져 들어오는 상황을 흉내낸다"""
    rnd = random.Random(seed)
    vf = VerseStreamFilter()
    out, i = [], 0
    while i < len(text):
        n = rnd.randint(1, 4)
        out.append(vf.feed(text[i:i+n])); i += n
    out.append(vf.finish())
    return "".join(out), vf.report

def check(text, expect_contains=(), expect_absent=(), statuses=None):
    whole, rep = verify_answer(text)
    for seed in range(30):
        s, _ = stream(text, seed)
        assert s == whole, f"seed {seed}: 스트리밍 결과가 다름\n{s!r}\n{whole!r}"
    for c in expect_contains: assert c in whole, (c, whole)
    for c in expect_absent: assert c not in whole, (c, whole)
    if statuses is not None:
        assert [r["status"] for r in rep] == statuses, rep
    return whole

def test_plain_text_untouched():
    t = "사람은 하나님의 형상대로 지음받았습니다. 이는 \"지적 설계\"의 증거입니다 (약 3배)."
    assert check(t, statuses=[]) == t

def test_correct_quote_kept():
    t = f'마무리 말씀입니다. "{GEN11}" (창세기 1:1, 개역한글)'
    assert check(t, statuses=["ok"]) == t   # 원문에 보였으니 참고 구절 없음

def test_wrong_quote_replaced():
    t = '"태초에 하나님께서 하늘과 땅을 만드셨다" (창세기 1:1, 개역한글)'
    check(t, expect_contains=[GEN11], expect_absent=["만드셨다"], statuses=["replaced"])

def test_missing_quoted_removed():
    t = '끝으로 "없는 말씀" (창세기 51:3) 을 기억합시다.'
    check(t, expect_absent=["없는 말씀", "51"], statuses=["missing"])

def test_missing_inline_replaced():
    t = "창세기 51장 3절에서 말하듯 하나님은 창조주이십니다."
    out = check(t, statuses=["missing"])
    assert out.startswith("성경에서 말하듯"), out

def test_chapter_only():
    out = check("창세기 5장과 11장에 족보가 나옵니다.", statuses=["ok"])
    assert APPENDIX_HEADER not in out
    check("창세기 51장에 나옵니다.", expect_contains=["성경에 나옵니다"], statuses=["missing"])

def test_address_only_kept_and_appended():
    t = "요한복음 3:16에서 말하듯 하나님은 세상을 사랑하십니다."
    out = check(t, statuses=["ok"])
    assert out.startswith(t)
    assert APPENDIX_HEADER in out and "요한복음 3:16 — 하나님이 세상을 이처럼 사랑하사" in out

def test_korean_range_up_to_3_appended():
    out = check("창세기 1장 1-3절을 보면 빛이 창조됩니다.", statuses=["ok"])
    assert "창세기 1:1-3 — 태초에" in out

def test_long_range_not_appended():
    out = check("창세기 1:1-10을 읽어보세요.", statuses=["ok"])
    assert APPENDIX_HEADER not in out

def test_long_range_wrong_quote_dropped():
    t = '"엉터리 본문" (창세기 1:1-10)'
    out = check(t, statuses=["quote_dropped"])
    assert out == "(창세기 1:1-10)"

def test_paren_citation():
    out = check("하나님이 사람을 지으셨습니다(창세기 1:27, 개역한글).", statuses=["ok"])
    assert "창세기 1:27 —" in out
    out = check("하나님이 사람을 지으셨습니다 (창세기 1:99).", statuses=["missing"])
    assert out == "하나님이 사람을 지으셨습니다.", out

def test_not_a_book_word():
    t = "요한은 이사를 갔고 시간이 흘러 마가 끼었습니다. 약 3:1 비율입니다."
    assert check(t, statuses=[]) == t

def test_quote_then_emphasis_paren():
    t = '"빅뱅"(대폭발) 이론은 한계가 있습니다.'
    assert check(t, statuses=[]) == t

def test_appendix_dedup_and_cap():
    t = "요한복음 3:16, 요한복음 3:16, 로마서 8:28, 창세기 1:1, 시편 23:1 참고."
    out = check(t)
    assert out.count("요한복음 3:16 —") == 1
    assert out.split(APPENDIX_HEADER)[1].count("\n- ") == 3

def test_psalm_pyeon():
    check("시편 23편은 위로를 줍니다.", statuses=["ok"])
    out = check("시편 23편 1절처럼 부족함이 없습니다.", statuses=["ok"])
    assert "시편 23:1 — 여호와는 나의 목자시니" in out
    check("시편 151편에서", expect_contains=["성경에서"], statuses=["missing"])

def test_appendix_skips_contained_range():
    out = check("창세기 6:19 말씀처럼 (창세기 6:19-20) 둘씩 들어갔습니다.")
    tail = out.split(APPENDIX_HEADER)[1]
    assert "창세기 6:19-20 —" in tail and "창세기 6:19 —" not in tail, tail

def test_reverify_cached_is_idempotent():
    raw = '로마서 8:28 말씀처럼. "엉터리" (창세기 1:1) 그리고 창세기 51장.'
    once = verify_answer(raw)[0]
    assert reverify_cached(raw) == once            # 검증 전 캐시 답변 → 검증됨
    assert reverify_cached(once) == once           # 이미 검증된 답변 → 그대로 (참고 구절 중복 없음)
    assert once.count(APPENDIX_HEADER) == 1

def test_unclosed_quote_flushes():
    t = '그는 "끝나지 않은 인용'
    assert check(t) == t

if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try: fn(); print("PASS", name)
            except AssertionError as e: fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
