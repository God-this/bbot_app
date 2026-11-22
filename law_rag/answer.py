"""3단계: 답변 생성 세 방식.

- no_rag     : 검색 없이 LLM 기억으로만 답변
- always_rag : 질문마다 무조건 검색해 조문 top-k를 프롬프트에 넣고 답변
- tool_rag   : LLM에 search_law / get_article 툴을 주고, 필요할 때 스스로 부르게 함

세 방식 모두 같은 시스템 규칙(근거 조문 표기)을 쓰고 차이는 '검색을 언제 하느냐'뿐이다.
"""
import json
import time
from dataclasses import dataclass, field

import config
import retriever

SYSTEM = """당신은 한국 법령 상담 도우미입니다.
- 질문에 한국어로 간결하게 답하세요.
- 답변의 근거가 된 조문을 마지막 줄에 다음 형식으로 적으세요.
  근거 조문: 도로교통법 제44조, 주택임대차보호법 제3조의2
- 확실하지 않으면 모른다고 답하세요."""

RAG_RULE = "\n- 아래 [참고 조문]만 근거로 답하세요. 참고 조문에 없는 내용은 지어내지 마세요."
TOOL_RULE = ("\n- 법령 내용이 필요하면 반드시 툴로 조문을 확인한 뒤 답하세요. "
             "조 번호를 알면 get_article, 모르면 search_law를 쓰세요.")

TOOLS = [
    {"type": "function", "function": {
        "name": "search_law",
        "description": "질문과 관련된 법령 조문을 의미 검색으로 찾는다. 조 번호를 모를 때 사용.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "검색할 내용 (자연어)"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_article",
        "description": "법령 이름과 조 번호로 조문 원문을 정확히 가져온다.",
        "parameters": {"type": "object", "properties": {
            "law_name": {"type": "string", "description": "정식 법령명. 예: 도로교통법"},
            "article_no": {"type": "string", "description": "조 번호. 예: 44, 44의2"},
        }, "required": ["law_name", "article_no"]}}},
]


@dataclass
class Result:
    mode: str
    answer: str
    retrieved: list[str] = field(default_factory=list)   # 'law|조번호' (검색·조회로 본 조문)
    tool_calls: list[dict] = field(default_factory=list)
    seconds: float = 0.0


_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY or None)
    return _client


def set_client(c) -> None:
    """테스트에서 가짜 LLM으로 바꿀 때 사용."""
    global _client
    _client = c


def _chat(messages, tools=None):
    kw = {"model": config.LLM_MODEL, "messages": messages}
    # gpt-5 계열(추론 모델)은 temperature를 바꾸면 오류가 나서 그 외 모델만 0으로 고정
    if not config.LLM_MODEL.startswith(("gpt-5", "o1", "o3", "o4")):
        kw["temperature"] = 0
    if tools:
        kw.update(tools=tools, tool_choice="auto")
    return get_client().chat.completions.create(**kw).choices[0].message


def _key(h: dict) -> str:
    return f"{h['law_name']}|{h['article_no']}"


def no_rag(question: str, domain: str | None = None) -> Result:
    t = time.time()
    msg = _chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}])
    return Result("no_rag", msg.content or "", seconds=time.time() - t)


def always_rag(question: str, domain: str | None = None) -> Result:
    t = time.time()
    hits = retriever.search(question, domain)
    user = f"[참고 조문]\n{retriever.format_hits(hits)}\n\n[질문]\n{question}"
    msg = _chat([{"role": "system", "content": SYSTEM + RAG_RULE}, {"role": "user", "content": user}])
    return Result("always_rag", msg.content or "", retrieved=[_key(h) for h in hits],
                  seconds=time.time() - t)


def _run_tool(name: str, args: dict, domain: str | None) -> tuple[str, list[str]]:
    if name == "search_law":
        hits = retriever.search(args.get("query", ""), domain)
        return retriever.format_hits(hits) or "검색 결과 없음", [_key(h) for h in hits]
    if name == "get_article":
        a = retriever.get_article(args.get("law_name", ""), args.get("article_no", ""))
        if not a:
            return "해당 조문이 DB에 없습니다. 법령명·조 번호를 확인하거나 search_law를 쓰세요.", []
        return retriever.format_hits([a]), [_key(a)]
    return f"알 수 없는 툴: {name}", []


def tool_rag(question: str, domain: str | None = None) -> Result:
    t = time.time()
    messages = [{"role": "system", "content": SYSTEM + TOOL_RULE},
                {"role": "user", "content": question}]
    res = Result("tool_rag", "")
    for _ in range(config.MAX_TOOL_ROUNDS):
        msg = _chat(messages, tools=TOOLS)
        if not msg.tool_calls:
            res.answer = msg.content or ""
            break
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            out, keys = _run_tool(tc.function.name, args, domain)
            res.tool_calls.append({"name": tc.function.name, "args": args})
            res.retrieved += [k for k in keys if k not in res.retrieved]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
    else:
        # 라운드를 다 쓰면 툴 없이 한 번 더 불러 답변을 받는다
        res.answer = _chat(messages).content or ""
    res.seconds = time.time() - t
    return res


MODES = {"no_rag": no_rag, "always_rag": always_rag, "tool_rag": tool_rag}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "음주운전 기준이 되는 혈중알코올농도는?"
    for name, fn in MODES.items():
        r = fn(q)
        print(f"\n===== {name} ({r.seconds:.1f}초) =====\n{r.answer}")
        if r.retrieved:
            print("본 조문:", ", ".join(r.retrieved))
        if r.tool_calls:
            print("툴 호출:", r.tool_calls)
