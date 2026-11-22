"""1단계: 법령 수집 → 조문 단위로 자르기.

config.DOMAINS의 법령 이름을 하나씩
  1) lawSearch.do로 검색해 '현행' 법령의 일련번호(MST)를 찾고
  2) lawService.do로 본문 전체를 받아
  3) 조문 하나 = 덩어리 하나로 잘라 data/articles.jsonl에 저장한다.
API 원본 응답은 data/raw/에 남긴다 (파싱이 이상하면 여기부터 확인).

실행: python collect.py            (전체)
      python collect.py jeonse     (한 분야만)
"""
import json
import re
import sys
import time

import requests

import config

MAX_CHARS = 1500  # 이보다 긴 조문은 항 단위로 나눈다


# ---------- API ----------

def _get(endpoint: str, params: dict) -> dict:
    if not config.LAW_OC:
        raise SystemExit("LAW_OC가 비어 있습니다. .env에 LAW_OC=계정ID(@ 앞부분)를 넣어 주세요.")
    params = {"OC": config.LAW_OC, "type": "JSON", **params}
    r = requests.get(f"{config.LAW_API_BASE}/{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        # 승인 전·IP 미등록이면 JSON 대신 안내 HTML이 올 수 있다
        raise RuntimeError(f"JSON이 아닌 응답 (승인·IP 등록 확인): {r.text[:300]}")


def find_law(name: str) -> dict:
    """법령 이름으로 검색해 이름이 정확히 같은 현행 법령 1건을 돌려준다."""
    data = _get("lawSearch.do", {"target": "law", "query": name, "display": 100})
    laws = _as_list(data.get("LawSearch", {}).get("law"))
    exact = [l for l in laws if l.get("법령명한글", "").strip() == name]
    current = [l for l in exact if l.get("현행연혁코드", "현행") == "현행"] or exact
    if not current:
        found = ", ".join(l.get("법령명한글", "") for l in laws[:10])
        raise LookupError(f"'{name}'과 이름이 같은 법령이 없습니다. 검색 결과: {found}")
    return current[0]


def fetch_law(mst: str) -> dict:
    return _get("lawService.do", {"target": "law", "MST": mst})


# ---------- 파싱 ----------

def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _texts(x) -> list[str]:
    """문자열 / 문자열 리스트 / 중첩 리스트를 모두 줄 목록으로."""
    if x is None:
        return []
    if isinstance(x, str):
        return [x.strip()] if x.strip() else []
    if isinstance(x, list):
        out = []
        for i in x:
            out += _texts(i)
        return out
    return []


def _hang_lines(hang: dict) -> list[str]:
    lines = _texts(hang.get("항내용"))
    for ho in _as_list(hang.get("호")):
        lines += _texts(ho.get("호내용"))
        for mok in _as_list(ho.get("목")):
            lines += ["  " + t for t in _texts(mok.get("목내용"))]
    return lines


def article_no_of(unit: dict) -> str:
    no = str(unit.get("조문번호", "")).strip()
    branch = str(unit.get("조문가지번호", "") or "").strip()
    return f"{no}의{branch}" if branch and branch != "0" else no


DELETED = re.compile(r"^제\d+조(의\d+)?\s*삭제")


def parse_law(law_json: dict, domain: str) -> list[dict]:
    """lawService.do 응답 → 조문 덩어리 목록."""
    law = law_json.get("법령", law_json)
    info = law.get("기본정보", {})
    law_name = info.get("법령명_한글") or info.get("법령명한글", "")
    law_type = (info.get("법종구분") or {}).get("content", "") if isinstance(info.get("법종구분"), dict) else info.get("법종구분", "")
    effective = str(info.get("시행일자", ""))

    chunks = []
    for unit in _as_list((law.get("조문") or {}).get("조문단위")):
        if unit.get("조문여부") != "조문":  # '전문' = 장·절 제목
            continue
        head = " ".join(_texts(unit.get("조문내용")))
        if DELETED.match(head):
            continue
        art_no = article_no_of(unit)
        title = (unit.get("조문제목") or "").strip()
        hangs = [_hang_lines(h) for h in _as_list(unit.get("항"))]

        base = {"domain": domain, "law_name": law_name, "law_type": law_type,
                "article_no": art_no, "title": title, "effective_date": effective}
        body_parts = [hl for hl in hangs if hl]
        full = "\n".join([head] + [l for hl in body_parts for l in hl])

        if len(full) <= MAX_CHARS or len(body_parts) < 2:
            chunks.append({**base, "part": 0, "text": full})
            continue
        # 긴 조문: 항 묶음 단위로 나누고, 각 덩어리 앞에 조문 머리를 붙인다
        part, buf = 0, []
        for hl in body_parts:
            if buf and len("\n".join(buf + hl)) > MAX_CHARS:
                chunks.append({**base, "part": part, "text": "\n".join([head] + buf)})
                part, buf = part + 1, []
            buf += hl
        if buf:
            chunks.append({**base, "part": part, "text": "\n".join([head] + buf)})

    for c in chunks:
        c["id"] = f"{c['law_name']}|{c['article_no']}|{c['part']}"
    return chunks


# ---------- 실행 ----------

def collect(domains: dict[str, list[str]]) -> list[dict]:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_chunks = []
    for domain, names in domains.items():
        for name in names:
            meta = find_law(name)
            mst = meta.get("법령일련번호")
            raw = fetch_law(mst)
            (config.RAW_DIR / f"{name}.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            chunks = parse_law(raw, domain)
            print(f"[{domain}] {name} (MST {mst}, 시행 {meta.get('시행일자')}): 덩어리 {len(chunks)}개")
            if not chunks:
                print(f"  ! 조문을 못 읽었습니다. data/raw/{name}.json 구조를 확인하세요.")
            all_chunks += chunks
            time.sleep(0.5)  # API 예의상
    return all_chunks


def save(chunks: list[dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    keep = []
    if config.ARTICLES_PATH.exists():  # 다른 분야 데이터는 그대로 둔다
        new_domains = {c["domain"] for c in chunks}
        for line in config.ARTICLES_PATH.read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            if c["domain"] not in new_domains:
                keep.append(c)
    with config.ARTICLES_PATH.open("w", encoding="utf-8") as f:
        for c in keep + chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"저장: {config.ARTICLES_PATH} (총 {len(keep) + len(chunks)}개)")


if __name__ == "__main__":
    picked = sys.argv[1:]
    domains = {d: v for d, v in config.DOMAINS.items() if not picked or d in picked}
    save(collect(domains))
