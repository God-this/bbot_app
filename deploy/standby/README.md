# 점검 대기 서버 (standby)

운영 EC2 **인스턴스 자체를 정지**하는 동안(인스턴스 타입 변경, 디스크 작업 등)이나 EC2가 예기치 않게 죽었을 때도 점검 페이지를 보여주기 위한 별도의 작은 서버입니다.

운영 서버의 Nginx 점검 모드(`deploy/maintenance.sh`)는 운영 EC2가 살아 있어야 동작합니다. 인스턴스가 꺼지면 Nginx도 같이 꺼지므로, **Elastic IP(54.163.78.107)를 대기 서버로 옮겨서** 그동안 대기 서버가 응답하게 합니다. DNS는 건드리지 않으므로 전환이 몇 초 안에 끝납니다.

```
평소     bebot.co.kr ─┐
                      ├─ 54.163.78.107 (EIP) ─→ 운영 EC2 (Nginx + FastAPI)
         api.bebot..  ┘                         대기 서버 (항상 켜져 있고, 아무도 접속하지 않음)

점검 중  bebot.co.kr ─┐
                      ├─ 54.163.78.107 (EIP) ─→ 대기 서버 (모든 요청에 점검 응답)
         api.bebot..  ┘                         운영 EC2 (정지/작업 중)
```

| 요청 | 대기 서버 응답 |
|---|---|
| 웹 (`bebot.co.kr`, `www.bebot.co.kr`, `bebot.kr`, `www.bebot.kr`) | 503 + 점검 페이지 |
| API (`api.bebot.co.kr`) | 503 JSON `{"status":"maintenance",...}` + CORS, preflight는 204 |
| http | https로 301 |

열려 있던 점검 페이지는 IP를 운영으로 되돌리면 자동으로 새로고침됩니다.

파일:
- `nginx-standby.conf`: 대기 서버 Nginx 사이트 설정. 운영과 같은 `deploy/nginx/` 점검 설정을 함께 씀
- `setup.sh`: 대기 서버에서 실행하는 설치 스크립트
- `standby.sh`: Mac에서 실행 (`push`, `sync-cert`, `check`)

---

## 1. 처음 한 번 설정

### 1-1. [콘솔] Elastic IP 확인
EC2 → **네트워크 및 보안 → 탄력적 IP**에 `54.163.78.107`이 있고, 운영 인스턴스에 연결돼 있는지 확인합니다. 목록에 없다면 Elastic IP가 아닌 자동 할당 IP라 인스턴스를 정지하면 주소가 바뀝니다. 이 경우 진행하기 전에 먼저 Elastic IP로 바꿔야 합니다.

### 1-2. [콘솔] 대기 서버 생성
EC2 → **인스턴스 시작** (리전: **us-east-1**, 운영과 같은 리전)

| 항목 | 값 |
|---|---|
| 이름 | `bebot-standby` |
| AMI | Ubuntu Server LTS (64비트 **Arm**) |
| 인스턴스 유형 | `t4g.nano` |
| 키 페어 | 기존 운영 키 또는 새 키 |
| 네트워크 | 운영과 같은 VPC의 퍼블릭 서브넷, 퍼블릭 IP 자동 할당 **활성화** |
| 보안 그룹 (새로 생성) | SSH 22: 내 IP / HTTP 80, HTTPS 443: `0.0.0.0/0`, `::/0` |
| 스토리지 | 8GiB gp3 |

예상 비용은 월 약 $7입니다(인스턴스 약 $3 + 공인 IPv4 약 $3.6 + 디스크 약 $0.6).

### 1-3. [Mac] ssh 별칭 등록
`~/.ssh/config`에 추가합니다 (`standby.sh`가 이 이름을 사용).
```
Host bebot-prod
    HostName 54.163.78.107
    User ubuntu
    IdentityFile ~/.ssh/<운영 키>.pem

Host bebot-standby
    HostName <대기 서버 공인 IP>
    User ubuntu
    IdentityFile ~/.ssh/<대기 서버 키>.pem
```

### 1-4. [Mac] 설치, 인증서 복사, 확인
```
deploy/standby/standby.sh push        # nginx 설치 + 점검 페이지·설정 배포
deploy/standby/standby.sh sync-cert   # 운영 Let's Encrypt 인증서를 대기 서버로 복사 (끝나면 check 자동 실행)
```
`check` 결과에서 두 서버의 인증서 만료일이 같고, `bebot.co.kr 503 / www 503 / api 503 / preflight 204`이면 정상입니다. 이 확인은 `--resolve`로 대기 서버에 직접 요청하므로 실제 사용자에게는 영향이 없습니다.

