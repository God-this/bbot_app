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
#   ./deploy/staging.sh prune-dist [개수] [-y] # 오래된 dist/web-* 정리 (사용 중·HEAD·최근 N개(기본 3)는 남김)
#   ./deploy/staging.sh compose <인자...>     # 그 밖의 docker compose 명령
#
# dist/web-* 는 직접 지우지 말고 prune-dist로 정리한다.
# frontend가 마운트한 폴더를 지우면(같은 sha로 다시 빌드해도) 화면이 403이 된다.
#
# 태그 결정 (환경변수로 지정하면 그 값을 우선. tags 출력에 출처를 표시):
#   BACKEND_TAG: <HEAD SHA> 이미지가 있으면 그것, 없으면 가장 최근에 만든 bebot-backend 이미지
#   FRONT_TAG:   dist/web-<HEAD SHA>가 있으면 그것, 없으면 가장 최근 dist/web-*

cd "$(dirname "$0")/.."

ENV_FILE=backend/.env.staging
# compose의 기본값과 같아야 한다. 태그를 찾는 저장소와 compose가 띄우는 저장소가 어긋나지 않도록 export한다
BACKEND_IMAGE=${BACKEND_IMAGE:-eunsaem338/bebot-backend}
export BACKEND_IMAGE

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE 이 없습니다."

HEAD_SHA=$(git rev-parse --short HEAD)

