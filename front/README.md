# BeBot ios APP

```
서버 실행
uvicorn server:app --port 8000

ui 실행
flutter pub get
flutter run --dart-define=BACKEND_URL=http://localhost:8000
```


## [핵심 기능]

| 기능 | 설명 |
|------|------|
| **대화 인터페이스** | 사용자/봇 말풍선, 타이핑 인디케이터, 날짜 구분선 |
| **추천 질문** | 첫 화면에서 샘플 질문 탭하여 바로 전송 |
| **출처 표시** | 웹/책/영상 출처를 배지로 표시, 탭하면 상세 보기 |
| **인앱 영상 재생** | YouTube 영상을 바텀시트 내에서 바로 재생 |
| **웹 링크 열기** | 웹 출처 탭하면 외부 브라우저로 이동 |
| **Markdown 렌더링** | 봇 답변의 마크다운 포맷 지원 |
| **한국어/영어 지원** | 백엔드 자동 언어 감지 + 번역 |


## [기술 스택]

- **프론트엔드**: Flutter 3.x + Dart
- **상태 관리**: Provider
- **백엔드**: FastAPI (기존 Python 코드 래핑)
- **데이터베이스**: PostgreSQL + pgvector
- **LLM**: Upstage Solar / OpenAI (설정 가능)
- **영상 재생**: youtube_player_flutter


## [프로젝트 구조]

```
bebot_app/
├── lib/
│   ├── main.dart                    # 앱 진입점
│   ├── theme.dart                   # 테마, 색상, 타이포그래피
│   ├── models/
│   │   └── chat_models.dart         # 데이터 모델 (메시지, 출처)
│   ├── services/
│   │   ├── api_service.dart         # 백엔드 API 통신
│   │   └── chat_provider.dart       # 상태 관리 (Provider)
│   ├── screens/
│   │   └── chat_screen.dart         # 메인 채팅 화면
│   └── widgets/
│       ├── welcome_view.dart        # 첫 화면 (로고 + 추천 질문)
│       ├── chat_bubble.dart         # 사용자/봇 말풍선
│       ├── chat_input_bar.dart      # 하단 입력 바
│       └── sources_sheet.dart       # 출처 상세 바텀시트 (영상 재생 포함)
├── server.py                        # FastAPI 백엔드 래퍼
├── pubspec.yaml                     # Flutter 의존성
└── README.md
```

## [아키텍처]

```
┌──────────────────┐     HTTP/JSON     ┌──────────────────────┐
│   Flutter App    │ ◄───────────────► │   FastAPI (server.py) │
│                  │                   │                       │
│  - ChatProvider  │                   │  bbot_graph.generate()│
│  - API Service   │                   │  ├─ bbot_web.py       │
│  - UI Widgets    │                   │  ├─ bbot_book.py      │
│                  │                   │  └─ bbot_video.py     │
└──────────────────┘                   └───────┬───────────────┘
                                               │
                                       ┌───────▼───────────────┐
                                       │  PostgreSQL + pgvector │
                                       │  - crawled_data        │
                                       │  - book_eng            │
                                       │  - video_db            │
                                       └───────────────────────┘
```


## [사전 요구사항]

- Flutter SDK 3.0 이상
- Xcode 15.0 이상
- iOS Simulator 또는 실제 iOS 기기
- CocoaPods

## [API 명세 - POST /api/chat]

**Request:**
```json
{
  "question": "공룡이 실제로 존재했나요?"
}
```

**Response:**
```json
{
  "answer": "네, 공룡은 정말 존재했어요! ...",
  "sources": {
    "web_docs": [
      { "title": "...", "url": "...", "content": "..." }
    ],
    "book_docs": [
      { "book": "CaseForACreator", "page": 42, "content": "..." }
    ],
    "video_docs": [
      {
        "video_id": "v0001",
        "title": "...",
        "start": 120.0,
        "end": 180.0,
        "url": "https://youtu.be/xxx?t=120s",
        "content": "..."
      }
    ]
  }
}
```