운영 인증서 디렉터리 이름이 `bebot.co.kr`이 아니면 `CERT_NAME=<이름>`을 앞에 붙입니다 (`sudo ls /etc/letsencrypt/live/`로 확인).

### 1-5. 이후 관리
- **인증서:** Let's Encrypt 인증서는 운영 서버에서만 자동 갱신되고 대기 서버 복사본은 갱신되지 않습니다. **점검 전에는 반드시 `standby.sh check`로 만료일을 비교**하고, 다르면 `sync-cert`를 실행합니다. 현재 만료일은 2026-12-06입니다.
- **점검 페이지를 고쳤을 때:** `standby.sh push`

---

## 2. 점검 절차 (운영 인스턴스 정지)

```
[Mac]  deploy/standby/standby.sh check
```
1. **사전 확인:** 대기 서버 응답이 정상이고 인증서 만료일이 같은지 봅니다.
2. **(권장) 운영에서 먼저 점검 모드 ON:** `[EC2] sudo ~/maintenance.sh on 60`
   사용자는 이때부터 점검 페이지를 봅니다. 운영 Nginx에 점검 설정이 반영돼 있어야 합니다(`deploy/nginx/`).
3. **[콘솔] IP를 대기 서버로 옮기기:** EC2 → 탄력적 IP → `54.163.78.107` 선택 → **작업 → 탄력적 IP 주소 연결**
   - 리소스 유형: 인스턴스 → `bebot-standby`
   - **"이 탄력적 IP 주소의 재연결 허용" 체크** → 연결
4. **전환 확인:** `[Mac] curl -sI https://bebot.co.kr | head -1` → `HTTP/1.1 503` (숫자 503만 보면 됨)
5. **[콘솔] 운영 인스턴스 정지 → 작업 → 시작**
6. **운영 확인:** IP가 없는 동안 운영 인스턴스는 새 공인 IP를 받을 수 있습니다(콘솔 인스턴스 상세에서 확인).
   ```
   [Mac]  ssh -i <운영 키> ubuntu@<운영 새 공인 IP>
   [EC2]  systemctl status bebot && curl -fsS localhost:8000/api/health
   ```
   공인 IP가 없으면 대기 서버를 거쳐 사설 IP로 접속합니다: `ssh -J bebot-standby ubuntu@<운영 사설 IP>`. 이때 운영 보안 그룹이 대기 서버에서 오는 22번을 허용해야 합니다.
7. **[콘솔] IP를 운영으로 되돌리기:** 3번과 같은 방법으로 인스턴스를 운영 인스턴스로 선택 (재연결 허용 체크)
   - 2번에서 점검 모드를 켰다면 운영이 계속 점검 페이지를 보여주고 있습니다. 관리자 IP로 서비스를 확인한 뒤 `[EC2] sudo ~/maintenance.sh off`로 엽니다.
8. **최종 확인:** `[Mac] curl -s https://api.bebot.co.kr/api/health` → `{"status":"ok",...}`

### 예기치 않은 EC2 장애
3번(IP를 대기 서버로 옮기기)만 하면 바로 점검 페이지가 뜹니다. 복구 후 7번으로 되돌립니다.

---

## 주의

- **전환하는 동안 `54.163.78.107`은 대기 서버입니다.**
  - `ssh bebot-prod`, 로컬 DB 터널(5433) 등 이 주소로 가는 접속은 모두 대기 서버로 갑니다.
  - "REMOTE HOST IDENTIFICATION HAS CHANGED" 경고가 나오는 것은 정상입니다. `known_hosts`를 지우지 말고, 6번처럼 운영의 다른 주소로 접속하세요.
  - 이 동안 `standby.sh sync-cert`를 실행하면 안 됩니다.
- **대기 서버 공인 IP:** 운영 IP를 받았다가 돌려준 뒤에는 대기 서버의 공인 IP가 바뀔 수 있습니다. 콘솔에서 확인하고 `~/.ssh/config`의 `bebot-standby`를 갱신하세요. 주소를 고정하려면 대기 서버 전용 Elastic IP를 하나 더 만들어 두고, 7번 뒤에 다시 연결하면 됩니다.
- **대기 서버는 점검 응답만 합니다.** 관리자 IP 예외도 적용되지 않습니다 (서비스를 확인하려면 운영으로 IP를 되돌린 뒤 운영의 점검 모드를 쓰세요).
