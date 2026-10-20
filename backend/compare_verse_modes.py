"""
compare_verse_modes.py — 성경 구절 검증 방식 비교 (code / tool / tool_nonet)

질문마다 LLM 답변을 **한 번만** 스트리밍으로 생성해 토큰과 도착 시각을 기록하고,
같은 토큰 흐름에 각 검증 방식을 적용해 비교한다. (답변이 같아야 방식끼리 공정하게 비교된다)

  code        : 코드로 바로 검증 (LLM 추가 호출 없음)
  tool        : 구절이 있을 때만 LLM 툴콜링 검증 + code 안전장치
  tool_nonet  : LLM 툴콜링 검증만 (안전장치 끔) — LLM 단독 성능 측정용

캐시와 입력 가드레일은 거치지 않는다 (검색 → 답변 생성 → 검증만).
성경 원문은 방식을 돌리기 전에 미리 캐시해, DB 접속 시간은 검증 시간에서 뺀다.

사용
  python compare_verse_modes.py                       # 내장 질문 20개, 세 방식 모두
  python compare_verse_modes.py --limit 3             # 앞 3개만 (빠른 확인)
  python compare_verse_modes.py --modes code,tool     # 방식 선택
  python compare_verse_modes.py --questions q.txt     # 한 줄에 질문 하나
  python compare_verse_modes.py --start 5 --limit 2 --out r.csv   # 5~6번만, r.csv에 이어 쓰기

출력
  bible_test_logs/verse_compare_YYYYMMDD_HHMM.csv    (질문 × 방식별 한 줄, 엑셀에서 바로 열림)
  터미널에 방식별 평균 요약

시간 항목 (초, 답변 생성 시작 기준)
  생성시간     : LLM이 답변 마지막 토큰을 보낸 시각
  첫글자       : 사용자 화면에 첫 글자가 나가는 시각
  완료시간     : 사용자 화면에 답변이 다 나가는 시각 (= 생성시간 + 검증에 쓴 시간)
  바로출력비율 : 답변 중 LLM 검증을 기다리지 않고 생성 즉시 나간 글자 비율
"""
import argparse
import csv
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import bible_verify
from bible_verify import VerseStreamFilter, APPENDIX_HEADER
from bbot_graph import (
    client, create_graph, recent_turns_to_history, resolve_question,
    reasoning_kwargs, _verse_llm, LLM_MODEL,
)

DEFAULT_QUESTIONS = [
    # 창조
    "하나님은 세상을 며칠 만에 창조하셨나요?",
    "창세기 1장의 하루는 문자 그대로 24시간인가요?",
    "사람은 어떻게 창조되었나요?",
    "하와는 왜 아담의 갈빗대로 만들어졌나요?",
    # 홍수·방주
    "노아의 홍수는 실제 있었던 사건인가요?",
    "노아의 방주에 모든 동물이 들어갈 수 있었나요?",
    "홍수 이후 무지개는 어떤 의미인가요?",
    # 지구 나이·지질
    "지구의 나이는 몇 년인가요?",
    "그랜드캐니언은 어떻게 만들어졌나요?",
    "화석은 어떻게 만들어지나요?",
    # 진화론
    "진화론은 과학적으로 증명된 사실인가요?",
    "사람과 원숭이는 공통 조상에서 나왔나요?",
    "유신론적 진화론은 성경과 맞나요?",
    # 생물·설계
    "공룡은 사람과 같은 시대에 살았나요?",
    "DNA의 정보는 설계의 증거인가요?",
    "사람의 눈은 진화로 설명할 수 있나요?",
    # 기타
    "바벨탑 사건 이후 언어는 어떻게 나뉘었나요?",
    "죽음은 언제부터 세상에 들어왔나요?",
    # 영어 / 인용 직접 요청
    "Did God create the universe in six days?",
    "창조에 관한 성경 구절 세 개를 정확히 인용해 주세요",
]

ALL_MODES = ["code", "tool", "tool_nonet"]
STATUSES = ["ok", "missing", "replaced", "quote_dropped"]


# ==================== 1. 답변 한 번 생성 (토큰 기록) ====================

def generate_tokens(question: str) -> tuple[list[tuple[float, str]] | None, str]:
    """검색 → 답변 스트리밍. [(도착 시각, 토큰)], 상태 메시지"""
    standalone = resolve_question(question, None)
    graph_result = create_graph().invoke({
        "question": question, "rewritten_question": "", "route": "", "documents": [],
        "judgement": "", "iteration": 0, "chat_history": recent_turns_to_history(None),
        "qualified_documents": [], "reranked_documents": [], "sources": {},
        "final_messages": [], "fallback_message": "", "standalone_question": standalone,
    })
    if graph_result.get("fallback_message"):
        return None, "fallback (자료 부족으로 답변 생성 안 함)"

    t0 = time.time()
    stream = client.chat.completions.create(
        model=LLM_MODEL, messages=graph_result["final_messages"], temperature=0,
        stream=True, name="compare-verse-modes", **reasoning_kwargs(),
    )
    tokens = []
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            tokens.append((time.time() - t0, delta))
    return tokens, "ok"


# ==================== 2. 같은 토큰 흐름에 검증 방식 적용 ====================

