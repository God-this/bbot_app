"""테스트 공통: 가짜 법령 데이터, 가짜 임베딩, 임시 폴더에 인덱스를 만드는 env fixture.
API·OpenAI 없이 파이프라인이 도는지 확인한다. 실행: python -m pytest tests -q
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import collect  # noqa: E402
import config  # noqa: E402
import retriever  # noqa: E402

# lawService.do 응답 모양을 흉내 낸 가짜 데이터 (내용은 테스트용으로 줄임)
FAKE_LAW = {"법령": {
    "기본정보": {"법령명_한글": "도로교통법", "법종구분": {"content": "법률"}, "시행일자": "20260101"},
    "조문": {"조문단위": [
        {"조문여부": "전문", "조문내용": "제1장 총칙"},
        {"조문여부": "조문", "조문번호": "5", "조문제목": "신호 또는 지시에 따를 의무",
         "조문내용": "제5조(신호 또는 지시에 따를 의무)",
         "항": [{"항내용": "① 도로를 통행하는 보행자와 차마의 운전자는 신호기의 신호를 따라야 한다."}]},
        {"조문여부": "조문", "조문번호": "44", "조문제목": "술에 취한 상태에서의 운전 금지",
         "조문내용": "제44조(술에 취한 상태에서의 운전 금지)",
         "항": [{"항내용": "① 누구든지 술에 취한 상태에서 자동차등을 운전하여서는 아니 된다."},
                {"항내용": "④ 운전이 금지되는 술에 취한 상태의 기준은 혈중알코올농도가 0.03퍼센트 이상인 경우로 한다."}]},
        {"조문여부": "조문", "조문번호": "44", "조문가지번호": "2", "조문제목": "테스트용 가지 조문",
         "조문내용": "제44조의2(테스트용 가지 조문) 가지 조문 본문.",
         "항": {"항내용": "① 단일 항이 dict로 오는 경우", "호": [{"호내용": "1. 첫째 호"},
                                                          {"호내용": "2. 둘째 호", "목": {"목내용": ["가. 목"]}}]}},
        {"조문여부": "조문", "조문번호": "45", "조문내용": "제45조 삭제 <2020. 1. 1.>"},
    ]}}}



def fake_embed(texts):
    """글자 2-gram 해시 벡터. 겹치는 단어가 많을수록 가깝다."""
    vecs = []
    for t in texts:
        v = [0.0] * 256
        t = t.replace(" ", "")
        for i in range(len(t) - 1):
            v[int(hashlib.md5(t[i:i + 2].encode()).hexdigest(), 16) % 256] += 1
        vecs.append(v)
    return vecs



@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ARTICLES_PATH", tmp_path / "articles.jsonl")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "DOMAINS", {"traffic": ["도로교통법"]})
    retriever.set_embedder(fake_embed)
    collect.save(collect.parse_law(FAKE_LAW, "traffic"))
    retriever.build_index()
    yield
    retriever.set_embedder(None)
