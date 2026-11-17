#!/bin/bash
# BeBot 점검 대기 서버 관리 — Mac에서 실행
#
#   deploy/standby/standby.sh push        # 점검 페이지·nginx 설정을 대기 서버에 설치/갱신
#   deploy/standby/standby.sh sync-cert   # 운영 서버의 Let's Encrypt 인증서를 대기 서버로 복사
#   deploy/standby/standby.sh check       # 인증서 만료일 비교 + 대기 서버 응답 확인 (사용자 영향 없음)
#
# 환경변수 (기본값은 ~/.ssh/config의 Host 별칭):
#   PROD_SSH     운영 서버 ssh 대상     (기본 bebot-prod)
#   STANDBY_SSH  대기 서버 ssh 대상     (기본 bebot-standby)
#   STANDBY_IP   대기 서버 공인 IP      (기본: STANDBY_SSH의 HostName)
#   CERT_NAME    /etc/letsencrypt/live/ 아래 디렉터리 이름 (기본 bebot.co.kr)
#
# 주의: Elastic IP를 대기 서버로 옮긴 동안에는 54.163.78.107이 대기 서버를 가리킴.
#       그동안 sync-cert는 실행하지 말 것 (운영 대신 대기 서버에서 읽게 됨).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROD_SSH="${PROD_SSH:-bebot-prod}"
STANDBY_SSH="${STANDBY_SSH:-bebot-standby}"
CERT_NAME="${CERT_NAME:-bebot.co.kr}"
LE_DIR="/etc/letsencrypt/live/$CERT_NAME"
SSL_DIR="/etc/nginx/ssl/bebot"

standby_ip() {
    if [ -n "${STANDBY_IP:-}" ]; then
        echo "$STANDBY_IP"
    else
        ssh -G "$STANDBY_SSH" | awk '/^hostname /{print $2}'
    fi
}

case "${1:-}" in
    push)
        tmp="$(mktemp -d)"
        trap 'rm -rf "$tmp"' EXIT
        cp "$ROOT/deploy/maintenance/index.html" \
           "$ROOT/deploy/nginx/maintenance-http.conf" \
           "$ROOT/deploy/nginx/snippets/maintenance-web.conf" \
           "$ROOT/deploy/nginx/snippets/maintenance-api.conf" \
           "$ROOT/deploy/standby/nginx-standby.conf" \
           "$ROOT/deploy/standby/setup.sh" "$tmp/"
        ssh "$STANDBY_SSH" 'rm -rf ~/bebot-standby && mkdir -p ~/bebot-standby'
        scp -q "$tmp"/* "$STANDBY_SSH:~/bebot-standby/"
        ssh "$STANDBY_SSH" 'sudo bash ~/bebot-standby/setup.sh'
        ;;
    sync-cert)
        # 개인키는 Mac 디스크에 저장하지 않고 ssh 파이프로만 전달
        ssh "$STANDBY_SSH" "sudo install -d -m 755 $SSL_DIR"
        ssh "$PROD_SSH" "sudo cat $LE_DIR/fullchain.pem" \
            | ssh "$STANDBY_SSH" "sudo sh -c 'umask 022; cat > $SSL_DIR/fullchain.pem.new && mv $SSL_DIR/fullchain.pem.new $SSL_DIR/fullchain.pem'"
        ssh "$PROD_SSH" "sudo cat $LE_DIR/privkey.pem" \
            | ssh "$STANDBY_SSH" "sudo sh -c 'umask 077; cat > $SSL_DIR/privkey.pem.new && mv $SSL_DIR/privkey.pem.new $SSL_DIR/privkey.pem'"
        ssh "$STANDBY_SSH" 'sudo nginx -t && sudo systemctl reload nginx'
        echo "인증서 복사 완료"
        "$0" check
        ;;
    check)
        printf "운영 인증서 만료:  "
        ssh "$PROD_SSH" "sudo openssl x509 -noout -enddate -in $LE_DIR/fullchain.pem" | cut -d= -f2
        printf "대기 인증서 만료:  "
        ssh "$STANDBY_SSH" "sudo openssl x509 -noout -enddate -in $SSL_DIR/fullchain.pem" | cut -d= -f2
        ip="$(standby_ip)"
        echo "대기 서버($ip) 응답 — 기대값: 웹 503, API 503, preflight 204"
        for host in bebot.co.kr www.bebot.co.kr api.bebot.co.kr; do
            path=/; [ "$host" = api.bebot.co.kr ] && path=/api/health
            printf "  %-18s %s\n" "$host" \
                "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$host:443:$ip" -H 'Origin: https://bebot.co.kr' "https://$host$path")"
        done
        printf "  %-18s %s\n" "preflight" \
            "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "api.bebot.co.kr:443:$ip" -X OPTIONS \
                -H 'Origin: https://bebot.co.kr' -H 'Access-Control-Request-Method: POST' https://api.bebot.co.kr/api/chat)"
        ;;
    *)
        sed -n '4,7p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
