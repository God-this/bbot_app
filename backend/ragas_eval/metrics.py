"""RAGAS 메트릭 구성 + composite_score 계산 + 판정.

ground truth 라벨이 없으므로 reference-free 메트릭만 쓴다
(context_recall / answer_correctness는 사용 불가).

이 모듈은 ragas에 의존하므로 배치 프로세스에서만 import할 것.
"""

import os

from logging_config import get_logger

logger = get_logger(__name__)

# ==================== 가중치 ====================
# faithfulness를 크게 두는 이유(spec §6.1):
#  1) 이 프로젝트에서 중요한 것은 "검색된 창조과학 자료에 실제로 근거했는가"
#  2) 시스템 프롬프트가 답변 말미에 성경 구절 인용과 묵상 문구를 요구하는데,
#     이 부분은 질문과 직접 관련이 없어 answer_relevancy를 구조적으로 깎는다.
#     실측에서도 타당한 답변이 0.36을 받았다 → 가중치를 낮게 두어 보정.
WEIGHTS = {
    "faithfulness": 0.60,
    "context_precision": 0.25,
    "answer_relevancy": 0.15,
}

# ==================== 판정 임계값 ====================
# ④단계에서 실제 점수 분포를 보고 확정한다. DRY_RUN=True인 동안에는
# 어떤 값이든 캐시를 건드리지 않으므로 아래 값은 '분포 관찰용 잠정치'다.
# 근거 없는 숫자를 확정값처럼 쓰지 말 것.
KEEP_THRESHOLD = float(os.getenv("RAGAS_KEEP_THRESHOLD", "0.70"))
DELETE_THRESHOLD = float(os.getenv("RAGAS_DELETE_THRESHOLD", "0.50"))

VERDICT_KEEP = "keep"
VERDICT_REVIEW = "review"
VERDICT_DELETED = "deleted"
VERDICT_WOULD_DELETE = "would_delete"


def build_metrics(llm, embeddings):
    """평가에 쓸 메트릭 인스턴스 3종을 만든다."""
    from ragas.metrics.collections import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
    )
    return {
        "faithfulness": Faithfulness(llm=llm),
        "context_precision": ContextPrecisionWithoutReference(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
    }


async def score_one(metrics: dict, question: str, answer: str, contexts: list[str]) -> dict:
    """한 건을 평가해 {메트릭명: 점수 or None}을 반환.

    메트릭 하나가 실패해도 나머지는 살린다 — 한 건 때문에 배치 전체를
    멈추지 않기 위해서다. 실패한 메트릭은 None으로 남고 composite 계산에서 빠진다.
    """
    scores = {}

    for name, metric in metrics.items():
        try:
            if name == "answer_relevancy":
                # answer_relevancy는 contexts를 받지 않는다 (question + answer만).
                result = await metric.ascore(user_input=question, response=answer)
            else:
                result = await metric.ascore(
                    user_input=question, response=answer, retrieved_contexts=contexts
                )
            value = getattr(result, "value", None)
            scores[name] = float(value) if value is not None else None
        except Exception as e:
            logger.warning("메트릭 %s 계산 실패: %s", name, e)
            scores[name] = None

    return scores


def composite_score(scores: dict) -> float | None:
    """가중 평균. 일부 메트릭이 실패(None)하면 남은 것들의 가중치를 정규화한다.

    정규화하지 않으면 실패한 메트릭이 0점처럼 작용해 멀쩡한 답변이
    삭제 판정을 받는다. 전부 실패하면 None — 판정 자체를 보류한다.
    """
    total_weight = 0.0
    acc = 0.0

    for name, weight in WEIGHTS.items():
        value = scores.get(name)
        if value is None:
            continue
        acc += value * weight
        total_weight += weight

    if total_weight == 0:
        return None

    return acc / total_weight


def decide(score: float | None, dry_run: bool) -> tuple[str, str]:
    """(verdict, reason) 반환.

    3단계 구조 — 단일 컷으로 즉시 삭제하지 않는다(spec §6.2).
      score >= KEEP           → keep
      DELETE <= score < KEEP  → review (캐시는 유지, 관리자 검토 대상)
      score <  DELETE         → deleted / would_delete
    """
    if score is None:
        # 점수를 못 낸 항목은 삭제 후보로 보지 않는다. 다음 회차에 재시도되지도
        # 않으므로(evaluated_at이 찍힌다) 관리자 검토로 넘긴다.
        return VERDICT_REVIEW, "scoring_failed"

    if score >= KEEP_THRESHOLD:
        return VERDICT_KEEP, "ok"

    if score >= DELETE_THRESHOLD:
        return VERDICT_REVIEW, "below_keep_threshold"

    verdict = VERDICT_WOULD_DELETE if dry_run else VERDICT_DELETED
    return verdict, "composite_low"
