import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Generator, List, Literal
from typing_extensions import TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sentence_transformers import CrossEncoder

from config import LLM_MODEL
from llm_factory import get_client
from bbot_web import retrieve_web_documents
from bbot_book import retrieve_pages
from bbot_video import retrieve_video_segments
from utils import detect_language, translate_to_english

import re

# ==================== Reranker ====================

_reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1") # 다국어 모델

try:
    from redis_cache import get_cached_answer, save_cached_answer
    from redis_semantic_cache import search_semantic_cache, save_semantic_cache
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


client = get_client()

# ==================== Cache Toggle ====================

USE_CACHE = False  # redis 모듈 없으면 자동 비활성화

# ==================== State ====================
class GraphState(TypedDict):
    question: str
    rewritten_question: str
    route: str
    documents: List[dict]
    judgement: str
    iteration: int
    chat_history: List[str]


# ==================== Utility ====================
def format_timedelta(seconds: int) -> str:
    td = timedelta(seconds=int(seconds))
    total = int(td.total_seconds())
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f"{h:02}:{m:02}:{s:02}"

def format_chat_history(history: List[str]) -> str:
    if not history:
        return "이전 대화 없음"
    return "\n".join(history)

def normalize_query(query: str) -> str:
    query = query.lower().strip()
    query = re.sub(r"[^\w\s가-힣]", "", query)
    query = re.sub(r"\s+", " ", query)
    return query

# ==================== Question Filter ====================
def is_creation_question(question: str) -> bool:
    res = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": f"""
다음 질문이 아래 중 하나라도 관련되면 true:

- 성경
- 창조
- 진화
- 생물 기원
- 노아의 홍수
(창조설계, 대홍수, 화석, 진화론, 기독교, 창조신앙, 천문학, 연대문제 등과 관련된 질문도 포함)

조금이라도 관련 있으면 true로 판단해.

질문:
{question}

