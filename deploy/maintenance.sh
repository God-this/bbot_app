#!/bin/bash
# BeBot 점검 모드 ON/OFF
#
# Nginx(snippets/maintenance-*.conf)가 $MAINT_DIR/ON 파일 유무로 점검 모드를 판단함.
# 플래그 파일 방식이라 nginx reload 없이 전환됨.
#
# 사용법:
#   sudo deploy/maintenance.sh on [예상_소요_분]   # 점검 시작. 분을 주면 페이지에 예상 완료 시각 표시
#   sudo deploy/maintenance.sh off                  # 점검 종료
#   deploy/maintenance.sh status
#
# 환경변수:
#   MAINT_DIR  점검 파일 위치 (기본 /var/www/maintenance, 로컬 리허설은 deploy/maintenance)
set -euo pipefail

MAINT_DIR="${MAINT_DIR:-/var/www/maintenance}"
FLAG="$MAINT_DIR/ON"
INFO="$MAINT_DIR/info.json"

usage() {
    sed -n '7,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

cmd="${1:-}"
case "$cmd" in
    on)
        eta="${2:-}"
        if [ -n "$eta" ] && ! [[ "$eta" =~ ^[1-9][0-9]*$ ]]; then
            echo "예상 소요 분은 양의 정수여야 합니다: $eta" >&2
            exit 1
        fi
        if [ ! -f "$MAINT_DIR/index.html" ]; then
            echo "$MAINT_DIR/index.html 이 없습니다. 점검 페이지를 먼저 복사하세요." >&2
            exit 1
        fi
        umask 022
        if [ -n "$eta" ]; then
            tmp="$(mktemp "$MAINT_DIR/.info.XXXXXX")"
            printf '{"started_at":"%s","eta_minutes":%s}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$eta" > "$tmp"
            chmod 644 "$tmp"
            mv "$tmp" "$INFO"
        else
            rm -f "$INFO"
        fi
        touch "$FLAG"
        echo "점검 모드 ON ($FLAG)${eta:+ — 예상 ${eta}분}"
        ;;
    off)
        rm -f "$FLAG" "$INFO"
        echo "점검 모드 OFF"
        ;;
    status)
        if [ -f "$FLAG" ]; then
            echo "점검 모드 ON (since $(date -r "$FLAG" '+%Y-%m-%d %H:%M:%S'))"
            [ -f "$INFO" ] && cat "$INFO"
        else
            echo "점검 모드 OFF"
        fi
        ;;
    *)
        usage
        ;;
esac
