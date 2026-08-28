import json
from concurrent.futures import ThreadPoolExecutor
import contextvars
from datetime import timedelta
from typing import Generator, List, Literal
from typing_extensions import TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sentence_transformers import CrossEncoder

# config를 먼저 import해서 .env가 로드된 다음에 langfuse를 초기화한다
from config import LLM_MODEL

from langfuse import observe, propagate_attributes, get_client as get_langfuse_client
from langfuse.langchain import CallbackHandler

from llm_factory import get_client
from bbot_web import retrieve_web_documents
from bbot_book import retrieve_pages
from bbot_video import retrieve_video_segments
from utils import detect_language, translate_to_english, extract_final_answer, reasoning_kwargs
from moderation import is_safe_input

import re

from logging_config import get_logger

logger = get_logger(__name__)

# ==================== Reranker ====================

_reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1") # 다국어 모델

# ==================== [임시] 궁금해궁금해 → 구매 링크 처리 ====================
# TODO: 임시 조치. 책 페이지 출처 대신 구매 링크(웹 출처 형태)로 노출.
# 되돌릴 때는 이 블록과 classify_documents() 내 관련 분기만 제거하면 됨.
# GUNGGEUM_BOOK_NAME = "궁금해궁금해"
# GUNGGEUM_PURCHASE_URL = "https://www.yes24.com/product/goods/85464691"


def classify_documents(docs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """문서 리스트를 web / book / video로 분류.

    [임시] book_name이 '궁금해궁금해'인 문서는 book이 아니라 web 취급하여
    페이지 정보 대신 구매 링크를 보여줌.
    """
    web_docs, book_docs, video_docs = [], [], []

    for doc in docs:
        if "start" in doc and "end" in doc:
            doc.setdefault("type", "video")
            video_docs.append(doc)
        # elif "book" in doc and doc.get("book") == GUNGGEUM_BOOK_NAME:
        #     doc["type"] = "web"
        #     doc["title"] = doc.get("book", GUNGGEUM_BOOK_NAME)
        #     doc["url"] = GUNGGEUM_PURCHASE_URL
        #     web_docs.append(doc)
        elif "book" in doc:
            doc.setdefault("type", "book")
            book_docs.append(doc)
        elif "url" in doc:
            doc.setdefault("type", "web")
            web_docs.append(doc)

    return web_docs, book_docs, video_docs

try:
    from redis_cache import (
        get_cached_answer, search_semantic_cache, save_answer_cache,
        get_embedding, CACHE_KEY_PREFIX,
        r as _redis_client, cosine_similarity as _cosine_similarity,
    )
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


client = get_client()

# LangGraph/LangChain 실행을 자동으로 Langfuse에 트레이싱하는 콜백 핸들러.
# graph.invoke()의 config에 넣어주면 route/retrieve/judge/rewrite 노드가
# 자동으로 중첩된 span으로 기록됨
_langfuse_langchain_handler = CallbackHandler()

# ==================== Cache Toggle ====================

USE_CACHE = True  # redis 모듈 없으면 자동 비활성화

# ==================== State ====================
class GraphState(TypedDict):
    question: str
    rewritten_question: str
    route: str
    documents: List[dict]
    judgement: str
    iteration: int
    chat_history: List[str]
    # ---- rerank/generate 노드화로 추가된 필드 ----
    qualified_documents: List[dict]   # judge_stage1 통과 문서 (rerank 입력)
    reranked_documents: List[dict]    # rerank 출력 top-k (judge_stage2, generate 입력)
    sources: dict                      # rerank 노드에서 확정되는 web/book/video 분류 결과
    final_messages: List[dict]         # generate 노드에서 조립된 system/user 메시지
    fallback_message: str              # judge 실패 시 즉시 반환할 안내 메시지


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
    # LangGraph 밖에서 호출되는 단발성 게이트라 별도 span으로 감싸지 않고,
    # chat.completions.create()에 name만 지정해 자동 생성되는 generation을 그대로 사용
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
        temperature=0,
        name="classify-creation-question",
        **reasoning_kwargs(),
    )

    answer = extract_final_answer(res.choices[0].message)
    return "true" in answer.lower()

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