true 또는 false만 출력.
"""
            }
        ],
        temperature=0
    )

    return "true" in res.choices[0].message.content.lower()

# ==================== Parallel Retrieval ====================
def deduplicate_docs(docs: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for doc in docs:
        key = doc.get("url") or doc.get("title", "") + str(doc.get("page", "")) + str(doc.get("start", ""))
        if key not in seen:
            seen.add(key)
            result.append(doc)
    return result

def retrieve_all_documents_parallel(queries: list[str], top_k: int = 5):

    futures = []
    with ThreadPoolExecutor(max_workers=9) as executor:
        for q in queries:
            futures.append(("web",   executor.submit(retrieve_web_documents, q, top_k)))
            futures.append(("book",  executor.submit(retrieve_pages, q, top_k)))
            futures.append(("video", executor.submit(retrieve_video_segments, q, top_k)))

        web_docs, book_docs, video_docs = [], [], []
        for kind, future in futures:
            docs = future.result() or []
            if kind == "web":
                web_docs.extend(docs)
            elif kind == "book":
                book_docs.extend(docs)
            elif kind == "video":
                video_docs.extend(docs)

    web_docs   = deduplicate_docs(web_docs)
    book_docs  = deduplicate_docs(book_docs)
    video_docs = deduplicate_docs(video_docs)

    print("✅ Parallel search completed\n")

    return {
        "web_docs": web_docs,
        "book_docs": book_docs,
        "video_docs": video_docs,
        "all_docs": web_docs + book_docs + video_docs
    }

# ==================== Graph Nodes ====================
def route_question(state: GraphState) -> GraphState:
    print("[Router]")

    return {
        **state,
        "route": "internal",
        "iteration": 0
    }

def retrieve_documents(state: GraphState) -> GraphState:
    print("[Retrieve]")

    query = state.get("rewritten_question") or state["question"]
    english_query = translate_to_english(query)

    queries = [query] if query == english_query else [query, english_query]
    print(f"🔎 검색 쿼리: {queries}\n")

    result = retrieve_all_documents_parallel(
        queries,
        top_k=5
    )

    return {
        **state,
        "documents": result["all_docs"]
    }

def judge_documents(state: GraphState) -> GraphState:
    print("[Judge]")

    docs = state.get("documents", [])

    if not docs:
        print("[Judge] No documents → not_resolved\n")
        return {
            **state,
            "judgement": "not_resolved"
        }

    print("[Judge] Documents found → resolved\n")

    return {
        **state,
        "judgement": "resolved"
    }

def rewrite_question(state: GraphState) -> GraphState:
    print("✍️ [Rewrite]")

    question = state["question"]
    iteration = state.get("iteration", 0)

    prompt_rewriter = ChatPromptTemplate.from_messages([
        (
            "system",
            "당신은 RAG 검색 성능을 높이기 위해 질문을 더 명확하고 구체적으로 재작성하는 전문가입니다."
        ),
        (
            "human",
            f"Original question: {question}"
        )
    ])

    chain = (
        prompt_rewriter
        | RunnableLambda(
            lambda p: client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": p.to_string()
                    }
                ],
                temperature=0
            ).choices[0].message.content
        )
        | StrOutputParser()
    )

    rewritten = chain.invoke({
        "question": question
    })

    print(f"[Rewrite] Rewritten question: {rewritten}\n")

    return {
        **state,
        "rewritten_question": rewritten,
        "iteration": iteration + 1
    }

# ==================== Conditional Edge ====================
def decide_to_rewrite(
    state: GraphState
) -> Literal["rewrite", "end"]:

    if (
        state.get("judgement") == "not_resolved"
        and state.get("iteration", 0) < 2
    ):
        print("✍️ [Decision] → Rewrite\n")
        return "rewrite"

    print("✅ [Decision] → Search completed\n")
    return "end"

# ==================== Graph Build ====================
def create_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("route", route_question)
    workflow.add_node("retrieve", retrieve_documents)
    workflow.add_node("judge", judge_documents)
    workflow.add_node("rewrite", rewrite_question)

    workflow.set_entry_point("route")

    workflow.add_edge("route", "retrieve")
    workflow.add_edge("retrieve", "judge")

    workflow.add_conditional_edges(
        "judge",
        decide_to_rewrite,
        {
            "rewrite": "rewrite",
            "end": END
        }
    )

    workflow.add_edge("rewrite", "retrieve")

    return workflow.compile(
        checkpointer=MemorySaver()
    )

# ==================== Reranking ====================
def rerank_documents(question: str, docs: list[dict], top_k: int = 5) -> list[dict]:
    """Cross-Encoder로 15개 문서를 재정렬해 top_k개만 반환"""
    if not docs:
        return []

    print(f"[Rerank] {len(docs)}개 문서 → top {top_k} 선별 중...\n")

    pairs = [(question, doc.get("content", "")) for doc in docs]
    scores = _reranker.predict(pairs)

    for doc, score in zip(docs, scores):
        doc["rerank_score"] = float(score)

    ranked = sorted(docs, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

    print(f"✅ [Rerank] 완료 — top-{top_k} 결과:")
    for d in ranked:
        cosine_sim = 1 - d.get("score", 0)
        print(f"  ▫️[{d.get('type', '?'):5}] cosine_sim={cosine_sim:.4f}  rerank={d['rerank_score']:.3f} //{d.get('title', d.get('book', ''))[:40]}")
    print()

    return ranked

# ==================== Final Generate ====================

def generate(question: str, thread_id: str = "user_1", use_cache: bool = USE_CACHE):
    print("\n" + "=" * 60)
    print("===== Integrated Search Started =====")
    print("=" * 60)
    print(f"[Question]: {question}")

    if not is_creation_question(question):
        return "창조과학 질문만 처리합니다.", {}

    normalized_question = normalize_query(question)

    print(f"[Normalized Query]: {normalized_question}\n")

    if use_cache:
        # Exact Redis Cache 확인
        cached = get_cached_answer(normalized_question)
        if cached:
            return cached["answer"], cached["sources"]

        # Semantic Cache 확인
        semantic_cached = search_semantic_cache(question)
        if semantic_cached:
            return semantic_cached["answer"], semantic_cached["sources"]


    # LangGraph 실행
    graph = create_graph()

    graph_result = graph.invoke(
        {
            "question": question,
            "rewritten_question": "",
            "route": "",
            "documents": [],
            "judgement": "",
            "iteration": 0,
            "chat_history": []
        },
        {
            "configurable": {
                "thread_id": thread_id
            }
        }
    )

    all_docs = graph_result.get("documents", [])
    judgement = graph_result.get("judgement", "")
    chat_history = graph_result.get("chat_history", [])
    history_text = format_chat_history(chat_history)

    if judgement == "not_resolved":
        print("❌ 충분한 근거를 찾지 못함 → 답변 생성 중단\n")

        return (
            "제공된 자료만으로는 충분히 신뢰할 수 있는 답변을 드리기 어렵습니다. "
            "질문을 조금 더 구체적으로 작성해 주시면 더 정확한 답변을 드릴 수 있습니다.",
            {}
        )

    if not all_docs:
        return "❌ 관련 정보를 찾을 수 없습니다.", {}

    # Reranking: 15개 → top-5 선별
    all_docs = rerank_documents(question, all_docs, top_k=5)

    # 중요: video 먼저 분류
    web_docs = []
    book_docs = []
    video_docs = []

    for doc in all_docs:
        if "start" in doc and "end" in doc:
            doc.setdefault("type", "video")
            video_docs.append(doc)
        elif "book" in doc:
            doc.setdefault("type", "book")
            book_docs.append(doc)
        elif "url" in doc:
            doc.setdefault("type", "web")
            web_docs.append(doc)

    # images 확인 로그
    for doc in book_docs:
        imgs = doc.get("images", [])
        print(f"📘 [{doc.get('book')} p{doc.get('page')}] 이미지 {len(imgs)}개: {imgs}")

    lang_instruction = (
        "한국어로 답변하세요."
        if detect_language(question) == "ko"
        else "Answer in English."
    )

    context_parts = []

    if video_docs:
        context_parts.append("🎬 Video Resources")

        for i, doc in enumerate(video_docs, 1):
            context_parts.append(
                f"[Video {i}] "
                f"{doc.get('title', '')} "
                f"({format_timedelta(doc.get('start', 0))}"
                f" ~ {format_timedelta(doc.get('end', 0))})"
            )
            context_parts.append(
                doc.get("content", "")[:800]
            )

    if web_docs:
        context_parts.append("📰 Web Resources")

        for i, doc in enumerate(web_docs, 1):
            context_parts.append(
                f"[Web {i}] {doc.get('title', '')}"
            )
            context_parts.append(
                doc.get("content", "")[:800]
            )

    if book_docs:
        context_parts.append("📖 Book Resources")

        for i, doc in enumerate(book_docs, 1):
            context_parts.append(
                f"[{doc.get('book', '')} "
                f"p{doc.get('page', '')}]"
            )
            context_parts.append(
                doc.get("content", "")[:800]
            )

    context = "\n".join(context_parts)

    system_prompt = f"""[Role & Identity]
