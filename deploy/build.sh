#!/bin/bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "❌ 커밋되지 않은 변경이 있습니다. 커밋 후 빌드하세요." >&2
  exit 1
fi

TAG=$(git rev-parse --short HEAD)
IMAGE=bebot-backend:$TAG

docker build -f backend/Dockerfile -t "$IMAGE" .
echo "✅ built $IMAGE"

if [ "${PUSH:-0}" = "1" ]; then
  : "${DOCKERHUB_USER:?DOCKERHUB_USER 환경변수가 필요합니다}"
  docker tag "$IMAGE" "$DOCKERHUB_USER/$IMAGE"
  docker push "$DOCKERHUB_USER/$IMAGE"
  echo "✅ pushed $DOCKERHUB_USER/$IMAGE"
fi