@observe(name="retrieve-context-parallel", as_type="retriever", capture_input=False, capture_output=False)
def retrieve_all_documents_parallel(queries: list[str], top_k: int = 5):

    # 작업마다 독립된 컨텍스트 복사본을 만들어야 함 —
    # Context 객체 하나를 여러 스레드가 동시에 run()하면
    # "already entered" RuntimeError가 남
    futures = []
    with ThreadPoolExecutor(max_workers=9) as executor:
        for q in queries:
            futures.append(("web",   executor.submit(contextvars.copy_context().run, retrieve_web_documents, q, top_k)))
            futures.append(("book",  executor.submit(contextvars.copy_context().run, retrieve_pages, q, top_k)))
            futures.append(("video", executor.submit(contextvars.copy_context().run, retrieve_video_segments, q, top_k)))

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

    logger.info("Parallel search completed")

    get_langfuse_client().update_current_span(
        input={"queries": queries, "top_k": top_k},
        output={
            "web_docs": len(web_docs),
            "book_docs": len(book_docs),
            "video_docs": len(video_docs),
        },
    )

    return {
        "web_docs": web_docs,
        "book_docs": book_docs,
        "video_docs": video_docs,
        "all_docs": web_docs + book_docs + video_docs
    }

# ==================== Graph Nodes ====================
def route_question(state: GraphState) -> GraphState:
    logger.debug("[Router]")

    return {
        **state,
        "route": "internal",
        "iteration": 0
    }

def retrieve_documents(state: GraphState) -> GraphState:
    logger.debug("[Retrieve]")

    query = state.get("rewritten_question") or state["question"]
    english_query = translate_to_english(query)

    queries = [query] if query == english_query else [query, english_query]
    logger.debug("검색 쿼리: %s", queries)

    result = retrieve_all_documents_parallel(
        queries,
        top_k=5
    )

    get_langfuse_client().update_current_span(
        input={"query": query},
        output={
            "web_docs": len(result["web_docs"]),
            "book_docs": len(result["book_docs"]),
            "video_docs": len(result["video_docs"]),
        },
    )

    return {
        **state,
        "documents": result["all_docs"]
    }

# judge_stage1: rerank에 넘길 후보를 고르는 "예비 필터" threshold.
# 최종 판정이 아니므로 느슨하게 잡는다. 실측 전 placeholder — 방향은 아래 참고.
#   - score는 코사인 거리(작을수록 유사)이므로 (1 - score)가 유사도.
#   - 세 타입 모두 일단 동일값(0.3)으로 시작해 "거의 걸러내지 않는" 안전한 기본값을 둔다.
#     즉 judge_stage1은 사실상 "완전히 무관한 것만 제거"하는 역할이고,
#     실제 관련도 판단은 rerank_score(judge_stage2)에서 이뤄지도록 한다.
#   - 실측 후에는 타입별로(web/book/video) 분리해 조정한다.
JUDGE_STAGE1_THRESHOLD = 0.3


def judge_stage1(state: GraphState) -> GraphState:
    """LLM 호출 없는 점수 기반 예비 필터. rerank로 넘길 후보(qualified_documents)를 고른다."""
    logger.debug("[Judge Stage1]")

    docs = state.get("documents", [])
    qualified = [
        d for d in docs
        if (1 - d.get("score", 1.0)) >= JUDGE_STAGE1_THRESHOLD
    ]

    judgement = "pending_rerank" if qualified else "not_resolved"

    if not qualified:
        logger.warning("[Judge Stage1] 통과 문서 없음 → not_resolved")
    else:
        logger.debug("[Judge Stage1] %d/%d개 통과 → pending_rerank", len(qualified), len(docs))

    get_langfuse_client().update_current_span(
        input={"document_count": len(docs), "threshold": JUDGE_STAGE1_THRESHOLD},
        output={"judgement": judgement, "qualified_count": len(qualified)},
    )

    return {
        **state,
        "judgement": judgement,
        "qualified_documents": qualified,
    }


