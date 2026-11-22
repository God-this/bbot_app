"""수집(파싱)과 검색 테스트."""
import collect
import retriever
from conftest import FAKE_LAW


# ---------- 파싱 ----------

def test_parse_law():
    chunks = collect.parse_law(FAKE_LAW, "traffic")
    nos = [c["article_no"] for c in chunks]
    assert nos == ["5", "44", "44의2"]          # 장 제목·삭제 조문은 빠짐, 가지번호 반영
    c44 = chunks[1]
    assert "0.03퍼센트" in c44["text"] and c44["law_type"] == "법률"
    assert "가. 목" in chunks[2]["text"]         # dict로 온 항, 목까지 읽음
    assert chunks[0]["id"] == "도로교통법|5|0"


def test_long_article_split():
    hangs = [{"항내용": f"{i} " + "가" * 600} for i in range(5)]
    law = {"법령": {"기본정보": {"법령명_한글": "긴법"}, "조문": {"조문단위": [
        {"조문여부": "조문", "조문번호": "1", "조문내용": "제1조(목적)", "항": hangs}]}}}
    chunks = collect.parse_law(law, "x")
    assert len(chunks) > 1 and all(c["text"].startswith("제1조(목적)") for c in chunks)


# ---------- 검색 ----------

def test_search_and_get(env):
    hits = retriever.search("술에 취한 상태 혈중알코올농도 기준", "traffic", k=2)
    assert hits[0]["article_no"] == "44"
    assert retriever.search("신호", "다른분야") == []
    assert retriever.get_article("도로교통법", "제44조의2")["article_no"] == "44의2"
    assert retriever.get_article("도로교통법", "999") is None
