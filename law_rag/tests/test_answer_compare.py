"""인용 추출, 세 방식 답변(가짜 LLM), 비교 채점 테스트."""
import json
from types import SimpleNamespace as NS

import pytest

import answer
import compare
import config


@pytest.fixture(autouse=True)
def reset_client():
    yield
    answer.set_client(None)


# ---------- 인용 추출 ----------

def test_extract_citations():
    names = ["도로교통법 시행령", "도로교통법", "주택임대차보호법"]
    text = "근거 조문: 도로교통법 제44조, 제148조의 2, 도로교통법 시행령 제3조, 주택임대차보호법 제3조의2"
    assert compare.extract_citations(text, names) == [
        "도로교통법|44", "도로교통법|148의2", "도로교통법 시행령|3", "주택임대차보호법|3의2"]
    assert compare.extract_citations("도로교통법 제148의2조, 제44조 제4항", names) == [
        "도로교통법|148의2", "도로교통법|44"]                      # '제N의M조' 표기, 항은 무시
    assert compare.extract_citations("제5조에 따르면", names) == []   # 법령명 없으면 무시


# ---------- 세 방식 (가짜 LLM) ----------

class FakeLLM:
    """툴이 있으면 첫 턴에 get_article(44)를 부르고, 그다음엔 답한다.
    툴이 없으면: 참고 조문이 있으면 제44조, 없으면 틀린 제999조를 인용."""

    def __init__(self):
        self.chat = NS(completions=NS(create=self.create))

    def create(self, model, messages, tools=None, tool_choice=None, **kw):
        used_tool = any(m["role"] == "tool" for m in messages)
        if tools and not used_tool:
            tc = NS(id="c1", function=NS(name="get_article",
                                         arguments=json.dumps({"law_name": "도로교통법", "article_no": "44"})))
            msg = NS(content=None, tool_calls=[tc])
        elif used_tool or "[참고 조문]" in messages[-1]["content"]:
            msg = NS(content="0.03% 이상입니다.\n근거 조문: 도로교통법 제44조", tool_calls=None)
        else:
            msg = NS(content="0.05% 이상입니다.\n근거 조문: 도로교통법 제999조", tool_calls=None)
        return NS(choices=[NS(message=msg)])


def test_three_modes_and_compare(env):
    answer.set_client(FakeLLM())
    q = [{"id": "T01", "domain": "traffic", "question": "음주운전 혈중알코올농도 기준은?",
          "gold": "도로교통법 제44조"}]
    rows = compare.run(q, list(answer.MODES))
    r = rows[0]
    assert (r["no_rag_correct"], r["no_rag_fake"]) == ("X", 1)      # 지어낸 조문 잡힘
    assert (r["always_rag_correct"], r["always_rag_hit"]) == ("O", "O")
    assert (r["tool_rag_correct"], r["tool_rag_tools"]) == ("O", 1)
    md = compare.summary_md(rows, list(answer.MODES))
    assert "| no_rag | 0/1 | 1건 | - |" in md


def test_tool_rounds_exhausted(env, monkeypatch):
    """LLM이 툴만 계속 부르면 라운드 소진 후 툴 없이 한 번 더 불러 답을 받는다."""
    class Loop(FakeLLM):
        def create(self, model, messages, tools=None, tool_choice=None, **kw):
            if tools:
                tc = NS(id="c", function=NS(name="search_law", arguments='{"query": "음주"}'))
                return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))])
            return NS(choices=[NS(message=NS(content="최종 답", tool_calls=None))])
    monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 2)
    answer.set_client(Loop())
    r = answer.tool_rag("음주운전", "traffic")
    assert r.answer == "최종 답" and len(r.tool_calls) == 2