# judge_stage2: rerank 결과를 LLM에게 배치로 보여주고 관련도를 판정.
# "관대한 기본값 + 명백한 이탈만 차단" 원칙의 placeholder 프롬프트 — 실측 후 문구 조정.
def judge_stage2(state: GraphState) -> GraphState:
    """reranked_documents를 대상으로 배치 LLM 콜 1회로 최종 관련도 판정."""
    logger.debug("[Judge Stage2]")

    docs = state.get("reranked_documents", [])
    question = state.get("rewritten_question") or state["question"]

    if not docs:
        logger.warning("[Judge Stage2] reranked_documents 없음 → not_resolved")
        get_langfuse_client().update_current_span(
            input={"document_count": 0},
            output={"judgement": "not_resolved"},
        )
        return {**state, "judgement": "not_resolved"}

    summary = "\n".join(
        f"[{i+1}] {d.get('title', d.get('book', ''))}: {d.get('content', '')[:150]}"
        for i, d in enumerate(docs)
    )

    res = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{
            "role": "user",
            "content": f"""아래 문서들이 질문에 답하기에 명백히 무관한 경우에만 false,
그 외에는 모두 true를 출력하세요.

질문: {question}

문서:
{summary}

true 또는 false만 출력.""",
        }],
        temperature=0,
        name="judge-stage2-relevance",
        **reasoning_kwargs(),
    )

    answer = extract_final_answer(res.choices[0].message)
    judgement = "resolved" if "false" not in answer.lower() else "not_resolved"

    logger.debug("[Judge Stage2] LLM 판정: %s → %s", answer.strip(), judgement)

    get_langfuse_client().update_current_span(
        input={"question": question, "document_count": len(docs)},
        output={"judgement": judgement, "raw_answer": answer},
    )

    return {**state, "judgement": judgement}

def rewrite_question(state: GraphState) -> GraphState:
    logger.info("[Rewrite]")

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
                temperature=0,
                name="generate-rewritten-question",
            ).choices[0].message.content
        )
        | StrOutputParser()
    )

    rewritten = chain.invoke({
        "question": question
    })

    logger.debug("[Rewrite] Rewritten question: %s", rewritten)

    get_langfuse_client().update_current_span(
        input={"question": question, "iteration": iteration},
        output={"rewritten_question": rewritten},
    )

    return {
        **state,
        "rewritten_question": rewritten,
        "iteration": iteration + 1
    }

# ==================== Conditional Edges ====================
# 재시도 카운터(iteration)는 stage1/stage2가 공유한다 — 전체 그래프 실행에서
# rewrite는 최대 2회만 허용
# 별도 카운터로 분리하지 않는 이유: 분리 시 rerank 실행 횟수·왕복 단계 수가
# 최악의 경우 예측하기 어려워지기 때문 (rerank 반복 비용에 대한 근거는 문서 4-3 참고).
MAX_REWRITE_ITERATIONS = 2


def decide_stage1(state: GraphState) -> Literal["rerank", "rewrite", "fallback"]:
    if state.get("judgement") == "pending_rerank":
        logger.debug("[Decision Stage1] → rerank")
        return "rerank"

    if state.get("iteration", 0) < MAX_REWRITE_ITERATIONS:
        logger.debug("[Decision Stage1] → rewrite")
        return "rewrite"

    logger.debug("[Decision Stage1] → fallback")
    return "fallback"


def decide_stage2(state: GraphState) -> Literal["generate", "rewrite", "fallback"]:
    if state.get("judgement") == "resolved":
        logger.debug("[Decision Stage2] → generate")
        return "generate"

    if state.get("iteration", 0) < MAX_REWRITE_ITERATIONS:
        logger.debug("[Decision Stage2] → rewrite")
        return "rewrite"

    logger.debug("[Decision Stage2] → fallback")
    return "fallback"

