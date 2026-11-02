#!/bin/bash
set -euo pipefail

# 스테이징 postgres에 운영 DB 덤프를 복원한다
#
# 사용법:
#   ./deploy/db-restore.sh <덤프 파일>           # 빈 DB에 복원
#   ./deploy/db-restore.sh <덤프 파일> --force   # 기존 데이터를 지우고 복원 (backend 정지)
#   ./deploy/db-restore.sh <덤프 파일> --force --delete-dump   # 복원에 성공하면 덤프 파일 삭제
#   ./deploy/db-restore.sh --check              # 복원 없이 현재 DB 상태만 출력
#
# 덤프는 custom 형식(pg_dump -Fc)만 받는다. 운영(EC2)에서 만드는 방법:
#   pg_dump -Fc -h <호스트> -p <포트> -U <사용자> -d <DB> -f bebot_staging.dump
#   EC2 키는 Mac에만 있으므로 EC2 → Mac → 스테이징 서버 순서로 옮긴다 (scp).
#   덤프에는 운영 개인정보(사용자, 대화 기록)가 들어 있다. Mac 사본은 scp 직후 지우고,
#   스테이징 서버 사본은 마지막 복원에 --delete-dump 를 붙여 지운다.
#
# 다른 compose 프로젝트로 복원해 보려면 (기존 스테이징 DB에 영향 없음):
#   COMPOSE_PROJECT_NAME=bebot-test ./deploy/db-restore.sh <덤프 파일>
#   docker compose -p bebot-test down -v    # 확인 후 정리

cd "$(dirname "$0")/.."

ENV_FILE=backend/.env.staging
# 복원 후 행 수를 확인할 주요 테이블
TABLES=(book_en book_ko crawled_data video_db users qa_eval_queue)

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE 이 없습니다. backend/.env.staging.example 을 복사해 채우세요."

# postgres만 다루지만 compose가 파일 전체를 해석하므로 태그 자리 값을 넣는다
dc() {
  BACKEND_TAG=${BACKEND_TAG:-none} FRONT_TAG=${FRONT_TAG:-none} \
    docker compose --env-file "$ENV_FILE" "$@"
}

psql_c() {
  dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At "$@"' sh "$@"
}

table_count() {
  psql_c -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
}

report() {
  echo "── DB 상태 ──"
  echo "vector extension: $(psql_c -c "SELECT coalesce((SELECT extversion FROM pg_extension WHERE extname = 'vector'), '없음')")"
  local t
  for t in "${TABLES[@]}"; do
    if [ "$(psql_c -c "SELECT to_regclass('public.$t') IS NOT NULL")" = t ]; then
      printf '  %-14s %s행\n' "$t" "$(psql_c -c "SELECT count(*) FROM public.$t")"
    else
      printf '  %-14s 없음\n' "$t"
    fi
  done
}

start_postgres() {
  dc up -d --wait postgres >/dev/null
}

DUMP="" FORCE=0 CHECK=0 DELETE_DUMP=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    --delete-dump) DELETE_DUMP=1 ;;
    -*) die "알 수 없는 옵션: $arg" ;;
    *) [ -z "$DUMP" ] || die "덤프 파일은 하나만 지정하세요."; DUMP=$arg ;;
  esac
done

[ "$CHECK" = 0 ] || [ "$DELETE_DUMP" = 0 ] || die "--check 와 --delete-dump 는 함께 쓸 수 없습니다."

if [ "$CHECK" = 1 ]; then
  start_postgres
  report
  exit 0
fi

if [ -z "$DUMP" ]; then
  sed -n '4,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
[ -f "$DUMP" ] || die "$DUMP 파일이 없습니다."
# custom 형식은 PGDMP로 시작한다. plain SQL(-Fp)이나 압축 파일이면 여기서 막는다
[ "$(head -c 5 "$DUMP")" = PGDMP ] || die "$DUMP 는 custom 형식(pg_dump -Fc)이 아닙니다. 'file $DUMP' 로 형식을 확인하세요."

start_postgres

existing=$(table_count)
CLEAN=()
if [ "$existing" -gt 0 ]; then
  if [ "$FORCE" != 1 ]; then
    report
    die "DB에 이미 테이블 ${existing}개가 있습니다. 지우고 다시 복원하려면 --force 를 붙이세요."
  fi
  # 복원 중 테이블을 지우고 다시 만들므로 연결을 잡고 있는 backend를 멈춘다
  echo "⏸️  backend를 정지합니다 (복원 후 ./deploy/staging.sh up 으로 다시 띄우세요)."
  dc stop backend >/dev/null 2>&1 || true
  CLEAN=(--clean --if-exists)
fi

LOG="${TMPDIR:-/tmp}/bebot-restore-$(date +%Y%m%d-%H%M%S).log"
echo "⏳ 복원 중: $DUMP ($(du -h "$DUMP" | cut -f1)). 로그: $LOG"

# 운영과 계정·권한이 다르므로 소유자·권한 정보는 버리고 접속 계정 소유로 만든다.
# 오류가 있어도 끝까지 진행한 뒤 건수를 알린다 (pg_restore 기본 동작)
rc=0
dc exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges "$@"' \
  sh ${CLEAN[@]+"${CLEAN[@]}"} < "$DUMP" 2> >(tee "$LOG" >&2) || rc=$?

# pg_restore는 통계를 복원하지 않는다. 벡터 테이블 쿼리 계획을 위해 바로 수집한다
echo "📊 ANALYZE 실행"
psql_c -c "ANALYZE" >/dev/null

report

if [ "$rc" -ne 0 ]; then
  echo "⚠️  pg_restore가 오류와 함께 끝났습니다 (종료 코드 $rc). $LOG 를 확인하세요." >&2
  [ "$DELETE_DUMP" = 0 ] || echo "   다시 시도할 수 있도록 $DUMP 는 지우지 않았습니다." >&2
  exit "$rc"
fi
echo "✅ 복원 완료"
if [ "$DELETE_DUMP" = 1 ]; then
  rm -f -- "$DUMP"
  echo "🗑️  $DUMP 삭제"
fi
[ "${#CLEAN[@]}" -eq 0 ] || echo "   ./deploy/staging.sh up 으로 backend를 다시 띄우세요. 이전 데이터 기준 캐시가 남아 있으면 redis를 비우세요."
