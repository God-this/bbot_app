#!/bin/bash
set -euo pipefail

# 스테이징 redis에 운영 redis 저장 파일(RDB)을 복원한다
#
# 사용법:
#   ./deploy/redis-restore.sh <dump.rdb>           # 빈 redis에 복원
#   ./deploy/redis-restore.sh <dump.rdb> --force   # 기존 키를 버리고 복원 (backend 정지)
#   ./deploy/redis-restore.sh <dump.rdb> --force --delete-dump   # 복원에 성공하면 파일 삭제
#   ./deploy/redis-restore.sh --check              # 복원 없이 현재 redis 상태만 출력
#
# 캐시 답변은 DB 내용을 기준으로 만들어졌으므로 db-restore.sh 다음에, 같은 시점의 파일로 복원한다.
# 운영(EC2)에서 만드는 방법:
#   redis-cli BGSAVE 후 LASTSAVE 값이 바뀌면 $(redis-cli CONFIG GET dir)/dump.rdb 를 복사한다.
#   EC2 → Mac → 스테이징 서버 순서로 옮긴다 (scp).
#   캐시에는 사용자 질문과 답변이 들어 있다. Mac 사본은 scp 직후 지우고,
#   스테이징 서버 사본은 --delete-dump 를 붙여 지운다.
#
# RDB는 상위 버전 redis가 만든 파일을 읽지 못한다. 교체 전에 스테이징 redis 이미지의
# redis-check-rdb로 읽을 수 있는지 먼저 확인한다.

cd "$(dirname "$0")/.."

ENV_FILE=backend/.env.staging
# 복원 후 개수를 확인할 키 패턴 (redis_cache.py)
PATTERNS=('bebot:cache:*' 'bebot:rejected:*')

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE 이 없습니다. backend/.env.staging.example 을 복사해 채우세요."

# redis만 다루지만 compose가 파일 전체를 해석하므로 태그 자리 값을 넣는다
dc() {
  BACKEND_TAG=${BACKEND_TAG:-none} FRONT_TAG=${FRONT_TAG:-none} \
    docker compose --env-file "$ENV_FILE" "$@"
}

rcli() { dc exec -T redis redis-cli "$@"; }

report() {
  echo "── redis 상태 ──"
  echo "  version        $(rcli INFO server | tr -d '\r' | sed -n 's/^redis_version://p')"
  echo "  전체 키        $(rcli DBSIZE)"
  local p
  for p in "${PATTERNS[@]}"; do
    printf '  %-14s %s\n' "$p" "$(rcli --scan --pattern "$p" | wc -l | tr -d ' ')"
  done
}

start_redis() {
  dc up -d --wait redis >/dev/null
}

DUMP="" FORCE=0 CHECK=0 DELETE_DUMP=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    --delete-dump) DELETE_DUMP=1 ;;
    -*) die "알 수 없는 옵션: $arg" ;;
    *) [ -z "$DUMP" ] || die "파일은 하나만 지정하세요."; DUMP=$arg ;;
  esac
done

[ "$CHECK" = 0 ] || [ "$DELETE_DUMP" = 0 ] || die "--check 와 --delete-dump 는 함께 쓸 수 없습니다."

if [ "$CHECK" = 1 ]; then
  start_redis
  report
  exit 0
fi

if [ -z "$DUMP" ]; then
  sed -n '4,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
[ -f "$DUMP" ] || die "$DUMP 파일이 없습니다."
# RDB는 REDIS + 4자리 버전으로 시작한다
[ "$(head -c 5 "$DUMP")" = REDIS ] || die "$DUMP 는 redis RDB 파일이 아닙니다. 'head -c 9 $DUMP' 로 확인하세요."

# 교체한 뒤 redis가 못 읽으면 기동에 실패하므로, 같은 이미지로 먼저 읽어 본다
echo "🔎 RDB 확인: $DUMP ($(du -h "$DUMP" | cut -f1), $(head -c 9 "$DUMP"))"
DUMP_ABS=$(cd "$(dirname "$DUMP")" && pwd)/$(basename "$DUMP")
if ! out=$(dc run --rm --no-deps -T -v "$DUMP_ABS:/tmp/restore.rdb:ro" \
            --entrypoint redis-check-rdb redis /tmp/restore.rdb 2>&1); then
  echo "$out" >&2
  die "스테이징 redis가 이 파일을 읽지 못합니다. 운영과 스테이징 redis 버전을 확인하세요."
fi

start_redis
existing=$(rcli DBSIZE)
if [ "$existing" -gt 0 ] && [ "$FORCE" != 1 ]; then
  report
  die "redis에 이미 키 ${existing}개가 있습니다. 버리고 복원하려면 --force 를 붙이세요."
fi

# 교체 중 backend가 캐시를 쓰지 않도록 멈춘다.
# redis는 꺼질 때 메모리를 저장하므로, 반드시 멈춘 뒤에 파일을 넣어야 덮어쓰이지 않는다
echo "⏸️  backend, redis를 정지합니다."
dc stop backend redis >/dev/null 2>&1 || true
id=$(dc ps -a -q redis)
[ -n "$id" ] || die "redis 컨테이너를 찾지 못했습니다."
docker cp "$DUMP" "$id:/data/dump.rdb"
# 공식 이미지 entrypoint가 기동할 때 /data 소유자를 redis로 맞춘다
start_redis

report

loaded=$(rcli DBSIZE)
if [ "$loaded" -eq 0 ]; then
  echo "⚠️  복원 후 키가 0개입니다. 운영 BGSAVE가 끝난 뒤의 파일인지 확인하세요." >&2
  [ "$DELETE_DUMP" = 0 ] || echo "   다시 시도할 수 있도록 $DUMP 는 지우지 않았습니다." >&2
  exit 1
fi
echo "✅ 복원 완료"
if [ "$DELETE_DUMP" = 1 ]; then
  rm -f -- "$DUMP"
  echo "🗑️  $DUMP 삭제"
fi
echo "   ./deploy/staging.sh up 으로 backend를 다시 띄우세요."