def run_mode(tokens: list[tuple[float, str]], mode: str) -> dict:
    real_mode = "tool" if mode.startswith("tool") else mode
    saved_net = bible_verify.VERSE_TOOL_SAFETY_NET
    bible_verify.VERSE_TOOL_SAFETY_NET = (mode != "tool_nonet")
    try:
        vf = VerseStreamFilter(mode=real_mode, llm=_verse_llm)
        lag = 0.0                    # 필터 처리(DB 조회 등)에 쓴 누적 시간 → 출력이 그만큼 늦어짐
        first_emit = None
        immediate = 0
        out_parts = []
        for t, delta in tokens:
            s = time.time()
            out = vf.feed(delta)
            lag += time.time() - s
            if out:
                first_emit = first_emit if first_emit is not None else t + lag
                immediate += len(out)
                out_parts.append(out)
        s = time.time()
        tail = vf.finish()
        finish_time = time.time() - s
        lag += finish_time
        out_parts.append(tail)
    finally:
        bible_verify.VERSE_TOOL_SAFETY_NET = saved_net

    raw = "".join(d for _, d in tokens)
    final = "".join(out_parts)
    body = final.split("\n\n" + APPENDIX_HEADER)[0]
    gen_end = tokens[-1][0] if tokens else 0.0
    summary = vf.summary()
    counts = Counter(r["status"] for r in summary["code"])
    if first_emit is None:          # 바로 나간 글자가 없으면 검증이 끝난 뒤 첫 글자가 나감
        first_emit = gen_end + lag
    return {
        "생성시간": round(gen_end, 2),
        "첫글자": round(first_emit, 2),
        "완료시간": round(gen_end + lag, 2),
        "검증시간": round(lag, 2),
        # 참고 구절 블록은 빼고 답변 본문 기준으로 계산
        "바로출력비율": f"{min(immediate, len(body)) / max(len(body), 1):.0%}",
        "구절수(code판정)": len(summary["code"]),
        **{f"code_{k}": counts.get(k, 0) for k in STATUSES},
        "tool상태": summary.get("tool_status", ""),
        "도구호출수": len(summary.get("tool_calls", [])),
        "도구호출내역": "; ".join(str(c.get("result") or c.get("error")) for c in summary.get("tool_calls", [])),
        "답변변경": "O" if final != raw else "",
        "원답변": raw,
        "최종답변": final,
    }


# ==================== 3. 실행 ====================

def load_questions(args) -> list[str]:
    if args.questions:
        qs = [l.strip() for l in open(args.questions, encoding="utf-8") if l.strip()]
    else:
        qs = list(DEFAULT_QUESTIONS)
    qs = qs[args.start - 1:]
    return qs[: args.limit] if args.limit else qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", help="질문 txt (한 줄에 하나)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (0=전체)")
    ap.add_argument("--modes", default=",".join(ALL_MODES), help="쉼표로 구분: code,tool,tool_nonet")
    ap.add_argument("--start", type=int, default=1, help="N번째 질문부터 (나눠서 돌릴 때)")
    ap.add_argument("--out", help="결과 CSV 경로. 이미 있으면 이어서 쓴다 (나눠서 돌릴 때 하나로 모으기)")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in ALL_MODES:
            ap.error(f"알 수 없는 방식: {m}")

    questions = load_questions(args)
    out_dir = Path(__file__).parent / "bible_test_logs"
    out_dir.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else out_dir / f"verse_compare_{datetime.now():%Y%m%d_%H%M}.csv"

    rows = []
    last = args.start + len(questions) - 1
    for i, q in enumerate(questions, args.start):
        print(f"\n[{i}/{last}] {q}")
        try:
            tokens, status = generate_tokens(q)
        except Exception as e:
            print(f"   답변 생성 실패: {e}")
            rows.append({"번호": i, "질문": q, "방식": "-", "에러": f"생성 실패: {e}"})
            continue
        if tokens is None:
            print(f"   {status}")
            rows.append({"번호": i, "질문": q, "방식": "-", "에러": status})
            continue
        # 원문 캐시를 미리 채워 DB 접속 시간은 비교에서 뺀다 (먼저 도는 방식만 DB 비용을 내는 불공정 방지).
        # 서버에서는 DB가 같은 컴퓨터라 조회가 몇 ms라서, 로컬 SSH 터널의 1~2초는 실제와 다르다.
        bible_verify.verify_answer("".join(d for _, d in tokens), mode="code")
        for mode in modes:
            try:
                r = run_mode(tokens, mode)
                print(f"   {mode:<10} 완료 {r['완료시간']:>6}s  첫글자 {r['첫글자']:>6}s  "
                      f"바로출력 {r['바로출력비율']:>4}  구절 {r['구절수(code판정)']}  "
                      f"도구 {r['도구호출수']}  변경 {r['답변변경'] or '-'}")
                rows.append({"번호": i, "질문": q, "방식": mode, **r, "에러": ""})
            except Exception as e:
                print(f"   {mode} 실패: {e}")
                rows.append({"번호": i, "질문": q, "방식": mode, "에러": str(e)})

    fields = ["번호", "질문", "방식", "생성시간", "첫글자", "완료시간", "검증시간", "바로출력비율",
              "구절수(code판정)", *[f"code_{k}" for k in STATUSES], "tool상태", "도구호출수",
              "도구호출내역", "답변변경", "에러", "원답변", "최종답변"]
    append = out_path.exists() and out_path.stat().st_size > 0
    with open(out_path, "a" if append else "w", encoding="utf-8" if append else "utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not append:
            w.writeheader()
        w.writerows(rows)

    print("\n==================== 방식별 평균 ====================")
    for mode in modes:
        rs = [r for r in rows if r.get("방식") == mode and not r.get("에러")]
        if not rs:
            continue
        avg = lambda k: sum(r[k] for r in rs) / len(rs)
        print(f"{mode:<10} n={len(rs):<3} 완료 {avg('완료시간'):6.2f}s  첫글자 {avg('첫글자'):5.2f}s  "
              f"검증 {avg('검증시간'):5.2f}s  도구호출 {avg('도구호출수'):.1f}회  "
              f"답변변경 {sum(1 for r in rs if r['답변변경'])}건")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