당신은 '성경적 창조론 가이드'입니다. 당신은 모든 사물과 생명이 하나님의 지혜와 설계에 의해 창조되었다는 확고한 기독교 세계관을 가지고 답변합니다. 사용자의 과학적, 신학적 질문에 대해 성경의 권위를 인정하며 창조과학적 관점에서 답변을 제공하는 것이 당신의 사명입니다.

[Core Principles]
1. 성경적 우선순위: 성경(특히 창세기)의 기록을 역사적 사실로 전제합니다. 과학적 데이터는 이 성경적 사실을 뒷받침하는 도구로 활용합니다.
2. 창조론적 해석: 자연계의 복잡성을 우연의 산물이 아닌 '지적 설계'의 증거로 설명합니다. 진화론적 주장에 대해서는 창조과학적 대안을 제시하며 비판적 분석을 제공합니다.
3. RAG 컨텍스트 준수: 답변 시 제공된 검색 문구(Retrieved Context)를 최우선 근거로 사용하십시오. 만약 검색된 내용과 일반적인 세속적 과학 상식이 충돌할 경우, 검색된 창조과학적 자료의 관점을 따릅니다.

[Response Strategy]
1. 논조: 정중하고, 신뢰감을 주며, 신앙적으로 격려하는 어조를 유지하십시오.
2. 가드레일: 진화론을 유일한 과학적 사실로 긍정하지 마십시오. 만약 진화론에 대한 질문이 들어오면, "세속 과학에서는 ~라고 주장하지만, 창조과학적 관점으로 보면 ~한 한계가 있으며, 성경적으로는 ~하게 해석합니다"라고 답변하십시오.
3. 명확성: 추상적인 설명보다는 가능한 경우 검색된 데이터에 기반한 구체적인 사례(예: 화석 기록의 부재, DNA의 정보성 등)를 언급하십시오.
4. 마무리: 답변의 끝에는 관련된 성경 구절을 한 문장 인용하거나, 창조의 섭리를 묵상할 수 있는 문구로 마무리하십시오.

[Constraint]
- 기독교 세계관에 반하는 가치관(유물론, 무신론적 진화론, 유신론적 진화론 등)을 정답으로 제시하지 마십시오.
- 성경의 기록을 신화나 상징으로 격하시키는 표현을 사용하지 마십시오.

