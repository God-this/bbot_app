"""RAGAS 평가 배치 진입점.

실행:
    python -m ragas_eval.runner              # DRY_RUN (기본) — 캐시를 건드리지 않음
    python -m ragas_eval.runner --limit 50
    python -m ragas_eval.runner --execute    # 실제 삭제/tombstone 반영 (⑤단계)
    python -m ragas_eval.runner --report     # 평가는 하지 않고 분포/판정만 출력

DRY_RUN=True인 동안에는 mark_evaluated / delete_and_tombstone을 호출하지 않는다.
평가 결과는 ragas_evaluations에 verdict='would_delete'로만 쌓이고,
Redis 캐시는 그대로 유지된다(spec §6.3).

비용 주의: faithfulness는 답변을 statement 단위로 분해해 각각 검증하므로
1건당 수~십수 회 LLM 호출이 발생한다. --limit 없이 큰 큐를 돌리지 말 것.
"""

import argparse
import asyncio
import os

from logging_config import get_logger

from .queue_repo import fetch_pending, mark_queue_evaluated
from .result_repo import save_evaluation, score_distribution, verdict_summary

logger = get_logger(__name__)

BATCH_LIMIT = int(os.getenv("RAGAS_BATCH_LIMIT", "200"))

# 동시 실행 수. faithfulness 1건이 LLM을 여러 번 부르므로 과하게 올리면
# rate limit에 걸린다. 배치는 급할 일이 없으니 보수적으로 둔다.
CONCURRENCY = int(os.getenv("RAGAS_CONCURRENCY", "3"))


async def _evaluate_all(items: list[dict], metrics: dict) -> list[tuple[dict, dict]]:
    """큐 항목들을 제한된 동시성으로 평가. (item, scores) 목록 반환."""
    from .metrics import score_one

    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(items)

    async def one(item):
        nonlocal done
        async with sem:
            contexts = item["contexts"] or []
            scores = await score_one(
                metrics, item["original_question"], item["answer"], contexts
            )
            done += 1
            logger.info("[%d/%d] %s → %s", done, total, item["original_question"][:40], scores)
            return item, scores

    return await asyncio.gather(*(one(i) for i in items))


def run_batch(limit: int = BATCH_LIMIT, dry_run: bool = True) -> dict:
    """큐에서 미평가 항목을 꺼내 평가하고 결과를 기록한다.

    Returns: 처리 요약 dict
    """
    from .judge import build_judge, get_ragas_version
    from .metrics import build_metrics, composite_score, decide, VERDICT_DELETED, VERDICT_KEEP

    items = fetch_pending(limit)
    if not items:
        logger.info("평가 대기 항목 없음")
        return {"processed": 0}

    logger.info(
        "평가 시작 — %d건, dry_run=%s (dry_run이면 캐시를 수정하지 않는다)",
        len(items), dry_run
    )

    llm, embeddings, judge_provider, judge_model = build_judge()
    metrics = build_metrics(llm, embeddings)
    ragas_version = get_ragas_version()

    results = asyncio.run(_evaluate_all(items, metrics))

    # 캐시 조작은 ⑤단계에서만. import 자체를 dry_run이 아닐 때로 미루지 않는 이유는
    # Redis가 없는 환경에서 배치를 돌릴 일이 없기 때문이다.
    from redis_cache import mark_evaluated, delete_and_tombstone

    counts = {}
    evaluated_ids = []

    for item, scores in results:
        composite = composite_score(scores)
        verdict, reason = decide(composite, dry_run)
        counts[verdict] = counts.get(verdict, 0) + 1

        save_evaluation(
            cache_key=item["cache_key"],
            normalized_question=item["normalized_question"],
            original_question=item["original_question"],
            answer=item["answer"],
            contexts=item["contexts"] or [],
            context_char_limit=item["context_char_limit"],
            scores=scores,
            composite=composite,
            verdict=verdict,
            dry_run=dry_run,
            ragas_version=ragas_version,
            judge_provider=judge_provider,
            judge_model=judge_model,
        )

        if not dry_run:
            # ⑤단계: 실제 반영
            try:
                if verdict == VERDICT_DELETED:
                    delete_and_tombstone(
                        item["normalized_question"], composite, reason,
                        item["original_question"],
                    )
                elif composite is not None:
                    # keep / review 모두 캐시는 유지하고 passed로 전환한다.
                    # review는 관리자 검토 대상일 뿐 서빙을 막지 않는다(spec §6.2).
                    mark_evaluated(item["normalized_question"], composite)
            except Exception as e:
                # 캐시 반영 실패가 큐 소진을 막으면 같은 항목을 무한 재평가하게 된다.
                logger.error("캐시 반영 실패 (%s): %s", item["normalized_question"], e)

        evaluated_ids.append(item["id"])

    # 평가 결과를 저장한 뒤에 큐를 소진 처리한다. 순서가 바뀌면 중간에 죽었을 때
    # 결과 없이 evaluated_at만 찍혀 항목이 영영 평가되지 않는다.
    marked = mark_queue_evaluated(evaluated_ids)

    summary = {"processed": len(results), "queue_marked": marked, "verdicts": counts,
               "dry_run": dry_run, "judge": f"{judge_provider}/{judge_model}"}
    logger.info("평가 완료 — %s", summary)
    return summary


def print_report():
    """수집된 점수 분포와 판정 요약 출력 (④단계 threshold 결정용)."""
    print("\n=== 판정 요약 (verdict / 건수 / 평균 composite) ===")
    for row in verdict_summary():
        print(f"  {row[0]:<14} {row[1]:>5}  avg={row[2]}")

    for metric in ("faithfulness", "context_precision", "answer_relevancy", "composite_score"):
        rows = score_distribution(metric)
        if not rows:
            continue
        print(f"\n=== {metric} 분포 (bucket 1=0.0~0.1 … 10=0.9~1.0) ===")
        for bucket, cnt, avg in rows:
            bar = "#" * min(cnt, 50)
            print(f"  {bucket:>2} {cnt:>5} {avg}  {bar}")

    print(
        "\n주의: threshold는 이 분포만으로 정하지 말 것. "
        "하위 10~20% 구간의 실제 답변 20건을 직접 읽어보고 "
        "점수가 낮은 것이 정말 나쁜 답변인지 확인해야 한다 (spec §6.3-4)."
    )


def main():
    parser = argparse.ArgumentParser(description="RAGAS 캐시 품질 평가 배치")
    parser.add_argument("--limit", type=int, default=BATCH_LIMIT,
                        help=f"한 회차 처리 건수 (기본 {BATCH_LIMIT})")
    parser.add_argument("--execute", action="store_true",
                        help="실제로 캐시 삭제/tombstone을 반영한다 (⑤단계). "
                             "기본은 dry-run이라 캐시를 건드리지 않는다.")
    parser.add_argument("--report", action="store_true",
                        help="평가하지 않고 누적된 점수 분포만 출력")
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    summary = run_batch(limit=args.limit, dry_run=not args.execute)
    print(summary)


if __name__ == "__main__":
    main()
