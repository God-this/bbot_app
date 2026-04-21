# BeBot — 기독교 세계관 AI 챗봇

기독교 세계관 및 창조과학 주제에 특화된 RAG 기반 AI 챗봇입니다. 웹 문서, 도서, 유튜브 영상 등 다양한 소스에서 관련 정보를 검색하여 출처가 명확한 답변을 제공합니다.

---

## 주요 기능

- **다중 소스 검색**: 크롤링된 웹 문서, 영문/국문 도서, 유튜브 영상 자막을 벡터 유사도 검색으로 동시에 조회
- **이중 언어 지원**: 질문의 언어(한국어/영어)를 자동 감지하고 동일 언어로 답변
- **출처 표시**: 웹 링크, 도서 페이지, 영상 타임스탬프를 응답에 함께 제공
- **인앱 유튜브 재생**: 출처 영상을 앱 내에서 특정 구간부터 바로 재생
- **질문 재작성**: 검색 결과가 부족할 경우 질문을 자동으로 재작성하여 재시도 (최대 2회)
- **마크다운 렌더링**: 답변을 마크다운으로 포맷

---

## 기술 스택

### 프론트엔드 (Flutter)
| 항목 | 내용 |
|------|------|
| 프레임워크 | Flutter 3.x (Dart) |
| 상태 관리 | Provider 6.1.1 |
| HTTP 통신 | http ^1.2.0 |
| 마크다운 | flutter_markdown ^0.7.1 |
| 영상 재생 | youtube_player_flutter ^9.0.3 |
| URL 처리 | url_launcher ^6.2.2 |
| 환경변수 | flutter_dotenv ^5.1.0 |

### 백엔드 (Python)
| 항목 | 내용 |
|------|------|
| 웹 프레임워크 | FastAPI 0.136.0 |
| ASGI 서버 | Uvicorn 0.45.0 |
| RAG 파이프라인 | LangGraph 1.1.2, LangChain 1.2.19 |
| LLM | OpenAI (gpt-4o-mini) / Upstage Solar (solar-pro2) |
| 임베딩 | text-embedding-3-small / embedding-query |
| 데이터베이스 | PostgreSQL + pgvector |
| 모니터링 | LangSmith (선택) |

---

## 프로젝트 구조

```
bbot_app/
├── backend/
│   ├── server.py           # FastAPI 서버 (REST API 엔드포인트)
│   ├── bbot_graph.py       # LangGraph RAG 워크플로우
│   ├── bbot_web.py         # 웹 문서 벡터 검색
│   ├── bbot_book.py        # 도서 페이지 검색
│   ├── bbot_video.py       # 유튜브 영상 구간 검색
│   ├── config.py           # DB 연결 및 환경설정
│   ├── llm_factory.py      # LLM/임베딩 프로바이더 팩토리
│   ├── requirements.txt    # Python 의존성
│   ├── .env                # 환경변수 (API 키 등)
│   └── .env.example        # 환경변수 템플릿
│
└── front/
    ├── lib/
    │   ├── main.dart               # 앱 진입점
    │   ├── theme.dart              # 테마 및 색상 정의
    │   ├── models/
    │   │   └── chat_models.dart    # 데이터 모델 (메시지, 소스)
    │   ├── services/
    │   │   ├── api_service.dart    # 백엔드 HTTP 통신
    │   │   └── chat_provider.dart  # 상태 관리
    │   ├── screens/
    │   │   └── chat_screen.dart    # 메인 채팅 화면
    │   └── widgets/
    │       ├── welcome_view.dart   # 웰컴 화면 (추천 질문 포함)
    │       ├── chat_bubble.dart    # 메시지 말풍선
    │       ├── chat_input_bar.dart # 입력창
    │       └── sources_sheet.dart  # 출처 상세 모달
    └── pubspec.yaml                # Flutter 의존성
```

---

## 시작하기

### 사전 요구사항

- Python 3.10+
- Flutter 3.x SDK
- PostgreSQL (pgvector 확장 포함)
- OpenAI 또는 Upstage API 키

### 1. 백엔드 설정

```bash
cd backend

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 및 DB 정보 입력
```

```bash
# 서버 실행
uvicorn server:app --host 0.0.0.0 --port 8000
```

### 2. 프론트엔드 설정

```bash
cd front

# 의존성 설치
flutter pub get

# 실행 (백엔드 URL 지정)
flutter run --dart-define=BACKEND_URL=http://localhost:8000
```

iOS 기기/시뮬레이터에서 실행할 경우:
```bash
flutter run -d iPhone --dart-define=BACKEND_URL=http://your_server_ip:8000
```

---

## API 명세

### `POST /api/chat`

질문을 받아 RAG 파이프라인을 통해 답변과 출처를 반환합니다.

**요청:**
```json
{
  "question": "공룡이 실제로 존재했나요?"
}
```

**응답:**
```json
{
  "answer": "네, 공룡은 실제로 존재했습니다...",
  "sources": {
    "web_docs": [
      { "title": "제목", "url": "https://...", "content": "본문..." }
    ],
    "book_docs": [
      { "book": "CaseForACreator", "page": 42, "content": "본문..." }
    ],
    "video_docs": [
      {
        "video_id": "abc123",
        "title": "영상 제목",
        "start": 120.0,
        "end": 180.0,
        "url": "https://youtu.be/abc123?t=120s",
        "content": "자막 내용..."
      }
    ]
  },
  "top_sources": []
}
```

### `GET /api/health`

서버 상태를 확인합니다.

```json
{ "status": "ok", "service": "BeBot API" }
```

---

## RAG 워크플로우

```
사용자 질문
    │
    ▼
언어 감지 (한국어 / 영어)
    │
    ▼
양 언어로 번역
    │
    ▼
병렬 문서 검색 ───────────────--─┐
  ├─ 웹 문서 (crawled_data).   |
  ├─ 도서 (book_en / book_ko)  │ ThreadPoolExecutor
  └─ 영상 (video_db)           │
                              └──▶ 결과 통합
    │
    ▼
충분한 문서? ──아니오──▶ 질문 재작성 (최대 2회) ──▶ 재검색
    │예
    ▼
LLM 답변 생성
    │
    ▼
응답 반환 (답변 + 소스)
```

---

## 데이터베이스 Schema

PostgreSQL + pgvector를 사용합니다.

| 테이블 | 주요 컬럼 |
|--------|-----------|
| `crawled_data` | title, url, content, content_embedding (vector) |
| `book_en` | book_name, page_num, content, embedding (vector) |
| `book_ko` | book_name, page_num, content, embedding (vector) |
| `video_db` | video_id, title, start_time, end_time, url, content, content_embedding (vector) |

---

## LLM 전환

`backend/.env`의 `PROVIDER` 값을 변경하여 LLM과 임베딩 모델을 전환할 수 있습니다.

| `PROVIDER` | LLM 모델 | 임베딩 모델 |
|------------|----------|-------------|
| `openai` | gpt-4o-mini | text-embedding-3-small |
| `upstage` | solar-pro2 | embedding-query |
