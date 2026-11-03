"""pytest 공통 설정 — 성경 구절 검증 테스트의 항목별 점수와 결과 파일

test_verse_pipeline.py의 케이스(verse_test_cases.Case)는 group(케이스 나무 항목)을 갖고 있다.
테스트가 끝나면
  1. 터미널에 항목별 점수와 실패한 케이스를 보여주고
  2. backend/test_reports/에 케이스별 상세 결과를 저장한다
     - verse_<날짜_시각>.md  : 읽기용 (질문, 가짜 LLM 답변, 실제 출력, 바뀐 부분, 확인 항목별 통과 여부)
     - verse_<날짜_시각>.csv : 엑셀용 (한 줄 = 케이스 하나, 필터·정렬용)
     결과 파일에는 성경 본문이 들어가므로 저장소에 올리지 않는다 (.gitignore)
다른 테스트 파일에는 영향이 없다 (group이 없는 테스트는 세지 않음).
"""
import csv
import difflib
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

REPORT_DIR = Path(__file__).parent / "test_reports"

_results: dict[str, dict] = defaultdict(lambda: {"passed": 0, "failed": [], "xfailed": 0, "xpassed": []})
_records: list[dict] = []     # 케이스별 상세 (결과 파일용)


def _case_of(item):
    callspec = getattr(item, "callspec", None)
    return callspec.params.get("case") if callspec else None


def _short_msg(rep) -> str:
    crash = getattr(rep.longrepr, "reprcrash", None)
    msg = crash.message if crash else str(rep.longrepr)
    return msg.splitlines()[0].removeprefix("Failed: ")[:150]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    case = _case_of(item)
    if case is None or not hasattr(case, "group"):
        return
    res = _results[case.group]
    if rep.when == "setup" and rep.failed:
        res["failed"].append((case.id, "준비 단계 오류"))
        _records.append({"case": case, "result": "실패", "msg": "준비 단계 오류", "rec": {}})
        return
    if rep.when != "call":
        return
    if hasattr(rep, "wasxfail"):
        if rep.skipped:
            res["xfailed"] += 1
            result = "예상대로 실패"
        else:
            res["xpassed"].append((case.id, case.note))
            result = "통과 (todo 지우기)"
    elif rep.passed:
        res["passed"] += 1
        result = "통과"
    elif "XPASS(strict)" in str(rep.longrepr):
        res["xpassed"].append((case.id, case.note))
        result = "통과 (todo 지우기)"
    else:
        res["failed"].append((case.id, _short_msg(rep)))
        result = "실패"
    _records.append({"case": case, "result": result, "msg": "" if rep.passed else _short_msg(rep),
                     "rec": getattr(item, "verse_record", {})})


# ==================== 바뀐 부분 ====================

_TOKEN = re.compile(r"\s+|[^\s]+")


def changes(before: str, after: str) -> list[str]:
    """입력 → 출력에서 바뀐 부분을 사람이 읽을 수 있게 (삭제 / 추가 / 교체)

    어절 단위로 비교하고, 바뀐 곳 사이에 같은 어절이 두 개 이하로 끼어 있으면 한 덩어리로 묶는다.
    (글자 단위로 비교하면 '세상을 → 가라사대', '빛 추가'처럼 잘게 쪼개져 읽기 어렵다)
    """
    if before == after:
        return []
    a, b = _TOKEN.findall(before), _TOKEN.findall(after)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    blocks: list[list[int]] = []          # [a시작, a끝, b시작, b끝]
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if blocks:
            pa, pb = blocks[-1][1], blocks[-1][3]
            gap = [t for t in a[pa:i1] if not t.isspace()]
            if len(gap) <= 2 and i1 - pa == j1 - pb:
                blocks[-1][1], blocks[-1][3] = i2, j2
                continue
        blocks.append([i1, i2, j1, j2])
    out = []
    for i1, i2, j1, j2 in blocks:
        x, y = "".join(a[i1:i2]).strip(), "".join(b[j1:j2]).strip()
        if x and y:
            out.append(f"교체: {x!r} → {y!r}")
        elif x:
            out.append(f"삭제: {x!r}")
        elif y:
            out.append(f"추가: {y!r}")
    return out


