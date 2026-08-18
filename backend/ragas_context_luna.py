# Ragas 기반 RAG 평가 모듈 (gpt-5.6-luna 전용)
#
# python ragas_context_luna.py              # 기본 5개
# python ragas_context_luna.py --limit 20   # 20개
# python ragas_context_luna.py --limit -1   # 전체
#
# 전제:
#   - .env: PROVIDER=openai, OPENAI_LLM_MODEL=gpt-5.6-luna, OPENAI_EMBED_MODEL 설정
#   - judge LLM은 평가 안정성을 위해 gpt-4o-mini로 고정 (temperature 이슈 없음)
#   - eval_data.xlsx: 1열 question, 2열 ground_truth

import sys
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ==================== OpenAI 최신 모델 호환 패치 ====================
# gpt-5.x 등 max_tokens 대신 max_completion_tokens만 받는 모델 대응
# + Ragas 내부 max_tokens가 너무 작아 answer_correctness가 잘려서 nan 나는 문제 방지
import openai
from openai.resources.chat.completions import Completions

_RAGAS_MAX_TOKENS = 8192  # 부족하면 16384로 올리기

def _patched_create(self, *args, **kwargs):
    if "max_tokens" in kwargs:
        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
    if kwargs.get("max_completion_tokens", 0) < _RAGAS_MAX_TOKENS:
        kwargs["max_completion_tokens"] = _RAGAS_MAX_TOKENS
    return _orig_create(self, *args, **kwargs)

_orig_create = Completions.create
Completions.create = _patched_create

try:
    from openai.resources.chat.completions import AsyncCompletions
    _orig_async_create = AsyncCompletions.create
    async def _patched_async_create(self, *args, **kwargs):
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        if kwargs.get("max_completion_tokens", 0) < _RAGAS_MAX_TOKENS:
            kwargs["max_completion_tokens"] = _RAGAS_MAX_TOKENS
        return await _orig_async_create(self, *args, **kwargs)
    AsyncCompletions.create = _patched_async_create
except (ImportError, AttributeError):
    pass

try:
    from openai.resources.chat import AsyncCompletions
    _orig_async_create2 = AsyncCompletions.create
    async def _patched_async_create2(self, *args, **kwargs):
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        if kwargs.get("max_completion_tokens", 0) < _RAGAS_MAX_TOKENS:
            kwargs["max_completion_tokens"] = _RAGAS_MAX_TOKENS
        return await _orig_async_create2(self, *args, **kwargs)
    AsyncCompletions.create = _patched_async_create2
except (ImportError, AttributeError):
    pass
# =====================================================================

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,        # 충실도: 답변이 검색된 컨텍스트에 근거하는지
    answer_relevancy,    # 답변 관련성: 답변이 질문과 관련 있는지
    context_precision,   # 컨텍스트 정밀도: 검색 문서 중 유용한 비율
    context_recall,      # 컨텍스트 재현율: ground truth에 필요한 정보가 포함됐는지 (ground_truth 필요)
    answer_correctness,  # 답변 정확도: ground truth 대비 사실적 정확도 (ground_truth 필요)
)

_DIR = Path(__file__).parent
EVAL_LOG_PATH  = str(_DIR / "eval_logs")
EVAL_DATA_PATH = str(_DIR / "eval_data.xlsx")

# 결과 파일명에 붙일 모델 태그 (다른 모델 결과와 섞이지 않도록 구분)
_MODEL_TAG = "gpt-5.6-luna"


# ==================== Ragas용 LLM/임베딩 ====================
def _get_ragas_llm():
    """judge LLM: 답변 생성 모델(gpt-5.6-luna)과 무관하게 안정성을 위해 gpt-4o-mini 고정"""
    from ragas.llms import llm_factory
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return llm_factory("gpt-4o-mini", client=client)


