#!/bin/bash
set -euo pipefail

# 사용법:
#   ./deploy/build.sh                       # backend 이미지 + frontend 결과물
#   TARGET=front ./deploy/build.sh          # frontend만 (backend 재빌드 생략)
#   PUSH=1 DOCKERHUB_USER=... ./deploy/build.sh   # backend 이미지 push
#   NAVER_REDIRECT_URI=... KAKAO_REDIRECT_URI=... TARGET=front ./deploy/build.sh
#
# frontend는 이미지가 아니라 dist/web-<sha>/ 정적 파일로 만든다.
# 스테이징은 이 폴더를 nginx에 마운트하고, 운영은 같은 폴더를 S3에 올린다.

cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "❌ 커밋되지 않은 변경이 있습니다. 커밋 후 빌드하세요." >&2
  exit 1
fi

TARGET=${TARGET:-all}
case "$TARGET" in
  all|backend|front) ;;
  *) echo "❌ TARGET은 all, backend, front 중 하나여야 합니다." >&2; exit 1 ;;
esac

TAG=$(git rev-parse --short HEAD)

if [ "$TARGET" != "front" ]; then
  IMAGE=bebot-backend:$TAG
  docker build -f backend/Dockerfile -t "$IMAGE" .
  echo "✅ built $IMAGE"

  if [ "${PUSH:-0}" = "1" ]; then
    : "${DOCKERHUB_USER:?DOCKERHUB_USER 환경변수가 필요합니다}"
    docker tag "$IMAGE" "$DOCKERHUB_USER/$IMAGE"
    docker push "$DOCKERHUB_USER/$IMAGE"
    echo "✅ pushed $DOCKERHUB_USER/$IMAGE"
  fi
fi

if [ "$TARGET" != "backend" ]; then
  # 빌드 컨텍스트를 front/로 둔다 (루트 .dockerignore는 front/를 제외함)
  DEST=dist/web-$TAG
  rm -rf "$DEST"
  DOCKER_BUILDKIT=1 docker build -f front/Dockerfile.build \
    ${NAVER_REDIRECT_URI:+--build-arg NAVER_REDIRECT_URI=$NAVER_REDIRECT_URI} \
    ${KAKAO_REDIRECT_URI:+--build-arg KAKAO_REDIRECT_URI=$KAKAO_REDIRECT_URI} \
    --output "type=local,dest=$DEST" \
    front
  echo "$TAG" > "$DEST/version.txt"
  echo "✅ built $DEST"
fi
