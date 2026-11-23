#!/bin/bash
set -euo pipefail

# 사용법 (빌드 서버에서만 실행. 운영·스테이징 서버는 빌드하지 않고 pull 한다):
#   ./deploy/build.sh                       # backend 이미지 + frontend 결과물 (로컬)
#   TARGET=backend ./deploy/build.sh        # backend만
#   TARGET=front ./deploy/build.sh          # frontend만
#   PUSH=1 ./deploy/build.sh                # 빌드 후 둘 다 push (HEAD가 origin에 push돼 있어야 함)
#   BACKEND_IMAGE=<저장소> ./deploy/build.sh  # backend 저장소 변경 (기본 eunsaem338/bebot-backend. ECR 등)
#   FRONT_IMAGE=<저장소> ./deploy/build.sh    # frontend 저장소 변경 (기본 eunsaem338/bebot-frontend)
#
#   # 소셜 로그인 redirect를 운영(bebot.co.kr)이 아닌 주소로 빌드할 때는 이름(FRONT_VARIANT)을 붙인다.
#   # 같은 sha의 운영 빌드와 섞이지 않도록 태그·폴더가 <sha>-<이름> 이 된다.
#   FRONT_VARIANT=local NAVER_REDIRECT_URI=... KAKAO_REDIRECT_URI=... TARGET=front ./deploy/build.sh
#
# 태그는 HEAD의 7자리 SHA다. 사람이 입력하지 않고 git에서만 정한다.
# frontend는 정적 파일만 담은 이미지(FROM scratch)로 만들고, 같은 내용을 dist/web-<태그>/ 에 꺼낸다.
# 서버는 ./deploy/staging.sh 가 이 이미지를 pull 해서 dist/web-<태그>/ 로 꺼내 nginx에 마운트한다.

cd "$(git rev-parse --show-toplevel)"

die() { echo "❌ $*" >&2; exit 1; }

[ -z "$(git status --porcelain)" ] || die "커밋되지 않은 변경이 있습니다. 커밋 후 빌드하세요."

TARGET=${TARGET:-all}
case "$TARGET" in
  all|backend|front) ;;
  *) die "TARGET은 all, backend, front 중 하나여야 합니다." ;;
esac

# 길이를 고정한다. 기본 길이는 저장소 객체 수에 따라 달라져 서버마다 태그가 어긋날 수 있다
TAG=$(git rev-parse --short=7 HEAD)

# 예전 방식(DOCKERHUB_USER)으로 실행하면 의도와 다른 저장소에 push될 수 있어 막는다
[ -z "${DOCKERHUB_USER:-}" ] || die "DOCKERHUB_USER 대신 BACKEND_IMAGE=$DOCKERHUB_USER/bebot-backend 로 지정하세요."

if [ -n "${NAVER_REDIRECT_URI:-}${KAKAO_REDIRECT_URI:-}" ] && [ -z "${FRONT_VARIANT:-}" ]; then
  die "redirect 주소를 바꿔 빌드할 때는 FRONT_VARIANT=<이름> 을 함께 지정하세요 (운영 빌드와 태그가 겹치지 않게)."
fi
case "${FRONT_VARIANT:-}" in
  ''|*[!a-z0-9]*) [ -z "${FRONT_VARIANT:-}" ] || die "FRONT_VARIANT는 영문 소문자·숫자만 씁니다." ;;
esac

if [ "${PUSH:-0}" = "1" ]; then
  # push 안 된 커밋으로 이미지를 만들면 서버가 같은 SHA를 checkout할 수 없다 (이전 배포에서 실제로 막힌 단계)
  git fetch -q origin
  [ -n "$(git branch -r --contains HEAD)" ] \
    || die "HEAD($TAG)가 origin에 없습니다. git push 후 다시 실행하세요."
fi

# staging.sh, docker-compose.yml과 같은 이름으로 만들어야 push 없이도 스테이징에서 바로 쓸 수 있다
BACKEND_IMAGE=${BACKEND_IMAGE:-eunsaem338/bebot-backend}
FRONT_IMAGE=${FRONT_IMAGE:-eunsaem338/bebot-frontend}
FRONT_TAG=$TAG${FRONT_VARIANT:+-$FRONT_VARIANT}

pushed=()

if [ "$TARGET" != "front" ]; then
  IMAGE=$BACKEND_IMAGE:$TAG
  docker build -f backend/Dockerfile -t "$IMAGE" .
  echo "✅ built $IMAGE"
  if [ "${PUSH:-0}" = "1" ]; then
    docker push "$IMAGE"
    pushed+=("$IMAGE")
  fi
fi

if [ "$TARGET" != "backend" ]; then
  IMAGE=$FRONT_IMAGE:$FRONT_TAG
  # 빌드 컨텍스트를 front/로 둔다 (루트 .dockerignore는 front/를 제외함)
  DOCKER_BUILDKIT=1 docker build -f front/Dockerfile.build \
    ${NAVER_REDIRECT_URI:+--build-arg NAVER_REDIRECT_URI=$NAVER_REDIRECT_URI} \
    ${KAKAO_REDIRECT_URI:+--build-arg KAKAO_REDIRECT_URI=$KAKAO_REDIRECT_URI} \
    -t "$IMAGE" front
  echo "✅ built $IMAGE"

  # 서버가 pull 해서 꺼내는 것과 같은 방법으로 꺼낸다 (staging.sh fetch_front와 동일)
  DEST=dist/web-$FRONT_TAG
  TMP=dist/.web-$FRONT_TAG.tmp
  mkdir -p dist && rm -rf "$TMP"
  printf 'FROM %s\n' "$IMAGE" | DOCKER_BUILDKIT=1 docker build -q --output "type=local,dest=$TMP" - >/dev/null
  [ -f "$TMP/index.html" ] || die "$IMAGE 에서 index.html을 꺼내지 못했습니다."
  echo "$FRONT_TAG" > "$TMP/version.txt"
  # nginx 컨테이너(uid 101)가 읽을 수 있도록 읽기 권한을 맞춘다
  chmod -R a+rX "$TMP"
  # frontend가 마운트 중인 폴더는 지우면 403이 되므로 덮어쓰지 않는다 (같은 sha 재빌드)
  if [ -d "$DEST" ]; then
    rm -rf "$TMP"
    echo "ℹ️  $DEST 가 이미 있어 그대로 둡니다 (마운트 중일 수 있음). 바꾸려면 prune-dist 후 다시 빌드하세요."
  else
    mv "$TMP" "$DEST"
    echo "✅ $DEST"
  fi

  if [ "${PUSH:-0}" = "1" ]; then
    docker push "$IMAGE"
    pushed+=("$IMAGE")
  fi
fi

if [ ${#pushed[@]} -gt 0 ]; then
  echo
  printf '✅ pushed %s\n' "${pushed[@]}"
  echo "서버에서:  git fetch && git checkout $TAG && TAG=$TAG ./deploy/staging.sh up"
  [ -z "${FRONT_VARIANT:-}" ] || echo "           (프론트 변형: FRONT_VARIANT=$FRONT_VARIANT 도 함께 지정)"
fi