# ==================== 터미널 점수표 ====================

def _w(s: str) -> int:
    """화면 폭 (한글은 2칸)"""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def _score_rows():
    from verse_test_cases import GROUPS
    rows = []
    for g, title in GROUPS.items():
        if g == "todo" or g not in _results:
            continue
        res = _results[g]
        rows.append((g, title, res["passed"], res["passed"] + len(res["failed"])))
    return rows


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def pytest_terminal_summary(terminalreporter):
    if not _results:
        return
    from verse_test_cases import GROUPS
    tr = terminalreporter
    tr.section("성경 구절 검증 테스트 점수")
    rows = _score_rows()
    for g, title, p, n in rows:
        mark = "" if p == n else f"   실패 {n - p}건"
        tr.write_line(f"{_pad(g, 8)}{_pad(title, 36)}{p:>4}/{n:<4}{mark}")
    total_pass, total = sum(r[2] for r in rows), sum(r[3] for r in rows)
    tr.write_line("-" * 62)
    if total:
        tr.write_line(f"총점  {total_pass}/{total} ({total_pass / total * 100:.1f}%)")
    if "todo" in _results:
        res = _results["todo"]
        n = res["xfailed"] + len(res["xpassed"]) + len(res["failed"])
        tr.write_line(f"{_pad('todo', 8)}{_pad(GROUPS['todo'], 36)}{res['xfailed']:>4}/{n:<4}예상대로 실패 (남은 과제)")
        for cid, note in res["xpassed"]:
            tr.write_line(f"  ! {cid} 통과함 — 고쳐졌다면 verse_test_cases.py에서 todo를 지우세요 ({note})")
    failed_all = [f for g in GROUPS if g != "todo" and g in _results for f in _results[g]["failed"]]
    if failed_all:
        tr.write_line("")
        tr.write_line("실패한 케이스 (자세히: python -m pytest test_verse_pipeline.py -k <id>)")
        for cid, msg in failed_all:
            tr.write_line(f"  {cid}  {msg}")
    try:
        md, csv_path = write_reports()
        tr.write_line("")
        tr.write_line(f"결과 파일: {_rel(md)}")
        tr.write_line(f"           {_rel(csv_path)}")
    except Exception as e:      # 결과 파일 저장 실패가 테스트 결과를 바꾸지는 않게
        tr.write_line(f"결과 파일 저장 실패: {e}")


# ==================== 결과 파일 ====================

def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        return ""


def _block(text: str) -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}text\n{text}\n{fence}"


