#!/bin/bash
# BeBot 점검 모드 로컬 리허설 (Docker 필요, 레포 어디서 실행해도 됨)
#
#   deploy/nginx/test/run.sh up        # nginx:1.28 컨테이너 기동 (웹 :8088, API :8089)
#   deploy/nginx/test/run.sh backend   # 가짜 백엔드 :8000 (포그라운드, Ctrl+C = 백엔드 다운)
#   deploy/nginx/test/run.sh on [분]   # 점검 플래그 ON
#   deploy/nginx/test/run.sh off       # 점검 플래그 OFF
#   deploy/nginx/test/run.sh down      # 컨테이너 삭제 + 플래그 정리
#
# 브라우저 확인 URL (점검 페이지가 로컬 API를 보도록 health 덮어쓰기):
#   http://localhost:8088/?health=http://localhost:8089/api/health
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
NAME=bebot-maint-test
TMP="${TMPDIR:-/tmp}/bebot-maint-test"
export MAINT_DIR="$ROOT/deploy/maintenance"

case "${1:-}" in
    up)
        mkdir -p "$TMP"
        # 운영 http 설정에 로컬 웹 출처만 CORS 허용으로 추가한 테스트용 사본
        awk '{print} /default "";/ && !done {print "    \"http://localhost:8088\" $http_origin;"; done=1}' \
            "$ROOT/deploy/nginx/maintenance-http.conf" > "$TMP/maintenance-http.conf"
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        docker run -d --name "$NAME" -p 8088:80 -p 8089:81 \
            --add-host host.docker.internal:host-gateway \
            -v "$TMP/maintenance-http.conf:/etc/nginx/conf.d/maintenance-http.conf:ro" \
            -v "$ROOT/deploy/nginx/test/maintenance-test.conf:/etc/nginx/conf.d/default.conf:ro" \
            -v "$ROOT/deploy/nginx/snippets:/etc/nginx/snippets:ro" \
            -v "$ROOT/deploy/maintenance:/var/www/maintenance:ro" \
            nginx:1.28 >/dev/null
        sleep 1
        docker exec "$NAME" nginx -t
        echo "웹: http://localhost:8088/?health=http://localhost:8089/api/health"
        echo "API: http://localhost:8089/api/health"
        ;;
    backend)
        exec python3 "$ROOT/deploy/nginx/test/fake_backend.py" 8000
        ;;
    on)
        "$ROOT/deploy/maintenance.sh" on ${2:-}
        ;;
    off)
        "$ROOT/deploy/maintenance.sh" off
        ;;
    down)
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        "$ROOT/deploy/maintenance.sh" off
        echo "테스트 컨테이너 삭제"
        ;;
    *)
        sed -n '4,11p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