# 셸에 예전에 export한 값이 남아 있으면 HEAD와 다른 버전이 뜰 수 있어 출처를 기록한다
BACKEND_SRC=환경변수
if [ -z "${BACKEND_TAG:-}" ]; then
  if docker image inspect "$BACKEND_IMAGE:$HEAD_SHA" >/dev/null 2>&1; then
    BACKEND_TAG=$HEAD_SHA BACKEND_SRC=HEAD
  else
    # docker images의 기본 정렬은 이미지 저장소 설정에 따라 달라 생성 시각으로 직접 정렬한다
    BACKEND_TAG=$(docker images "$BACKEND_IMAGE" --format '{{.CreatedAt}}\t{{.Tag}}' 2>/dev/null \
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
  docker compose version >/dev/null 2>&1 || die "docker compose(v2 플러그인)가 없습니다."
  docker info >/dev/null 2>&1 \
    || die "Docker 데몬에 접속할 수 없습니다. 데몬이 떠 있는지, 현재 사용자가 docker 그룹에 있는지 확인하세요."

  # 빈 값이면 기동 중 int("")로 죽는 키 (config.py, redis_cache.py)
  local key
  for key in OLLAMA_EMBED_DIM REDIS_PORT REDIS_DB; do
    if grep -qE "^${key}=\s*$" "$ENV_FILE"; then
      die "$ENV_FILE 의 ${key}= 가 빈 값입니다. 줄을 지우거나 값을 넣으세요."
    fi
  done

  # 비어 있으면 기동은 되지만 기능이 깨지는 키 (.env.staging.example의 [필수])
  local missing=()
  for key in OPENAI_API_KEY DB_PASSWORD JWT_SECRET_KEY \
             NAVER_CLIENT_ID NAVER_CLIENT_SECRET KAKAO_REST_API_KEY KAKAO_CLIENT_SECRET; do
    grep -qE "^${key}=[[:space:]]*[^[:space:]]" "$ENV_FILE" || missing+=("$key")
  done
  [ ${#missing[@]} -eq 0 ] || die "$ENV_FILE 에 [필수] 값이 비어 있습니다: ${missing[*]}"

  # compose는 --env-file의 값도 읽지만 이 스크립트는 셸 값만 보므로, 넣어 두면 둘이 다른 저장소를 쓰게 된다
  if grep -qE "^BACKEND_IMAGE=" "$ENV_FILE"; then
    die "BACKEND_IMAGE는 $ENV_FILE 이 아니라 셸에서 지정하세요 (BACKEND_IMAGE=... ./deploy/staging.sh up)."
  fi

  [ -n "$BACKEND_TAG" ] || die "backend 이미지를 찾지 못했습니다. BACKEND_TAG=<sha> 로 지정하세요."
  [ -n "$FRONT_TAG" ] || die "dist/web-* 가 없습니다. TARGET=front ./deploy/build.sh 로 먼저 빌드하세요."
  [ -d "dist/web-$FRONT_TAG" ] || die "dist/web-$FRONT_TAG 가 없습니다."

  # 로컬에 없으면 미리 받는다. compose up 중 실패하면 권한 문제인지 알기 어렵다
  local image="$BACKEND_IMAGE:$BACKEND_TAG" out
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "⬇️  $image 가 로컬에 없어 pull 합니다."
    if ! out=$(docker pull "$image" 2>&1); then
      if echo "$out" | grep -qiE 'denied|unauthorized|authentication required|no basic auth'; then
        die "$image pull 권한이 없습니다. 'docker login' 후 다시 실행하세요 (ECR이면 aws ecr get-login-password)."
      fi
      die "$image pull 실패:
$out"
    fi
  fi

  # 다른 프로세스가 포트를 쓰고 있는지 (frontend 컨테이너 자신은 제외)
  local port=${FRONT_PORT:-8080}
  if ! dc ps --status running --services 2>/dev/null | grep -qx frontend \
     && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; then
    die "호스트 ${port} 포트를 이미 사용 중입니다. FRONT_PORT=<다른 포트> 로 지정하세요."
  fi
}

FRONT_ROOT=/usr/share/nginx/html

frontend_id() { dc ps -a -q frontend 2>/dev/null || true; }

# frontend가 마운트한 호스트 폴더 이름 (예: web-af28806). 컨테이너가 없으면 빈 값
mounted_dist() {
  local id src
  id=$(frontend_id)
  [ -n "$id" ] || return 0
  src=$(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$FRONT_ROOT\"}}{{.Source}}{{end}}{{end}}" "$id" 2>/dev/null || true)
  echo "${src##*/}"
}

# 마운트한 폴더를 호스트에서 지우면 컨테이너는 지워진 빈 폴더를 계속 본다.
# 같은 이름으로 다시 만들어도 마찬가지라, 호스트 폴더가 아니라 컨테이너 안에서 확인한다.
frontend_dist_ok() {
  local id
  id=$(dc ps -q --status running frontend 2>/dev/null || true)
  [ -n "$id" ] || return 0
  docker exec "$id" test -f "$FRONT_ROOT/index.html" 2>/dev/null && return 0
  echo "⚠️  frontend가 마운트한 $(mounted_dist) 를 컨테이너에서 읽을 수 없습니다 (지워졌거나 다시 빌드됨 → 화면 403)." >&2
  return 1
}

# 태그가 같으면 compose는 frontend를 다시 만들지 않으므로 직접 다시 만든다
ensure_frontend() {
  if ! frontend_dist_ok; then
    echo "🔁 frontend를 다시 만듭니다."
    dc up -d --force-recreate --no-deps frontend
  fi
}

prune_dist() {
  local keep_n=3 yes=0 arg
  for arg in "$@"; do
    case "$arg" in
      -y) yes=1 ;;
      ''|*[!0-9]*) die "사용법: prune-dist [보존 개수] [-y]" ;;
      *) keep_n=$arg ;;
    esac
  done

  local mounted d name i=0 del=()
  mounted=$(mounted_dist)
  # 최근 빌드 순. 사용 중인 폴더, HEAD 폴더, 최근 N개는 남긴다
  while IFS= read -r d; do
    d=${d%/} name=${d##*/} i=$((i + 1))
    if [ "$i" -le "$keep_n" ] || [ "$name" = "$mounted" ] || [ "$name" = "web-$HEAD_SHA" ]; then
      continue
    fi
    del+=("$d")
  done < <(ls -td dist/web-*/ 2>/dev/null || true)

  echo "남김: 최근 ${keep_n}개, 사용 중 ${mounted:-없음}, HEAD web-$HEAD_SHA"
  if [ ${#del[@]} -eq 0 ]; then
    echo "지울 dist가 없습니다."
    return 0
  fi
  printf '  삭제: %s\n' "${del[@]}"
  if [ "$yes" -ne 1 ]; then
    local ans
    read -r -p "삭제할까요? [y/N] " ans || true
    [ "$ans" = y ] || { echo "취소했습니다."; return 0; }
  fi
  rm -rf -- "${del[@]}"
  echo "✅ ${#del[@]}개 삭제"
}

show_tags() {
  echo "HEAD=$HEAD_SHA"
  echo "BACKEND_IMAGE=$BACKEND_IMAGE"
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
    ensure_frontend
    dc ps
    ;;
  down)
    for arg in "$@"; do
      case "$arg" in -v|--volumes) die "volume 삭제는 지원하지 않습니다 (DB가 지워짐). 필요하면 compose 명령으로 직접 실행하세요." ;; esac
    done
    dc down "$@"
    ;;
  ps)
    dc ps "$@"
    frontend_dist_ok || echo "   ./deploy/staging.sh up 으로 다시 만드세요." >&2
    ;;
  logs)             dc logs "$@" ;;
  recreate-backend)
    preflight
    show_tags
    dc up -d --force-recreate backend
    # nginx는 시작할 때 backend 주소를 한 번만 찾으므로 함께 재시작한다
    dc restart frontend
    ensure_frontend
    dc ps
    ;;
  psql)
    dc exec ${TTY[@]+"${TTY[@]}"} postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
    ;;
  redis)            dc exec ${TTY[@]+"${TTY[@]}"} redis redis-cli "$@" ;;
  tags)             show_tags ;;
  prune-dist)       prune_dist "$@" ;;
  compose)          dc "$@" ;;
  *)
    # 파일 맨 위 설명 주석(첫 빈 줄 전까지)을 출력한다
    sed -n '4,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    [ -z "$cmd" ] || exit 1
    ;;
esac
