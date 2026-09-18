-- BeBot 캐시 품질 평가 스키마 (캐시 개편 ②단계)
--
-- 이 프로젝트에는 마이그레이션 도구가 없고 기존 테이블도 서버에서 수동 생성되어
-- 코드로 추적되지 않는다. 최소한 신규 테이블만이라도 DDL을 레포에 남긴다.
--
-- 적용:
--   psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f backend/schema/qa_eval.sql
-- 멱등이므로 재실행해도 안전하다.


-- ==================== 평가 대기열 ====================
-- 답변 생성(캐시 저장 성공) 시 1건씩 적재된다. RAGAS 배치(③단계)가
-- evaluated_at IS NULL 인 항목을 created_at 순으로 BATCH_LIMIT만큼 꺼내 처리한다.
CREATE TABLE IF NOT EXISTS qa_eval_queue (
    id                  BIGSERIAL PRIMARY KEY,
    cache_key           TEXT NOT NULL,          -- bebot:cache:{normalized_question}
    normalized_question TEXT NOT NULL,          -- mark_evaluated/delete_and_tombstone 입력
    original_question   TEXT NOT NULL,
    answer              TEXT NOT NULL,
    contexts            JSONB NOT NULL,         -- [content[:800], ...] — 프롬프트 입력과 동일해야 함
    context_char_limit  INT  NOT NULL DEFAULT 800,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    evaluated_at        TIMESTAMPTZ             -- NULL = 미평가
);

-- 배치 조회 전용 부분 인덱스. 평가 완료분은 인덱스에서 빠져
-- 큐가 누적되어도 미평가 스캔 비용이 늘지 않는다.
CREATE INDEX IF NOT EXISTS idx_eval_queue_pending
    ON qa_eval_queue (created_at)
    WHERE evaluated_at IS NULL;


-- ==================== 평가 결과 ====================
CREATE TABLE IF NOT EXISTS ragas_evaluations (
    id                  BIGSERIAL PRIMARY KEY,
    cache_key           TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    original_question   TEXT NOT NULL,
    answer              TEXT NOT NULL,
    contexts            JSONB,
    context_char_limit  INT,

    faithfulness        REAL,
    answer_relevancy    REAL,
    context_precision   REAL,
    composite_score     REAL,           -- 가중 평균, 판정 기준

    verdict             TEXT NOT NULL,  -- keep / review / deleted / would_delete
    dry_run             BOOLEAN NOT NULL DEFAULT TRUE,

    -- RAGAS는 버전 간 메트릭 계산식이 바뀔 수 있고 judge 모델이 달라지면
    -- 점수 비교가 무의미하다. 없으면 "삭제율이 왜 올랐는가"를 추적할 수 없다.
    ragas_version       TEXT,
    judge_provider      TEXT,
    judge_model         TEXT,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ragas_eval_question
    ON ragas_evaluations (normalized_question, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ragas_eval_verdict
    ON ragas_evaluations (verdict, evaluated_at DESC);