# ==================== Graph Build ====================
def create_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("route", route_question)
    workflow.add_node("retrieve", retrieve_documents)
    workflow.add_node("judge_stage1", judge_stage1)
    workflow.add_node("rerank", rerank_node)
    workflow.add_node("judge_stage2", judge_stage2)
    workflow.add_node("rewrite", rewrite_question)
    workflow.add_node("generate", generate_node)
    workflow.add_node("fallback", fallback_node)

    workflow.set_entry_point("route")

    workflow.add_edge("route", "retrieve")
    workflow.add_edge("retrieve", "judge_stage1")

    workflow.add_conditional_edges(
        "judge_stage1",
        decide_stage1,
        {
            "rerank": "rerank",
            "rewrite": "rewrite",
            "fallback": "fallback",
        }
    )

    workflow.add_edge("rerank", "judge_stage2")

    workflow.add_conditional_edges(
        "judge_stage2",
        decide_stage2,
        {
            "generate": "generate",
            "rewrite": "rewrite",
            "fallback": "fallback",
        }
    )

    workflow.add_edge("rewrite", "retrieve")
    workflow.add_edge("generate", END)
    workflow.add_edge("fallback", END)

    return workflow.compile(
        checkpointer=MemorySaver()
    )

# ==================== Reranking ====================
@observe(name="rerank-context", as_type="tool", capture_input=False, capture_output=False)
def rerank_documents(question: str, docs: list[dict], top_k: int = 5) -> list[dict]:
    """Cross-Encoder로 15개 문서를 재정렬해 top_k개만 반환"""
    if not docs:
        return []

    logger.debug("[Rerank] %d개 문서 → top %d 선별 중...", len(docs), top_k)

    pairs = [(question, doc.get("content", "")) for doc in docs]
    scores = _reranker.predict(pairs)

    for doc, score in zip(docs, scores):
        doc["rerank_score"] = float(score)

    ranked = sorted(docs, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

    logger.info("[Rerank] 완료 — top-%d 결과:", top_k)
    for d in ranked:
        cosine_sim = 1 - d.get("score", 0)
        logger.debug("  [%s] cosine_sim=%.4f  rerank=%.3f // %s", d.get('type', '?'), cosine_sim, d['rerank_score'], d.get('title', d.get('book', ''))[:40])

    get_langfuse_client().update_current_span(
        input={"question": question, "candidate_count": len(docs)},
        output={"selected_count": len(ranked), "top_k": top_k},
    )

    return ranked


# ==================== Rerank Node ====================
def rerank_node(state: GraphState) -> GraphState:
    """judge_stage1을 통과한 qualified_documents만 대상으로 Cross-Encoder 재정렬.
    top_k(5)로 압축하고, 출처 분류(sources)까지 이 노드에서 함께 확정한다.
    기존 rerank_documents()/classify_documents()를 그대로 재사용한다."""
    logger.debug("[Rerank Node]")

    qualified = state.get("qualified_documents", [])
    question = state.get("rewritten_question") or state["question"]

    ranked = rerank_documents(question, qualified, top_k=5)

    web_docs, book_docs, video_docs = classify_documents(ranked)

    return {
        **state,
        "reranked_documents": ranked,
        "sources": {
            "web_docs": web_docs,
            "book_docs": book_docs,
            "video_docs": video_docs,
        },
    }


# ==================== Fallback Node ====================
FALLBACK_MESSAGE = (
    "제공된 자료만으로는 충분히 신뢰할 수 있는 답변을 드리기 어렵습니다. "
    "질문을 조금 더 구체적으로 작성해 주시면 더 정확한 답변을 드릴 수 있습니다."
)


def fallback_node(state: GraphState) -> GraphState:
    """judge_stage1/2가 재시도 소진 후에도 실패했을 때 LLM 호출 없이 즉시 반환할 메시지."""
    logger.warning("[Fallback] 충분한 근거를 찾지 못함 → 답변 생성 중단")

    get_langfuse_client().update_current_span(
        input={"iteration": state.get("iteration", 0)},
        output={"fallback_message": FALLBACK_MESSAGE},
    )

    return {
        **state,
        "fallback_message": FALLBACK_MESSAGE,
    }


# ==================== Context 조립 헬퍼 ====================
def _build_context(video_docs: list[dict], web_docs: list[dict], book_docs: list[dict]) -> str:
    """video → web → book 순서로 컨텍스트 텍스트 블록을 조립.
    기존 generate()/generate_stream()에 중복 구현되어 있던 로직을 하나로 통합."""
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
            context_parts.append(doc.get("content", "")[:800])

    if web_docs:
        context_parts.append("📰 Web Resources")
        for i, doc in enumerate(web_docs, 1):
            context_parts.append(f"[Web {i}] {doc.get('title', '')}")
            context_parts.append(doc.get("content", "")[:800])

    if book_docs:
        context_parts.append("📖 Book Resources")
        for i, doc in enumerate(book_docs, 1):
            context_parts.append(f"[{doc.get('book', '')} p{doc.get('page', '')}]")
            context_parts.append(doc.get("content", "")[:800])

    return "\n".join(context_parts)


# ==================== 시스템 프롬프트 ====================
SYSTEM_PROMPT_TEMPLATE = """[Role & Identity]
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


# ==================== Generate Node ====================
def generate_node(state: GraphState) -> GraphState:
    """reranked_documents/sources만을 참조하여 최종 LLM 입력 메시지(final_messages)를 조립.
    실제 LLM 호출(스트리밍 여부 분기)은 이 노드에서 수행하지 않고 그래프 밖 어댑터가 담당한다."""
    logger.debug("[Generate Node]")

    question = state["question"]
    chat_history = state.get("chat_history", [])

    sources = state.get("sources", {})
    web_docs = sources.get("web_docs", [])
    book_docs = sources.get("book_docs", [])
    video_docs = sources.get("video_docs", [])

    context = _build_context(video_docs, web_docs, book_docs)
    lang_instruction = (
        "한국어로 답변하세요."
        if detect_language(question) == "ko"
        else "Answer in English."
    )
    history_text = format_chat_history(chat_history)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(lang_instruction=lang_instruction)

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"[이전 대화]\n{history_text}\n\n"
                f"[자료]\n{context}\n\n"
                f"[질문]\n{question}"
            ),
        },
    ]

    get_langfuse_client().update_current_span(
        input={"question": question},
        output={
            "web_docs": len(web_docs),
            "book_docs": len(book_docs),
            "video_docs": len(video_docs),
        },
    )

    return {
        **state,
        "final_messages": messages,
    }

# ==================== 캐시 조회/저장 공용 헬퍼 ====================
# generate()/generate_stream()에 중복 구현되어 있던
# exact/semantic 캐시 조회, cache-off 유사도 로깅, 캐시 저장 로직을 통합.
#
# 조회 결과 소비 방식(return vs SSE yield)이 두 함수에서 다르므로,
# 조회 함수는 "히트 여부 + 데이터"만 반환하고 실제 응답 처리는 호출부에 남긴다.

def lookup_answer_cache(question: str, normalized_question: str, use_cache: bool) -> tuple[str | None, dict | None]:
    """
    Exact → Semantic 순서로 캐시 조회.
    use_cache=False인 경우 조회 대신 유사도 점수만 로그로 남기고 (None, None) 반환.

    Returns:
        (cache_hit_type, data) — hit 시 cache_hit_type은 "exact" 또는 "semantic",
        data는 {"answer": ..., "sources": ...}. 미스 시 (None, None).
    """
    if use_cache:
        cached = get_cached_answer(normalized_question)
        if cached:
            return "exact", cached

        semantic_cached = search_semantic_cache(question)
        if semantic_cached:
            return "semantic", semantic_cached

        return None, None

    if _REDIS_AVAILABLE:
        # 캐시 비활성화 시에도 유사도 점수만 로그로 확인
        _keys = list(_redis_client.scan_iter(f"{CACHE_KEY_PREFIX}*"))
        if _keys:
            _q_emb = get_embedding(question)
            logger.debug("[Similarity Log (cache OFF)]")
            for _key in _keys:
                _raw = _redis_client.get(_key)
                if not _raw:
                    continue
                _item = json.loads(_raw)
                if len(_item.get("embedding", [])) != len(_q_emb):
                    continue  # 다른 provider로 저장된 옛 데이터는 로그에서도 스킵
                _score = _cosine_similarity([_q_emb], [_item["embedding"]])[0][0]
                logger.debug("  score=%.4f | cached_query='%s'", _score, _item['query'])

    return None, None


def persist_answer_cache(use_cache: bool, normalized_question: str, question: str, answer: str, sources: dict) -> None:
    """use_cache=True일 때만 캐시에 저장.
    Redis 등 캐시 저장 실패가 API 응답 자체를 실패시키면 안 되므로
    (fail-open) 예외 처리를 이 함수 내부에서 담당한다 — 호출부는 신경 쓸 필요 없음."""
    if not use_cache:
        return
    try:
        save_answer_cache(
            normalized_question,
            question,
            {"answer": answer, "sources": sources},
        )
        logger.debug("캐시 저장 완료 — question: %s", question)
    except Exception as e:
        logger.error("캐시 저장 실패: %s", e, exc_info=True)


# ==================== Final Generate ====================

@observe(name="generate-response", capture_input=False, capture_output=False)
def generate(
    question: str,
    thread_id: str = "user_1",
    use_cache: bool = USE_CACHE,
    user_id: str | None = None,
    source: str = "cli",
):
    langfuse = get_langfuse_client()

    with propagate_attributes(
        session_id=thread_id,
        user_id=user_id,
        tags=[source],
    ):
        langfuse.update_current_span(input={"question": question})

        logger.info("===== Integrated Search Started ===== question=%s", question)

    safe, reason = is_safe_input(question)
    if not safe:
       logger.warning("[Blocked] reason=%s | question=%s", reason, question[:200])
       return "죄송합니다. 해당 요청은 처리할 수 없습니다.", {}

    # if not is_creation_question(question):
    #     return "창조과학 질문만 처리합니다.", {}

    normalized_question = normalize_query(question)

    logger.debug("[Normalized Query]: %s", normalized_question)

    cache_hit_type, cached = lookup_answer_cache(question, normalized_question, use_cache)
    if cached:
        langfuse.update_current_span(
            output=cached["answer"],
            metadata={"cache_hit": cache_hit_type},
        )
        return cached["answer"], cached["sources"]

    # LangGraph 실행 — callbacks에 Langfuse 핸들러를 넘겨서
    # route/retrieve/judge_stage1/rerank/judge_stage2/rewrite/generate/fallback
    # 노드 전체가 하나의 invoke() 아래에서 자동으로 트레이싱되게 함
    graph = create_graph()

    graph_result = graph.invoke(
        {
            "question": question,
            "rewritten_question": "",
            "route": "",
            "documents": [],
            "judgement": "",
            "iteration": 0,
            "chat_history": [],
            "qualified_documents": [],
            "reranked_documents": [],
            "sources": {},
            "final_messages": [],
            "fallback_message": "",
        },
        {
            "configurable": {
                "thread_id": thread_id
            },
            "callbacks": [_langfuse_langchain_handler],
        }
    )

    chat_history = graph_result.get("chat_history", [])

    # judge_stage1/2가 재시도 소진 후에도 실패 → fallback 노드가 채운 메시지를
    # LLM 호출 없이 그대로 반환
    if graph_result.get("fallback_message"):
        answer = graph_result["fallback_message"]
        langfuse.update_current_span(
            output=answer,
            metadata={"judgement": "not_resolved"},
        )
        return answer, {}

    reranked_docs = graph_result.get("reranked_documents", [])
    sources_by_type = graph_result.get("sources", {})
    web_docs = sources_by_type.get("web_docs", [])
    book_docs = sources_by_type.get("book_docs", [])
    video_docs = sources_by_type.get("video_docs", [])

    # images 확인 로그
    for doc in book_docs:
        imgs = doc.get("images", [])
        logger.debug("[%s p%s] 이미지 %d개: %s", doc.get('book'), doc.get('page'), len(imgs), imgs)

    messages = graph_result["final_messages"]

    logger.debug("[Generate]")

    res = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0,
        name="generate-final-answer",
        **reasoning_kwargs(),
    )

    answer = extract_final_answer(res.choices[0].message)

    updated_history = chat_history + [
        f"User: {question}",
        f"Assistant: {answer}"
    ]

    logger.info("Integrated answer completed")

    sources = {
        "video_docs": video_docs,
        "web_docs": web_docs,
        "book_docs": book_docs,
        "chat_history": updated_history,
        "top_sources": reranked_docs,
    }

    langfuse.update_current_span(
        output=answer,
        metadata={
            "web_docs": len(web_docs),
            "book_docs": len(book_docs),
            "video_docs": len(video_docs),
        },
    )

    persist_answer_cache(use_cache, normalized_question, question, answer, sources)

    return answer, sources


# ==================== Streaming Generate ====================

@observe(name="generate-response-stream", capture_input=False, capture_output=False)
def generate_stream(
    question: str,
    thread_id: str = "user_1",
    use_cache: bool = USE_CACHE,
    user_id: str | None = None,
    source: str = "cli",
) -> Generator[str, None, None]:
    """답변을 SSE 형식으로 스트리밍. 토큰→[DONE]→[SOURCES]→[SESSION] 순서로 yield"""

    langfuse = get_langfuse_client()

    safe, reason = is_safe_input(question)
    if not safe:
       logger.warning("[Blocked-Stream] reason=%s | question=%s", reason, question[:200])
       yield "data: 죄송합니다. 해당 요청은 처리할 수 없습니다.\n\n"
       yield "data: [DONE]\n\n"
       return

    # if not is_creation_question(question):
    #     yield "data: 창조과학 질문만 처리합니다.\n\n"
    #     yield "data: [DONE]\n\n"
    #     return

    normalized_question = normalize_query(question)

    # ---------- 캐시 조회 ----------
    cache_hit_type, cached = lookup_answer_cache(question, normalized_question, use_cache)
    if cached:
        logger.info("Cache Hit (stream, %s) — question: %s", cache_hit_type, question)
        answer = cached["answer"]
        sources = cached["sources"]

        for i in range(0, len(answer), 20):
            piece = answer[i:i+20].replace("\n", "\\n")
            yield f"data: {piece}\n\n"

        yield "data: [DONE]\n\n"
        yield f"data: [SOURCES]{json.dumps(sources, ensure_ascii=False)}\n\n"

        langfuse.update_current_span(
            output=answer,
            metadata={"cache_hit": cache_hit_type},
        )
        return
    # ---------- 캐시 조회 끝 ----------

    graph = create_graph()
    graph_result = graph.invoke(
        {
            "question": question,
            "rewritten_question": "",
            "route": "",
            "documents": [],
            "judgement": "",
            "iteration": 0,
            "chat_history": [],
            "qualified_documents": [],
            "reranked_documents": [],
            "sources": {},
            "final_messages": [],
            "fallback_message": "",
        },
        {
            "configurable": {"thread_id": thread_id},
            "callbacks": [_langfuse_langchain_handler],
        }
    )

    # judge_stage1/2가 재시도 소진 후에도 실패 → fallback 노드가 채운 메시지를
    # LLM 호출 없이 그대로 스트리밍
    if graph_result.get("fallback_message"):
        msg = graph_result["fallback_message"]
        yield f"data: {msg}\n\n"
        yield "data: [DONE]\n\n"

        langfuse.update_current_span(
            output=msg,
            metadata={"judgement": "not_resolved"},
        )
        return

    reranked_docs = graph_result.get("reranked_documents", [])
    sources_by_type = graph_result.get("sources", {})
    web_docs = sources_by_type.get("web_docs", [])
    book_docs = sources_by_type.get("book_docs", [])
    video_docs = sources_by_type.get("video_docs", [])

    messages = graph_result["final_messages"]

    stream = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0,
        stream=True,
        name="generate-final-answer-stream",
        **reasoning_kwargs(),
    )

    full_answer = ""
    for chunk in stream:
        # stream_options={"include_usage": True}를 나중에 켜서 토큰 사용량을
        # 트레이싱하게 되면, 마지막에 choices가 빈 청크가 하나 더 오므로
        # 이 가드가 없으면 IndexError가 남
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            full_answer += delta
            safe = delta.replace("\n", "\\n")
            yield f"data: {safe}\n\n"

    sources = {
        "web_docs":   web_docs,
        "book_docs":  book_docs,
        "video_docs": video_docs,
        "top_sources": reranked_docs,
    }

    # ---------- 캐시 저장 ----------
    persist_answer_cache(use_cache, normalized_question, question, full_answer, sources)
    # -------------------------------

    yield "data: [DONE]\n\n"
    yield f"data: [SOURCES]{json.dumps(sources, ensure_ascii=False)}\n\n"