def _get_ragas_embeddings():
    """
    Ragas는 내부적으로 embed_text()를 호출하므로
    LangchainEmbeddingsWrapper로 감싸야 answer_correctness가 정상 동작함.
    """
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import OpenAIEmbeddings
    from config import (
        PROVIDER,
        UPSTAGE_API_KEY, UPSTAGE_EMBED_BASE_URL, UPSTAGE_EMBED_MODEL,
        OPENAI_API_KEY, OPENAI_EMBED_MODEL,
    )
    if PROVIDER == "upstage":
        lc_emb = OpenAIEmbeddings(
            api_key=UPSTAGE_API_KEY,
            base_url=UPSTAGE_EMBED_BASE_URL,
            model=UPSTAGE_EMBED_MODEL,
        )
    else:
        lc_emb = OpenAIEmbeddings(
            api_key=OPENAI_API_KEY,
            model=OPENAI_EMBED_MODEL,
        )
    return LangchainEmbeddingsWrapper(lc_emb)


# ==================== sources_info → contexts 변환 ====================
def _build_contexts(sources_info: dict) -> list[str]:
    contexts = []

    for doc in sources_info.get("web_docs", []):
        prefix = f"[웹] {doc.get('title', '')} ({doc.get('url', '')})\n"
        contexts.append(prefix + doc.get("content", ""))

    for doc in sources_info.get("book_docs", []):
        prefix = f"[책] {doc.get('book', '')} p{doc.get('page', '')}\n"
        contexts.append(prefix + doc.get("content", ""))

    for doc in sources_info.get("video_docs", []):
        prefix = f"[영상] {doc.get('title', '')} ({int(doc.get('start', 0))}s~{int(doc.get('end', 0))}s)\n"
        contexts.append(prefix + doc.get("content", ""))

    return contexts


# ==================== 핵심 평가 함수 ====================
def evaluate_response(
    question:     str,
    answer:       str,
    sources_info: dict,
    ground_truth: Optional[str] = None,
    duration:     Optional[float] = None,
) -> dict:
    print("\n" + "=" * 60)
    print("===== Ragas 평가 시작 =====")
    print("=" * 60)

    contexts = _build_contexts(sources_info)
    if not contexts:
        print("⚠️ 검색된 문서가 없어 평가를 건너뜁니다.")
        return {}

    data = {
        "question": [question],
        "answer":   [answer],
        "contexts": [contexts],
    }
    if ground_truth:
        data["ground_truth"] = [ground_truth]

    dataset = Dataset.from_dict(data)

    from llm_factory import get_model_info
    model_info       = get_model_info()   # 현재 PROVIDER/LLM_MODEL 정보를 결과에 같이 기록
    ragas_llm        = _get_ragas_llm()
    ragas_embeddings = _get_ragas_embeddings()

    metrics = [faithfulness, answer_relevancy, context_precision]
    if ground_truth:
        metrics.append(context_recall)
        metrics.append(answer_correctness)

    for metric in metrics:
        metric.llm        = ragas_llm
        metric.embeddings = ragas_embeddings

    print(f"📊 평가 지표: {[m.name for m in metrics]}")
    print(f"📄 컨텍스트 수: {len(contexts)}개\n")

    result_df = evaluate(dataset, metrics=metrics).to_pandas()

    result = {
        "question":          question,
        "answer":            answer,
        "contexts":          contexts,
        "faithfulness":      round(float(result_df["faithfulness"].iloc[0]),      4),
        "answer_relevancy":  round(float(result_df["answer_relevancy"].iloc[0]),  4),
        "context_precision": round(float(result_df["context_precision"].iloc[0]), 4),
        **model_info,
    }
    if duration is not None:
        result["duration"] = round(duration, 2)
    if ground_truth:
        result["context_recall"]     = round(float(result_df["context_recall"].iloc[0]),     4)
        result["answer_correctness"] = round(float(result_df["answer_correctness"].iloc[0]),  4)

    print("✅ 평가 완료!")
    print(f"   faithfulness      : {result['faithfulness']}")
    print(f"   answer_relevancy  : {result['answer_relevancy']}")
    print(f"   context_precision : {result['context_precision']}")
    if ground_truth:
        print(f"   context_recall    : {result['context_recall']}")
        print(f"   answer_correctness: {result['answer_correctness']}")
    print("=" * 60 + "\n")

    return result


