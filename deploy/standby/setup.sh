#!/bin/bash
# BeBot 점검 대기 서버 설치 — 대기 서버(Ubuntu)에서 실행
#
# 보통 Mac에서 deploy/standby/standby.sh push 로 번들을 올리고 이 스크립트를 실행함.
# 직접 실행 시: 번들 디렉터리에서 sudo ./setup.sh
#
# 여러 번 실행해도 됨 (점검 페이지·설정 갱신용)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" != 0 ]; then
    echo "sudo로 실행하세요" >&2
    exit 1
fi

if ! command -v nginx >/dev/null; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx
fi

install -d -m 755 /var/www/maintenance /etc/nginx/snippets /etc/nginx/ssl
install -m 644 "$DIR/index.html" /var/www/maintenance/index.html
touch /var/www/maintenance/ON
rm -f /var/www/maintenance/info.json

install -m 644 "$DIR/maintenance-http.conf" /etc/nginx/conf.d/maintenance-http.conf
install -m 644 "$DIR/maintenance-web.conf" "$DIR/maintenance-api.conf" /etc/nginx/snippets/
install -m 644 "$DIR/nginx-standby.conf" /etc/nginx/sites-available/bebot-standby
ln -sf /etc/nginx/sites-available/bebot-standby /etc/nginx/sites-enabled/bebot-standby
rm -f /etc/nginx/sites-enabled/default

if [ ! -s /etc/nginx/ssl/bebot/fullchain.pem ] || [ ! -s /etc/nginx/ssl/bebot/privkey.pem ]; then
    echo "설정 파일은 설치했지만 인증서가 없습니다."
    echo "Mac에서 deploy/standby/standby.sh sync-cert 를 실행한 뒤 다시 확인하세요."
    exit 0
fi

nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx
echo "대기 서버 설치 완료"