def write_reports() -> tuple[Path, Path]:
    from verse_test_cases import GROUPS
    REPORT_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    stem = REPORT_DIR / f"verse_{now:%Y%m%d_%H%M%S}"
    branch, commit = _git("rev-parse", "--abbrev-ref", "HEAD"), _git("rev-parse", "--short", "HEAD")
    dirty = " (커밋 안 된 변경 있음)" if _git("status", "--porcelain", "--untracked-files=no") else ""
    order = {g: i for i, g in enumerate(GROUPS)}
    records = sorted(_records, key=lambda r: (order.get(r["case"].group, 99), r["case"].id))
    icon = {"통과": "✅", "실패": "❌", "예상대로 실패": "⏸️", "통과 (todo 지우기)": "❗"}

    # ---------- .md ----------
    rows = _score_rows()
    total_pass, total = sum(r[2] for r in rows), sum(r[3] for r in rows)
    L = [
        "# 성경 구절 검증 테스트 결과", "",
        f"- 실행: {now:%Y-%m-%d %H:%M:%S}",
        f"- 코드: `{branch}` @ `{commit}`{dirty}",
        f"- 총점: **{total_pass}/{total}**" + (f" ({total_pass / total * 100:.1f}%)" if total else ""),
        "- 방식: 가짜 LLM이 질문과 상관없이 정해 둔 답변을 하고, 그 답변이 실제 검증 코드를 거쳐 "
        "사용자에게 어떻게 나가는지 확인한다. 케이스마다 일반 응답 1번 + 스트리밍 3번을 돌린다.",
        "", "## 항목별 점수", "", "| 항목 | 설명 | 통과 |", "|---|---|---|",
    ]
    for g, title, p, n in rows:
        L.append(f"| {g} | {title} | {p}/{n}" + ("" if p == n else f" (실패 {n - p})") + " |")
    if "todo" in _results:
        res = _results["todo"]
        L.append(f"| todo | {GROUPS['todo']} | 예상대로 실패 {res['xfailed']}개 |")
    failed = [r for r in records if r["result"] == "실패"]
    if failed:
        L += ["", "## 실패한 케이스", ""]
        L += [f"- [{r['case'].id}](#{r['case'].id}) {r['case'].note} — {r['msg']}" for r in failed]
    L += ["", "## 케이스별 상세"]
    current = None
    for r in records:
        c, rec = r["case"], r["rec"]
        if c.group != current:
            current = c.group
            L += ["", f"### {c.group} · {GROUPS[c.group]}"]
        L += ["", f'<a id="{c.id}"></a>', f"#### {icon.get(r['result'], '')} {c.id} — {c.note}", "",
              f"- 결과: **{r['result']}**" + (f" — {r['msg']}" if r["msg"] else "")]
        if c.todo:
            L.append(f"- 아직 못 하는 이유: {c.todo}")
        L.append(f"- 질문: {rec.get('question', '')}")
        L += ["- 가짜 LLM 답변 (입력):", "", _block(c.answer if c.path != "blocked" else "(차단돼서 LLM을 부르지 않음)"), ""]
        if rec.get("output") is not None:
            L += ["- 사용자에게 나간 답변 (출력):", "", _block(rec["output"]), ""]
            ch = changes(c.answer, rec["output"]) if c.path in ("llm", "cache") else []
            L.append("- 바뀐 부분: " + ("없음" if not ch else ""))
            L += [f"  - {x}" for x in ch]
        if rec.get("statuses") is not None:
            L.append(f"- 구절별 처리 결과: {rec['statuses']}")
        if rec.get("checks"):
            L.append("- 확인한 것:")
            for label, ok, detail in rec["checks"]:
                L.append(f"  - {'✅' if ok else '❌'} {label}" + (f" — {detail}" if detail and not ok else ""))
    md = stem.with_suffix(".md")
    md.write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---------- .csv ----------
    csv_path = stem.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig: 엑셀에서 한글 안 깨짐
        w = csv.writer(f)
        w.writerow(["id", "항목", "항목 설명", "케이스 설명", "결과", "실패 이유", "질문", "가짜 LLM 답변(입력)",
                    "사용자에게 나간 답변(출력)", "바뀐 부분", "구절별 처리 결과(기대)", "구절별 처리 결과(실제)",
                    "확인 항목 통과", "확인한 것"])
        for r in records:
            c, rec = r["case"], r["rec"]
            checks = rec.get("checks", [])
            out = rec.get("output")
            w.writerow([
                c.id, c.group, GROUPS[c.group], c.note, r["result"], r["msg"] or (c.todo or ""),
                rec.get("question", ""), c.answer, "" if out is None else out,
                "\n".join(changes(c.answer, out)) if out is not None and c.path in ("llm", "cache") else "",
                "" if c.statuses is None else str(c.statuses),
                "" if rec.get("statuses") is None else str(rec["statuses"]),
                f"{sum(ok for _, ok, _ in checks)}/{len(checks)}",
                "\n".join(f"{'O' if ok else 'X'} {label}" + (f" — {d}" if d and not ok else "")
                          for label, ok, d in checks),
            ])
    return md, csv_path
