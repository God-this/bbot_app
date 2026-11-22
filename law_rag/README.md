# law_rag — 법령 RAG 세 방식 비교

> bebot 서비스와 별개인 실험 코드입니다. 백엔드(`backend/`)와 의존성·가상환경을 공유하지 않습니다.

같은 질문을 **RAG 없음 / 항상 RAG / 툴콜링 RAG** 세 방식으로 답하게 하고, 인용한 조문이 맞는지 한 표로 비교한다.

```
config.DOMAINS(법령 이름 목록)
   → collect.py      법령 API로 본문 받기 → 조문 단위로 자르기 → data/articles.jsonl
   → build_index.py  조문 임베딩 → Chroma(data/chroma)
   → answer.py       세 방식 답변 (검색 함수는 retriever.py 하나를 같이 씀)
   → compare.py      questions.csv로 돌려 results/compare_*.csv / .md
```

## 준비

```bash
cd law_rag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # LAW_OC, OPENAI_API_KEY 채우기
```

- `LAW_OC`: open.law.go.kr → 마이페이지 → API인증키관리의 "현재 API인증키(OC)" 값
- 법령 API는 **등록된 IP에서만** 호출됨. `curl -s ifconfig.me`로 공인 IP를 확인해 OPEN API 신청서의 "서버장비의 IP주소"에 추가해야 함 (와이파이가 바뀌면 IP도 바뀜)
- zsh에서는 질문에 `?`가 있으면 따옴표로 감쌀 것

## 실행

```bash
python collect.py                 # 전체 분야 수집 (python collect.py jeonse → 한 분야만)
python build_index.py             # 임베딩·저장 (수집할 때마다 다시)
python answer.py "계약갱신요구권은 몇 번 쓸 수 있어?"   # 한 질문 세 방식 확인
python compare.py                 # 전체 비교 (--domain jeonse, --modes no_rag tool_rag)
python -m pytest tests -q         # API 없이 동작 확인
```

## 새 케이스 추가

1. `config.py`의 `DOMAINS`에 분야와 법령 이름(국가법령정보센터 정식 이름) 추가
2. `python collect.py <분야>` → `python build_index.py`
3. `questions.csv`에 질문과 정답 조문 추가

## 결과 읽는 법

| 항목 | 뜻 |
|---|---|
| 정답 조문 인용 | 답변 끝 "근거 조문"에 정답 조문이 있는지 |
| 없는 조문 지어냄 | 인용했는데 DB에 없는 조문 수 → "이상하게 가져오는 예시" |
| 검색 적중 | 검색·툴로 가져온 조문에 정답이 있었는지. 적중 O인데 인용 X면 생성 문제, 적중 X면 검색 문제 |

## 알아둘 점

- `questions.csv`의 정답 조문은 **예시**. 수집한 현행 법령으로 번호를 꼭 확인할 것 (compare 실행 시 DB에 없는 정답은 경고가 뜸).
- 첫 수집 후 `data/raw/*.json`을 열어 조문이 잘 읽혔는지 확인. 덩어리 0개면 응답 구조가 다른 것이니 `collect.parse_law`를 맞춰야 함.
- 별표(범칙금·벌점 표 등)는 아직 수집하지 않음. 금액 질문은 별표에 답이 있는 경우가 많다.
- 조 번호로 묻는 질문은 임베딩 검색이 약함 → 툴콜링의 `get_article`이 이 차이를 보여줌.