# ==================== 결과 저장 ====================
def save_eval_result(result: dict, path: str = EVAL_LOG_PATH):
    if not result:
        return
    import json
    os.makedirs(path, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")

    jsonl_path = os.path.join(path, f"eval_{_MODEL_TAG}_{date_str}.jsonl")
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    txt_path = os.path.join(path, f"eval_{_MODEL_TAG}_{date_str}.txt")
    lines = [
        f"Q: {result['question']}",
        f"A: {result['answer']}",
    ]
    if result.get("answer_generated") is False:
        lines.append("[답변 생성 중단]")
    else:
        score_parts = [
            f"faithfulness: {result.get('faithfulness', '-')}",
            f"answer_relevancy: {result.get('answer_relevancy', '-')}",
            f"context_precision: {result.get('context_precision', '-')}",
            f"context_recall: {result.get('context_recall', '-')}",
            f"answer_correctness: {result.get('answer_correctness', '-')}",
        ]
        lines.append(" | ".join(score_parts))
        lines.append(f"answer_model: {result.get('answer_model', '-')} | judge_model: {result.get('judge_model', '-')}")
    lines.append("=" * 60)
    with open(txt_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"💾 평가 결과 저장: {jsonl_path}, {txt_path}")


# ==================== 평가용 질문 데이터 로드 ====================
def load_eval_data(path: str = EVAL_DATA_PATH) -> list[dict]:
    import pandas as pd

    if not os.path.exists(path):
        raise FileNotFoundError(f"평가 데이터 파일을 찾을 수 없습니다: {path}")

    df = pd.read_excel(path, header=0, usecols=[0, 1])
    df.columns = ["question", "ground_truth"]
    df = df.dropna(subset=["question"])

    records = df.to_dict(orient="records")
    print(f"📋 평가 데이터 로드: {len(records)}개 ({path})")
    return records


# ==================== RAG 실행 ====================
def run_rag(question: str) -> tuple[str, dict]:
    from bbot_graph_luna import generate   # gpt-5.6-luna 전용 그래프 사용
    return generate(question)


# ==================== 배치 평가 실행 ====================
async def main(limit: Optional[int] = 5):
    print("\n===== RAGAS BATCH EVALUATION START (gpt-5.6-luna) =====\n")

    eval_data = load_eval_data()
    eval_data = eval_data if limit is None else eval_data[:limit]
    total_str = "전체" if limit is None else f"{limit}개 제한"
    print(f"🔢 평가 대상: {len(eval_data)}개 ({total_str})\n")

    for item in eval_data:
        q  = item["question"]
        gt = item["ground_truth"]

        print(f"\n질문: {q}")
        t0 = time.time()
        answer, sources_info = run_rag(q)
        elapsed = time.time() - t0

        if not sources_info:
            skipped = {
                "question":         q,
                "answer":           answer,
                "contexts":         [],
                "answer_generated": False,
                "duration":         round(elapsed, 2),
            }
            if gt:
                skipped["ground_truth"] = gt
            save_eval_result(skipped)
            print("📝 답변 생성 중단 → 기록 완료 (평가 건너뜀)\n")
            continue

        result = evaluate_response(
            question=q,
            answer=answer,
            sources_info=sources_info,
            ground_truth=gt,
            duration=elapsed,
        )
        if result:
            save_eval_result(result)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="평가할 질문 수 (기본값: 5, 전체: -1)")
    args = parser.parse_args()

    limit = None if args.limit == -1 else args.limit
    asyncio.run(main(limit=limit))