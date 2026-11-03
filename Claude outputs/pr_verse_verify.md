## 변경 사항
- 답변 전에 성경 도구를 강제 호출하던 방식(평균 66초)을 없애고, 답변은 도구 없이 바로 생성·스트리밍한 뒤 **답변에 포함된 구절만** 개역한글 원문(`bible_krv`)과 코드로 대조합니다. (교수님 피드백: 답변 생성 후 구절이 있을 때만 확인)
- 스트리밍 중 구절 인용 부분만 잠깐 붙잡아 검증한 뒤 전송하므로, 틀린 구절은 화면에 나가지 않고 앱(Flutter) 수정도 필요 없습니다.
- 랩미팅 의견에 따라 정규식으로 찾은 구절의 **맥락·주소를 LLM이 툴콜링으로 판정**합니다. LLM은 판정만 하고 수정은 코드가 하며, **기본값은 응답 전송 후 기록만 하는 `shadow`**입니다.

### 검증 규칙 (코드)
| 형식 | 처리 |
| --- | --- |
| 장만 (`창세기 5장`) | 장 존재 확인 |
| 3절 이하 | 존재 확인 + 인용 본문이 다르면 원문으로 교체 |
| 4절 이상 | 존재 확인, 본문이 틀리면 주소만 남김 |
| 없는 구절 | 인용 삭제 / 문장 속 언급은 '성경'으로 치환 |
| 주소만 언급 | 그대로 두고 답변 끝 **참고 구절**에 원문 표시 |

### 맥락·주소 판정 (LLM)
1. 구절 검출 (코드) → 2. 존재·본문 확인 (코드, 표시만) → 3. 판정 (LLM + `get_bible_verses`·`search_bible`, 구절별 JSON) → 4. 확인된 판정만 반영 (코드)
- `VERSE_JUDGE_MODE`: `shadow`(기본, 기록만 · Langfuse `verse-judge-shadow`) / `apply`(답변에 반영) / `off`

### 주요 파일
- `bible_verify.py` (신규): 구절 검출, 원문 조회(장 단위 캐시, DB 실패 시 `bible.txt`), 스트리밍 필터, 참고 구절, 캐시 답변 재검증, 판정 반영(`apply_verdicts`)
- `bible_verse_judge.py` (신규): 판정 LLM 루프, 툴, shadow 기록
- `bbot_graph.py`: `generate` / `generate_stream` / 캐시 경로에 필터·판정 연결, 성경 인용 규칙 프롬프트, 기존 `chat_with_tools` 연결 해제
- `scripture_strip.py`: RAGAS 평가 입력에서 참고 구절 제거
- `.env.example`: `VERSE_VERIFY_MODE`, `APPEND_REFERENCE_VERSES`, `VERSE_JUDGE_MODE`, `VERSE_CONTEXT_ACTION`, `BIBLE_SOURCE`
- 테스트·실험: `test_bible_verify.py`, `test_bible_verse_judge.py`, `compare_verse_modes.py`, `eval_verse_judge.py`
- 중간에 만든 tool 방식(LLM이 답변을 다시 씀)은 비교 실험 결과 출처·문단을 지워 제거했습니다 (`bible_tool_verify.py` 삭제).

## 테스트 방법 및 결과
- 단위 테스트 (LLM 없음): `python test_bible_verify.py` 19/19, `python test_bible_verse_judge.py` 16/16 통과 (`bible.txt` / 운영 DB 양쪽). 커밋별로 단독 실행해도 통과
- DB 원문 확인: `bible_krv` 31,101절과 `bible.txt` 전수 비교 결과 차이 0건
- 방식 비교 (`compare_verse_modes.py`, 질문 20개, OpenAI, 운영 DB)

| | code (채택) | tool (제거) |
| --- | --- | --- |
| 첫 글자 | 0.9초 | 0.9초 |
| 답변 완료 | **4.1초** | 7.7초 |
| 틀린 인용 21건 처리 | **21건 원문 교체** | 17건 |
| 답변 손상 | 없음 | 출처 삭제 16개, 문단 삭제 3개 답변 |

- 판정 오프라인 평가 (`eval_verse_judge.py`, 구절 49개): ok 12 / quote_wrong 33 / context_mismatch 4 / wrong_ref 0, 답변당 평균 3.3초. 코드가 놓친 주소 뒤 인용 11건을 찾음 → 정확도 검토 전까지 shadow 유지

## 체크리스트
- [x] 로컬에서 정상 동작 확인 (단위 테스트, 비교·평가 스크립트)
- [x] .env, API 키 등 민감정보 포함 안 됨
- [ ] 관련 문서(README 등) 업데이트 필요 시 반영
- [ ] emptycan(스테이징)에서 스트리밍 · shadow 기록(Langfuse) 확인

## 참고
- 기존 Redis 캐시 답변도 꺼낼 때 code 방식으로 재검증되므로 캐시를 비우지 않아도 됩니다.
- shadow 판정은 구절이 있는 답변마다 응답 후 LLM 호출 1회가 추가됩니다. 끄려면 `VERSE_JUDGE_MODE=off`.
- 브랜치에 `origin/main` merge 커밋이 있으니 Squash and merge로 머지해 주세요.
- 후속 과제: 프롬프트 "마무리" 규칙 수정(본문 대신 주소만), 주소 뒤 인용 검출, 영어 구절 검출, 판정 정확도 검토 후 apply 여부 결정

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01JBRbRdvyZM8aM2iYT9A5ms
