#!/bin/bash
set -euo pipefail

# compose로 운영 중인 서버(운영 EC2, 스테이징)에서 DB 덤프와 redis RDB를 만든다.
# 결과는 db-restore.sh, redis-restore.sh 가 그대로 받는 형식이다.
#
# 사용법:
#   ./deploy/dump.sh [저장 폴더]          # 기본 ~/bebot_dump. 파일: bebot_<시각>.dump / .rdb
#
#   # 서버의 저장소를 바꾸지 않고 Mac에서 실행 (서버 체크아웃이 이 스크립트보다 오래됐을 때)
#   ssh -i <키> ubuntu@<서버> 'BEBOT_DIR=~/bbot_app bash -s' < deploy/dump.sh
#
# - 서비스를 멈추지 않는다. pg_dump는 시작 시점의 일관된 스냅숏을 뜨고, 이어서 redis BGSAVE를 한다.
#   둘 사이 몇 초 동안 생긴 캐시 차이는 테스트 용도로 무시한다.
# - 파일에는 운영 개인정보(사용자, 대화 기록, 질문·답변 캐시)가 들어 있다. 권한 600으로 만들고,
#   옮긴 뒤에는 서버·중간 사본을 지운다.
# - 나중에 S3 주기 백업도 이 스크립트 결과를 올리는 방식으로 붙인다.

# 파일로 실행하면 저장소 루트로, 'bash -s'(표준입력)로 실행하면 BEBOT_DIR(기본 ~/bbot_app)로 간다
if [ -f "${BASH_SOURCE[0]:-}" ]; then
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
else
  cd "${BEBOT_DIR:-$HOME/bbot_app}"
fi

ENV_FILE=backend/.env.staging
OUT_DIR=${1:-$HOME/bebot_dump}
STAMP=$(date +%Y%m%d-%H%M%S)
DB_OUT=$OUT_DIR/bebot_$STAMP.dump
RDB_OUT=$OUT_DIR/bebot_$STAMP.rdb

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$(pwd)/$ENV_FILE 이 없습니다. 저장소 위치가 다르면 BEBOT_DIR=<경로> 로 지정하세요."

# 'bash -s'로 실행하면 스크립트 본문이 표준입력이므로, docker가 나머지 본문을 읽어 가지 않게 막는다
dc() {
  BACKEND_TAG=${BACKEND_TAG:-none} FRONT_TAG=${FRONT_TAG:-none} \
    docker compose --env-file "$ENV_FILE" "$@" </dev/null
}
rcli() { dc exec -T redis redis-cli "$@" | tr -d '\r'; }

[ -n "$(dc ps -q --status running postgres)" ] || die "postgres 컨테이너가 떠 있지 않습니다."
[ -n "$(dc ps -q --status running redis)" ] || die "redis 컨테이너가 떠 있지 않습니다."

umask 077
mkdir -p "$OUT_DIR"
avail_kb=$(df -Pk "$OUT_DIR" | awk 'NR==2 {print $4}')
echo "저장 폴더 $OUT_DIR (여유 $((avail_kb / 1024))MB)"

# 1) DB 전체 (custom 형식). 일부 테이블만 뜨면 사용자·대화 기록이 빠진다
echo "⏳ pg_dump"
dc exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$DB_OUT" \
  || { rm -f "$DB_OUT"; die "pg_dump 실패"; }
[ "$(head -c 5 "$DB_OUT")" = PGDMP ] || { rm -f "$DB_OUT"; die "덤프 형식이 올바르지 않습니다."; }
tables=$(dc exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "SELECT count(*) FROM pg_tables WHERE schemaname = '"'public'"'"' \
  | tr -d '\r')
echo "  DB 테이블 ${tables}개, $(du -h "$DB_OUT" | cut -f1)"

# 2) redis. LASTSAVE가 바뀐 뒤에 복사해야 한다 (전에 복사하면 0바이트·이전 파일)
echo "⏳ redis BGSAVE"
keys=$(rcli DBSIZE)
before=$(rcli LASTSAVE)
rcli BGSAVE >/dev/null
for _ in $(seq 1 120); do
  [ "$(rcli LASTSAVE)" != "$before" ] && break
  sleep 1
done
[ "$(rcli LASTSAVE)" != "$before" ] || die "BGSAVE가 120초 안에 끝나지 않았습니다 (redis 로그 확인)."
dc cp redis:/data/dump.rdb "$RDB_OUT"
chmod 600 "$RDB_OUT"
[ "$(head -c 5 "$RDB_OUT")" = REDIS ] || die "RDB 형식이 올바르지 않습니다."
echo "  redis $(rcli INFO server | sed -n 's/^redis_version://p'), 키 ${keys}개, $(du -h "$RDB_OUT" | cut -f1)"

echo
ls -l "$DB_OUT" "$RDB_OUT"
echo "✅ 완료. 받는 쪽에서: ./deploy/db-restore.sh <dump> --force --delete-dump"
echo "                     ./deploy/redis-restore.sh <rdb> --force --delete-dump"