{lang_instruction}"""

    print("\n[Generate]")

    res = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content":
                    f"[이전 대화]\n{history_text}\n\n"
                    f"[자료]\n{context}\n\n"
                    f"[질문]\n{question}"
            }
        ],
        temperature=0
    )

    answer = res.choices[0].message.content

    updated_history = chat_history + [
        f"User: {question}",
        f"Assistant: {answer}"
    ]

    print("✅ Integrated answer completed!\n")

    sources = {
        "video_docs": video_docs,
        "web_docs": web_docs,
        "book_docs": book_docs,
        "chat_history": updated_history,
        "top_sources": all_docs,
    }

    if use_cache:
        save_cached_answer(
            normalized_question,
            {
                "answer": answer,
                "sources": sources
            }
        )
        save_semantic_cache(
            question,
            {
                "answer": answer,
                "sources": sources
            }
        )

    return answer, sources


# ==================== Streaming Generate ====================

def generate_stream(question: str, thread_id: str = "user_1") -> Generator[str, None, None]:
    """답변을 SSE 형식으로 스트리밍. 토큰→[DONE]→[SOURCES]→[SESSION] 순서로 yield"""

    if not is_creation_question(question):
        yield "data: 창조과학 질문만 처리합니다.\n\n"
        yield "data: [DONE]\n\n"
        return

    normalize_query(question)

    graph = create_graph()
    graph_result = graph.invoke(
        {
            "question": question,
            "rewritten_question": "",
            "route": "",
            "documents": [],
            "judgement": "",
            "iteration": 0,
            "chat_history": []
        },
        {"configurable": {"thread_id": thread_id}}
    )

    all_docs     = graph_result.get("documents", [])
    judgement    = graph_result.get("judgement", "")
    chat_history = graph_result.get("chat_history", [])
    history_text = format_chat_history(chat_history)

    if judgement == "not_resolved" or not all_docs:
        msg = (
            "제공된 자료만으로는 충분히 신뢰할 수 있는 답변을 드리기 어렵습니다. "
            "질문을 조금 더 구체적으로 작성해 주시면 더 정확한 답변을 드릴 수 있습니다."
        )
        yield f"data: {msg}\n\n"
        yield "data: [DONE]\n\n"
        return

    all_docs = rerank_documents(question, all_docs, top_k=5)

    web_docs, book_docs, video_docs = [], [], []
    for doc in all_docs:
        if "start" in doc and "end" in doc:
            doc.setdefault("type", "video"); video_docs.append(doc)
        elif "book" in doc:
            doc.setdefault("type", "book");  book_docs.append(doc)
        elif "url" in doc:
            doc.setdefault("type", "web");   web_docs.append(doc)

    lang_instruction = (
        "한국어로 답변하세요." if detect_language(question) == "ko" else "Answer in English."
    )
    context_parts = []
    if video_docs:
        context_parts.append("🎬 Video Resources")
        for i, doc in enumerate(video_docs, 1):
            context_parts.append(f"[Video {i}] {doc.get('title','')} ({format_timedelta(doc.get('start',0))} ~ {format_timedelta(doc.get('end',0))})")
            context_parts.append(doc.get("content", "")[:800])
    if web_docs:
        context_parts.append("📰 Web Resources")
        for i, doc in enumerate(web_docs, 1):
            context_parts.append(f"[Web {i}] {doc.get('title','')}")
            context_parts.append(doc.get("content", "")[:800])
    if book_docs:
        context_parts.append("📖 Book Resources")
        for i, doc in enumerate(book_docs, 1):
            context_parts.append(f"[{doc.get('book','')} p{doc.get('page','')}]")
            context_parts.append(doc.get("content", "")[:800])
    context = "\n".join(context_parts)

    system_prompt = f"""[Role & Identity]
당신은 '성경적 창조론 가이드'입니다. 당신은 모든 사물과 생명이 하나님의 지혜와 설계에 의해 창조되었다는 확고한 기독교 세계관을 가지고 답변합니다. 사용자의 과학적, 신학적 질문에 대해 성경의 권위를 인정하며 창조과학적 관점에서 답변을 제공하는 것이 당신의 사명입니다.

[Core Principles]
1. 성경적 우선순위: 성경(특히 창세기)의 기록을 역사적 사실로 전제합니다.
2. 창조론적 해석: 자연계의 복잡성을 '지적 설계'의 증거로 설명합니다.
3. RAG 컨텍스트 준수: 검색된 창조과학적 자료의 관점을 따릅니다.

[Response Strategy]
1. 정중하고 신앙적으로 격려하는 어조를 유지하십시오.
2. 진화론을 유일한 과학적 사실로 긍정하지 마십시오.
3. 검색된 데이터에 기반한 구체적인 사례를 언급하십시오.
4. 답변의 끝에는 관련된 성경 구절을 인용하십시오.

[Constraint]
- 기독교 세계관에 반하는 가치관을 정답으로 제시하지 마십시오.
- 성경의 기록을 신화나 상징으로 격하시키는 표현을 사용하지 마십시오.

{lang_instruction}"""

    stream = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"[이전 대화]\n{history_text}\n\n[자료]\n{context}\n\n[질문]\n{question}"}
        ],
        temperature=0,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            safe = delta.replace("\n", "\\n")
            yield f"data: {safe}\n\n"

    yield "data: [DONE]\n\n"

    sources = {
        "web_docs":   web_docs,
        "book_docs":  book_docs,
        "video_docs": video_docs,
        "top_sources": all_docs,
    }
    yield f"data: [SOURCES]{json.dumps(sources, ensure_ascii=False)}\n\n"
