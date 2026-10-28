#!/bin/bash
set -euo pipefail

# 스테이징 compose 실행 래퍼 (emptycan)
# 태그·--env-file·실행 위치를 매번 맞추지 않아도 되도록 한곳에 모은다.
#
# 사용법:
#   ./deploy/staging.sh up [서비스...]       # 기동 (사전 점검 후)
#   ./deploy/staging.sh down                 # 정지 (volume 유지. -v는 일부러 지원하지 않음)
#   ./deploy/staging.sh ps
#   ./deploy/staging.sh logs [서비스] [옵션]  # 예: logs backend --since 5m
#   ./deploy/staging.sh recreate-backend     # .env.staging 변경 반영: backend 재생성 + frontend 재시작
#   ./deploy/staging.sh psql [psql 옵션]      # 예: psql -c "SELECT count(*) FROM users;"
#   ./deploy/staging.sh redis [redis-cli 명령] # 예: redis --scan --pattern 'bebot:cache:*'
#   ./deploy/staging.sh tags                 # 사용할 태그만 출력
#   ./deploy/staging.sh compose <인자...>     # 그 밖의 docker compose 명령
#
# 태그 결정 (환경변수로 지정하면 그 값을 우선. tags 출력에 출처를 표시):
#   BACKEND_TAG: <HEAD SHA> 이미지가 있으면 그것, 없으면 가장 최근에 만든 bebot-backend 이미지
#   FRONT_TAG:   dist/web-<HEAD SHA>가 있으면 그것, 없으면 가장 최근 dist/web-*

cd "$(dirname "$0")/.."

ENV_FILE=backend/.env.staging
BACKEND_REPO=eunsaem338/bebot-backend

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE 이 없습니다."

HEAD_SHA=$(git rev-parse --short HEAD)

# 셸에 예전에 export한 값이 남아 있으면 HEAD와 다른 버전이 뜰 수 있어 출처를 기록한다
BACKEND_SRC=환경변수
if [ -z "${BACKEND_TAG:-}" ]; then
  if docker image inspect "$BACKEND_REPO:$HEAD_SHA" >/dev/null 2>&1; then
    BACKEND_TAG=$HEAD_SHA BACKEND_SRC=HEAD
  else
    # docker images의 기본 정렬은 이미지 저장소 설정에 따라 달라 생성 시각으로 직접 정렬한다
    BACKEND_TAG=$(docker images "$BACKEND_REPO" --format '{{.CreatedAt}}\t{{.Tag}}' 2>/dev/null \
      | grep -v '<none>' | sort -r | head -1 | cut -f2 || true)
    BACKEND_SRC="최근 이미지, HEAD 아님"
  fi
fi

FRONT_SRC=환경변수
if [ -z "${FRONT_TAG:-}" ]; then
  if [ -d "dist/web-$HEAD_SHA" ]; then
    FRONT_TAG=$HEAD_SHA FRONT_SRC=HEAD
  else
    LATEST=$(ls -td dist/web-*/ 2>/dev/null | head -1 || true)
    FRONT_TAG=${LATEST:+$(basename "$LATEST")}
    FRONT_TAG=${FRONT_TAG#web-}
    FRONT_SRC="최근 빌드, HEAD 아님"
  fi
fi
export BACKEND_TAG FRONT_TAG

# down/ps/logs 등은 태그 값이 쓰이지 않지만 compose가 파일 전체를 해석하므로 자리 값을 넣는다
dc() {
  BACKEND_TAG=${BACKEND_TAG:-none} FRONT_TAG=${FRONT_TAG:-none} \
    docker compose --env-file "$ENV_FILE" "$@"
}

preflight() {
  [ -n "$BACKEND_TAG" ] || die "backend 이미지를 찾지 못했습니다. BACKEND_TAG=<sha> 로 지정하세요."
  [ -n "$FRONT_TAG" ] || die "dist/web-* 가 없습니다. TARGET=front ./deploy/build.sh 로 먼저 빌드하세요."
  [ -d "dist/web-$FRONT_TAG" ] || die "dist/web-$FRONT_TAG 가 없습니다."

  # 빈 값이면 기동 중 int("")로 죽는 키 (config.py, redis_cache.py)
  local key
  for key in OLLAMA_EMBED_DIM REDIS_PORT REDIS_DB; do
    if grep -qE "^${key}=\s*$" "$ENV_FILE"; then
      die "$ENV_FILE 의 ${key}= 가 빈 값입니다. 줄을 지우거나 값을 넣으세요."
    fi
  done

  # 다른 프로세스가 포트를 쓰고 있는지 (frontend 컨테이너 자신은 제외)
  local port=${FRONT_PORT:-8080}
  if ! dc ps --status running --services 2>/dev/null | grep -qx frontend \
     && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; then
    die "호스트 ${port} 포트를 이미 사용 중입니다. FRONT_PORT=<다른 포트> 로 지정하세요."
  fi
}

show_tags() {
  echo "HEAD=$HEAD_SHA"
  echo "BACKEND_TAG=$BACKEND_TAG ($BACKEND_SRC)"
  echo "FRONT_TAG=$FRONT_TAG ($FRONT_SRC)"
  echo "FRONT_PORT=${FRONT_PORT:-8080}"
  if [ "$BACKEND_TAG" != "$HEAD_SHA" ] || [ "$FRONT_TAG" != "$HEAD_SHA" ]; then
    echo "⚠️  HEAD와 다른 버전입니다. 의도한 것이 아니면 'unset BACKEND_TAG FRONT_TAG' 후 다시 실행하거나 ./deploy/build.sh 로 빌드하세요."
  fi
}

TTY=()
[ -t 0 ] || TTY=(-T)

cmd=${1:-}
if [ $# -gt 0 ]; then shift; fi

case "$cmd" in
  up)
    preflight
    show_tags
    dc up -d "$@"
    dc ps
    ;;
  down)
    for arg in "$@"; do
      case "$arg" in -v|--volumes) die "volume 삭제는 지원하지 않습니다 (DB가 지워짐). 필요하면 compose 명령으로 직접 실행하세요." ;; esac
    done
    dc down "$@"
    ;;
  ps)               dc ps "$@" ;;
  logs)             dc logs "$@" ;;
  recreate-backend)
    preflight
    show_tags
    dc up -d --force-recreate backend
    # nginx는 시작할 때 backend 주소를 한 번만 찾으므로 함께 재시작한다
    dc restart frontend
    dc ps
    ;;
  psql)
    dc exec ${TTY[@]+"${TTY[@]}"} postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
    ;;
  redis)            dc exec ${TTY[@]+"${TTY[@]}"} redis redis-cli "$@" ;;
  tags)             show_tags ;;
  compose)          dc "$@" ;;
  *)
    sed -n '4,20p' "$0" | sed 's/^# \{0,1\}//'
    [ -z "$cmd" ] || exit 1
    ;;
esac
