"""pytest 공통 설정 — 성경 구절 검증 테스트의 항목별 점수 표시

test_verse_pipeline.py의 케이스(verse_test_cases.Case)는 group(케이스 나무 항목)을 갖고 있다.
테스트가 끝나면 항목별로 몇 개 중 몇 개가 통과했는지, 실패한 케이스는 무엇인지 보여준다.
다른 테스트 파일에는 영향이 없다 (group이 없는 테스트는 세지 않음).
"""
from collections import defaultdict

import pytest

_results: dict[str, dict] = defaultdict(lambda: {"passed": 0, "failed": [], "xfailed": 0, "xpassed": []})


def _case_of(item):
    callspec = getattr(item, "callspec", None)
    return callspec.params.get("case") if callspec else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    case = _case_of(item)
    if case is None or not hasattr(case, "group"):
        return
    if rep.when == "setup" and rep.failed:
        _results[case.group]["failed"].append((case.id, "준비 단계 오류"))
        return
    if rep.when != "call":
        return
    res = _results[case.group]
    if hasattr(rep, "wasxfail"):
        if rep.skipped:
            res["xfailed"] += 1
        else:
            res["xpassed"].append((case.id, case.note))
    elif rep.passed:
        res["passed"] += 1
    elif rep.failed and "XPASS(strict)" in str(rep.longrepr):
        res["xpassed"].append((case.id, case.note))
    elif rep.failed:
        msg = str(getattr(rep.longrepr, "reprcrash", None) and rep.longrepr.reprcrash.message or rep.longrepr)
        res["failed"].append((case.id, msg.splitlines()[0].removeprefix("Failed: ")[:150]))


def _w(s: str) -> int:
    """화면 폭 (한글은 2칸)"""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def pytest_terminal_summary(terminalreporter):
    if not _results:
        return
    from verse_test_cases import GROUPS
    tr = terminalreporter
    tr.section("성경 구절 검증 테스트 점수")
    total_pass = total = 0
    failed_all = []
    for g, title in GROUPS.items():
        if g == "todo" or g not in _results:
            continue
        res = _results[g]
        n = res["passed"] + len(res["failed"])
        total_pass += res["passed"]
        total += n
        mark = "" if not res["failed"] else f"   실패 {len(res['failed'])}건"
        tr.write_line(f"{_pad(g, 8)}{_pad(title, 36)}{res['passed']:>4}/{n:<4}{mark}")
        failed_all += res["failed"]
    tr.write_line("-" * 62)
    if total:
        tr.write_line(f"총점  {total_pass}/{total} ({total_pass / total * 100:.1f}%)")
    if "todo" in _results:
        res = _results["todo"]
        n = res["xfailed"] + len(res["xpassed"]) + len(res["failed"])
        tr.write_line(f"{_pad('todo', 8)}{_pad(GROUPS['todo'], 36)}{res['xfailed']:>4}/{n:<4}예상대로 실패 (남은 과제)")
        for cid, note in res["xpassed"]:
            tr.write_line(f"  ! {cid} 통과함 — 고쳐졌다면 verse_test_cases.py에서 todo를 지우세요 ({note})")
    if failed_all:
        tr.write_line("")
        tr.write_line("실패한 케이스 (자세히: python -m pytest test_verse_pipeline.py -k <id>)")
        for cid, msg in failed_all:
            tr.write_line(f"  {cid}  {msg}")
