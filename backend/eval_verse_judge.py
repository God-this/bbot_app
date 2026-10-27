"""
eval_verse_judge.py — 맥락·주소 판정(LLM) 오프라인 평가

compare_verse_modes.py가 저장한 답변(원답변)을 다시 쓰고, 답변마다
  1·2단계(코드) 구절 검출·표시 → 3단계(LLM) 판정 → 4단계(코드) 반영
을 돌려 **구절별 판정 결과**를 CSV로 저장한다. 사람이 '사람판정' 칸에 O/X를 적어
LLM 판정의 정확도를 잰다. (서비스 답변 흐름과 무관, 캐시·검색 없음)

사용
  python eval_verse_judge.py                                   # 가장 최근 verse_compare_*.csv
  python eval_verse_judge.py --csv bible_test_logs/verse_compare_20261021.csv
  python eval_verse_judge.py --start 1 --limit 10 --out r.csv  # 나눠서 돌리기 (이어 쓰기)

출력
  <out>.csv          구절별 한 줄 — 판정, 이유, 추천 주소, 코드 반영 결과, 사람판정(빈칸)
  <out>_answers.csv  답변별 한 줄 — code 방식 결과 vs 판정 반영 결과
"""
import argparse
import csv
import glob
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from bible_verify import REF_RE, apply_verdicts, find_citations, parse_ref, ref_exists, ref_text, verify_answer
from bible_verse_judge import make_judge
from config import LLM_MODEL
from llm_factory import get_client
from utils import reasoning_kwargs

KIND_KO = {"quoted": "따옴표 인용", "paren": "괄호 출처", "inline": "문장 속 언급"}
YN = {True: "예", False: "아니오", None: "-"}


def load_answers(path: str) -> list[tuple[str, str, str]]:
    """(번호, 질문, 원답변) — 질문마다 한 번"""
    seen, out = set(), []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r.get("에러") or not r.get("원답변") or r["번호"] in seen:
            continue
        seen.add(r["번호"])
        out.append((r["번호"], r["질문"], r["원답변"]))
    return out


def suggested_text(ref_str) -> str:
    m = REF_RE.search(str(ref_str or ""))
    if not m:
        return ""
    ref = parse_ref(m)
    if not ref_exists(ref) or ref.v1 is None:
        return "(존재하지 않음)" if not ref_exists(ref) else ""
    return ref_text(ref) if ref.is_short else "(4절 이상)"


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    append = path.exists() and path.stat().st_size > 0
    with open(path, "a" if append else "w", encoding="utf-8" if append else "utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not append:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="compare_verse_modes.py 결과 CSV (기본: 가장 최근)")
    ap.add_argument("--start", type=int, default=1, help="N번째 답변부터")
    ap.add_argument("--limit", type=int, default=0, help="N개만 (0=전체)")
    ap.add_argument("--out", help="결과 CSV 경로 (이미 있으면 이어 쓴다)")
    args = ap.parse_args()

    log_dir = Path(__file__).parent / "bible_test_logs"
    src = args.csv or max(glob.glob(str(log_dir / "verse_compare_*.csv")), default=None)
    if not src:
        ap.error("입력 CSV가 없습니다. compare_verse_modes.py를 먼저 돌리거나 --csv를 주세요.")
    answers = load_answers(src)[args.start - 1:]
    if args.limit:
        answers = answers[: args.limit]
    out = Path(args.out) if args.out else log_dir / f"verse_judge_eval_{datetime.now():%Y%m%d_%H%M}.csv"
    out_answers = out.with_name(out.stem + "_answers.csv")

    judge = make_judge(get_client(), LLM_MODEL, name="verse-judge-eval", **reasoning_kwargs())
    cit_rows, ans_rows = [], []
    for no, question, raw in answers:
        print(f"\n[{no}] {question}")
        cits = find_citations(raw)
        if not cits:
            print("   구절 없음")
            ans_rows.append({"번호": no, "질문": question, "구절수": 0, "판정반영_변경": ""})
            continue
        t = time.time()
        try:
            verdicts, tool_log = judge(text=raw, citations=cits)
            err = ""
        except Exception as e:
            verdicts, tool_log, err = [], [], str(e)
        secs = time.time() - t
        applied, applied_log = apply_verdicts(raw, cits, verdicts)
        code_only = verify_answer(raw)[0]
        with_judge = verify_answer(applied)[0]
        by_id = {e["id"]: e for e in applied_log}
        for c in cits:
            e = by_id.get(c.id, {})
            cit_rows.append({
                "번호": no, "질문": question, "구절id": c.id, "형태": KIND_KO.get(c.kind, c.kind),
                "주소": c.ref.label, "인용문": c.quote or "", "존재": YN[c.exists],
                "본문일치": YN[c.quote_match], "원문": c.original, "문맥": c.context,
                "LLM판정": e.get("verdict", "(판정 없음)"), "추천주소": e.get("suggested_ref") or "",
                "추천주소원문": suggested_text(e.get("suggested_ref")), "이유": e.get("reason", ""),
                "코드반영": e.get("applied", ""), "사람판정(O/X)": "", "올바른판정": "", "메모": "",
            })
        counts = Counter(e["verdict"] for e in applied_log)
        print(f"   구절 {len(cits)}  판정 {dict(counts)}  도구 {len(tool_log)}회  {secs:.1f}s"
              + (f"  에러: {err}" if err else ""))
        ans_rows.append({
            "번호": no, "질문": question, "구절수": len(cits), "판정시간": round(secs, 2),
            "도구호출수": len(tool_log),
            "도구호출내역": "; ".join(f"{x['tool']}({x['args']})→{x['result']}" for x in tool_log),
            **{f"판정_{k}": counts.get(k, 0) for k in ["ok", "wrong_ref", "quote_wrong", "context_mismatch", "not_found"]},
            "판정반영_변경": "O" if with_judge != code_only else "", "에러": err,
            "원답변": raw, "code결과": code_only, "판정반영결과": with_judge,
        })

    cit_fields = ["번호", "질문", "구절id", "형태", "주소", "인용문", "존재", "본문일치", "원문", "문맥",
                  "LLM판정", "추천주소", "추천주소원문", "이유", "코드반영", "사람판정(O/X)", "올바른판정", "메모"]
    ans_fields = ["번호", "질문", "구절수", "판정시간", "도구호출수", "도구호출내역", "판정_ok", "판정_wrong_ref",
                  "판정_quote_wrong", "판정_context_mismatch", "판정_not_found", "판정반영_변경", "에러",
                  "원답변", "code결과", "판정반영결과"]
    write_csv(out, cit_rows, cit_fields)
    write_csv(out_answers, ans_rows, ans_fields)

    total = Counter(r["LLM판정"] for r in cit_rows)
    print(f"\n구절 {len(cit_rows)}개 판정: {dict(total)}")
    print(f"저장: {out}\n      {out_answers}")


if __name__ == "__main__":
    main()
