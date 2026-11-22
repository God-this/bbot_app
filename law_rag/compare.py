"""4단계: 같은 질문을 세 방식으로 돌려 한 표로 비교.

입력: questions.csv (id, domain, question, gold)
  gold = 정답 조문. 여러 개면 ';'로. 예) 주택임대차보호법 제3조; 주택임대차보호법 제3조의2
출력: results/compare_<시각>.csv  — 한 줄 = 질문 하나, 방식별 답변·인용·판정이 옆으로
      results/compare_<시각>.md   — 방식별 요약 점수 + 질문별 O/X 표

채점 (코드로 계산)
  - 정답 인용   : 답변이 인용한 조문 중 gold가 하나라도 있으면 O
  - 없는 조문   : 답변이 인용했는데 DB에 없는 조문 수 (지어낸 조문)
  - 검색 적중   : RAG 방식에서 검색·조회로 가져온 조문에 gold가 있었는지
                  (적중 O인데 정답 인용 X → 생성 문제 / 적중 X → 검색 문제)

실행: python compare.py                      (전체)
      python compare.py --domain jeonse      (한 분야)
      python compare.py --modes no_rag tool_rag
"""
import argparse
import csv
import re
from datetime import datetime

import config
import retriever
from answer import MODES


def law_names() -> list[str]:
    names = {n for ns in config.DOMAINS.values() for n in ns}
    return sorted(names, key=len, reverse=True)  # 긴 이름 먼저 ('도로교통법 시행령' > '도로교통법')


def extract_citations(text: str, names: list[str] | None = None) -> list[str]:
    """답변에서 '법령명 제N조(의M)' 인용을 'law|N(의M)' 목록으로 뽑는다.
    법령명 없이 이어지는 '제45조'는 바로 앞에 나온 법령명으로 본다."""
    names = names or law_names()
    name_re = "|".join(re.escape(n) for n in names)
    # '제148조의2'와 '제148의2조' 두 표기 모두 인식
    token = re.compile(rf"(?P<law>{name_re})|제\s*(?P<no>\d+)\s*(?:조(?:\s*의\s*(?P<br>\d+))?|의\s*(?P<br2>\d+)\s*조)")
    out, current = [], None
    for m in token.finditer(text):
        if m.group("law"):
            current = m.group("law")
        elif current:
            br = m.group("br") or m.group("br2")
            key = f"{current}|{m.group('no')}" + (f"의{br}" if br else "")
            if key not in out:
                out.append(key)
    return out


def parse_gold(gold: str) -> list[str]:
    return extract_citations(gold.replace(";", " "))


def exists(key: str) -> bool:
    law, no = key.split("|")
    return retriever.get_article(law, no) is not None


def run(questions: list[dict], modes: list[str]) -> list[dict]:
    rows = []
    for q in questions:
        gold = parse_gold(q["gold"])
        missing_gold = [g for g in gold if not exists(g)]
        if missing_gold:
            print(f"  ! {q['id']}: 정답 조문이 DB에 없음 {missing_gold} (개정으로 번호가 바뀌었는지 확인)")
        row = {"id": q["id"], "domain": q["domain"], "question": q["question"], "gold": ", ".join(gold)}
        for mode in modes:
            r = MODES[mode](q["question"], q["domain"] or None)
            cited = extract_citations(r.answer)
            row[f"{mode}_answer"] = r.answer
            row[f"{mode}_cited"] = ", ".join(cited)
            row[f"{mode}_correct"] = "O" if set(cited) & set(gold) else "X"
            row[f"{mode}_fake"] = sum(not exists(c) for c in cited)
            row[f"{mode}_hit"] = ("O" if set(r.retrieved) & set(gold) else "X") if mode != "no_rag" else "-"
            row[f"{mode}_tools"] = len(r.tool_calls)
            row[f"{mode}_sec"] = round(r.seconds, 1)
            print(f"{q['id']} {mode:10s} 정답인용 {row[f'{mode}_correct']}  "
                  f"없는조문 {row[f'{mode}_fake']}  검색적중 {row[f'{mode}_hit']}  {r.seconds:.1f}s")
        rows.append(row)
    return rows


def summary_md(rows: list[dict], modes: list[str]) -> str:
    n = len(rows)
    lines = ["# 세 방식 비교", "", f"- 실행: {datetime.now():%Y-%m-%d %H:%M} · 모델 {config.LLM_MODEL} · "
             f"임베딩 {config.EMBED_MODEL} · top-k {config.TOP_K} · 질문 {n}개", "",
             "| 방식 | 정답 조문 인용 | 없는 조문 지어냄 | 검색 적중 | 평균 툴 호출 | 평균 시간 |",
             "|---|---|---|---|---|---|"]
    for m in modes:
        correct = sum(r[f"{m}_correct"] == "O" for r in rows)
        fake = sum(r[f"{m}_fake"] for r in rows)
        hit = "-" if m == "no_rag" else f"{sum(r[f'{m}_hit'] == 'O' for r in rows)}/{n}"
        tools = sum(r[f"{m}_tools"] for r in rows) / n if n else 0
        sec = sum(r[f"{m}_sec"] for r in rows) / n if n else 0
        lines.append(f"| {m} | {correct}/{n} | {fake}건 | {hit} | {tools:.1f} | {sec:.1f}초 |")
    lines += ["", "## 질문별", "", "| id | 질문 | 정답 | " + " | ".join(modes) + " |",
              "|---|---|---|" + "---|" * len(modes)]
    for r in rows:
        cells = [f"{r[f'{m}_correct']} ({r[f'{m}_cited'] or '인용 없음'})" for m in modes]
        lines.append(f"| {r['id']} | {r['question']} | {r['gold']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(config.ROOT / "questions.csv"))
    ap.add_argument("--domain")
    ap.add_argument("--modes", nargs="+", default=list(MODES))
    a = ap.parse_args()

    with open(a.questions, encoding="utf-8-sig") as f:
        qs = [q for q in csv.DictReader(f) if not a.domain or q["domain"] == a.domain]
    rows = run(qs, a.modes)

    config.RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = config.RESULTS_DIR / f"compare_{stamp}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md_path = config.RESULTS_DIR / f"compare_{stamp}.md"
    md_path.write_text(summary_md(rows, a.modes), encoding="utf-8")
    print(f"\n저장: {csv_path}\n      {md_path}")


if __name__ == "__main__":
    main()
