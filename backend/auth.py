# auth.py — 인증 라우터 (Google/Naver/Kakao 소셜 로그인 + 게스트 로그인 + JWT)
#
# 엔드포인트:
#   POST /api/auth/google          — Google idToken/accessToken 검증 → JWT 발급
#   POST /api/auth/guest           — device_id 기반 게스트 로그인 → JWT 발급
#   POST /api/auth/naver           — 모바일: Naver access_token 검증 → JWT 발급
#   POST /api/auth/naver/web       — 웹: Naver 인가 코드(code) 교환 → JWT 발급
#   POST /api/auth/kakao           — 모바일: Kakao access_token 검증 → JWT 발급
#   POST /api/auth/kakao/web       — 웹: Kakao 인가 코드(code) 교환 → JWT 발급
#   GET  /api/auth/me              — 내 정보 조회 (JWT 필요)
#   GET  /api/chat/sessions        — 내 대화 세션 목록 (JWT 필요)
#   GET  /api/chat/sessions/{id}/messages — 세션 메시지 조회 (JWT 필요)
#   DELETE /api/chat/sessions/{id} — 세션 삭제 (JWT 필요)

import os
import json
import httpx

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from config import get_conn
from logging_config import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────
# 설정값 (환경변수)
# ──────────────────────────────────────────────────────────

SECRET_KEY  = os.getenv("JWT_SECRET_KEY", "CHANGE-THIS-SECRET-IN-PRODUCTION")
ALGORITHM   = "HS256"
# 토큰 유효기간: 7일 (모바일 앱은 길게 설정하는 것이 UX상 유리)
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

# 웹 네이버 로그인(인가 코드 교환)에만 필요. 모바일 네이티브 SDK는 사용 안 함.
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 웹 카카오 로그인(인가 코드 교환)에만 필요. 모바일 네이티브 SDK는 사용 안 함.
KAKAO_REST_API_KEY  = os.getenv("KAKAO_REST_API_KEY")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")

router   = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()


# ──────────────────────────────────────────────────────────
# JWT 유틸리티
# ──────────────────────────────────────────────────────────

def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub":  str(user_id),
        "role": role,
        "exp":  expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """토큰 디코딩. 만료/변조 시 HTTPException 401 발생."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": int(payload["sub"]), "role": payload.get("role", "user")}
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 토큰입니다.")


# ──────────────────────────────────────────────────────────
# FastAPI 의존성
# ──────────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """로그인된 사용자 정보를 반환하는 의존성."""
    return decode_token(credentials.credentials)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """관리자 전용 엔드포인트에 사용하는 의존성."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")
    return user


# ──────────────────────────────────────────────────────────
# DB 헬퍼
# ──────────────────────────────────────────────────────────

def upsert_user(
    provider: str,
    provider_id: str,
    email: str,
    nickname: str,
) -> dict:
    """
    소셜/게스트 로그인 시 사용자 정보를 upsert합니다.
    - 최초 로그인: INSERT (role='user')
    - 재로그인: 이메일/닉네임만 UPDATE (role은 유지)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (provider, provider_id, email, nickname)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (provider, provider_id) DO UPDATE
                    SET email    = EXCLUDED.email,
                        nickname = EXCLUDED.nickname
                RETURNING id, role, nickname
            """, (provider, provider_id, email, nickname))
            row = cur.fetchone()
            conn.commit()

    return {
        "id":       row[0],
        "role":     row[1],
        "nickname": row[2],
    }


# ──────────────────────────────────────────────────────────
# Request 모델
# ──────────────────────────────────────────────────────────

class GoogleLoginRequest(BaseModel):
    id_token: Optional[str] = None       # 모바일: google_sign_in 패키지의 idToken
    access_token: Optional[str] = None   # 웹: 팝업 플로우에서 받은 accessToken


class GuestLoginRequest(BaseModel):
    device_id: str  # 클라이언트가 로컬에 생성/저장한 UUID (재실행해도 동일 게스트 유지용)


class NaverLoginRequest(BaseModel):
    access_token: str  # 모바일: flutter_naver_login에서 받은 accessToken


class NaverWebLoginRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str  # 네이버 콘솔에 등록한 Callback URL과 정확히 일치해야 함


class KakaoLoginRequest(BaseModel):
    access_token: str  # 모바일: kakao_flutter_sdk_user에서 받은 accessToken


class KakaoWebLoginRequest(BaseModel):
    code: str
    redirect_uri: str  # 카카오 콘솔에 등록한 Redirect URI와 정확히 일치해야 함


# ──────────────────────────────────────────────────────────
# 인증 엔드포인트 — Google
# ──────────────────────────────────────────────────────────

@router.post("/google")
async def google_login(req: GoogleLoginRequest):
    """
    Flutter에서 전달받은 Google 토큰을 검증하고 JWT를 발급합니다.
    모바일(id_token)과 웹(access_token)은 검증 방식이 다릅니다.
    """
    if not req.id_token and not req.access_token:
        raise HTTPException(status_code=400, detail="id_token 또는 access_token이 필요합니다.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        if req.id_token:
            resp = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": req.id_token},
            )
        else:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {req.access_token}"},
            )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail=f"Google 토큰 검증 실패 (status={resp.status_code})"
        )

    info = resp.json()

    if "sub" not in info:
        raise HTTPException(status_code=401, detail="Google 토큰에 사용자 정보가 없습니다.")

    user = upsert_user(
        provider    = "google",
        provider_id = info["sub"],
        email       = info.get("email", ""),
        nickname    = info.get("name", ""),
    )

    token = create_access_token(user["id"], user["role"])

    logger.info("Google 로그인: [%s] %s (role=%s)", user["id"], info.get("email", ""), user["role"])

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["id"],
        "role":         user["role"],
        "nickname":     user["nickname"],
        "email":        info.get("email", ""),
    }


# ──────────────────────────────────────────────────────────
# 인증 엔드포인트 — 게스트
# ──────────────────────────────────────────────────────────

@router.post("/guest")
async def guest_login(req: GuestLoginRequest):
    """
    비회원(게스트) 로그인. 외부 검증 없이 클라이언트가 보낸 device_id를
    provider_id로 사용해 users 테이블에 upsert하고 JWT를 발급합니다.
    """
    if not req.device_id or not req.device_id.strip():
        raise HTTPException(status_code=400, detail="device_id가 필요합니다.")

    user = upsert_user(
        provider    = "guest",
        provider_id = req.device_id.strip(),
        email       = "",
        nickname    = "게스트",
    )

    token = create_access_token(user["id"], user["role"])

    logger.info("게스트 로그인: [%s] device_id=%s (role=%s)", user["id"], req.device_id, user["role"])

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["id"],
        "role":         user["role"],
        "nickname":     user["nickname"],
        "email":        "",
    }


# ──────────────────────────────────────────────────────────
# 인증 엔드포인트 — Naver
# ──────────────────────────────────────────────────────────

async def _naver_login_with_access_token(access_token: str) -> dict:
    """네이버 access_token으로 프로필 조회 → upsert → JWT 발급 (모바일/웹 공용 로직)"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://openapi.naver.com/v1/nid/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail=f"네이버 토큰 검증 실패 (status={resp.status_code})"
        )

    data = resp.json()

    # 네이버는 HTTP 200이어도 resultcode로 성공 여부를 별도 표기함
    if data.get("resultcode") != "00":
        raise HTTPException(status_code=401, detail="네이버 토큰이 유효하지 않습니다.")

    info = data.get("response", {})

    if "id" not in info:
        raise HTTPException(status_code=401, detail="네이버 토큰에 사용자 정보가 없습니다.")

    user = upsert_user(
        provider    = "naver",
        provider_id = str(info["id"]),
        email       = info.get("email", ""),
        nickname    = info.get("nickname", info.get("name", "")),
    )

    token = create_access_token(user["id"], user["role"])

    logger.info("네이버 로그인: [%s] %s (role=%s)", user["id"], info.get("email", ""), user["role"])

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["id"],
        "role":         user["role"],
        "nickname":     user["nickname"],
        "email":        info.get("email", ""),
    }


@router.post("/naver")
async def naver_login(req: NaverLoginRequest):
    """모바일: flutter_naver_login이 발급한 access_token 검증 → JWT 발급"""
    return await _naver_login_with_access_token(req.access_token)


@router.post("/naver/web")
async def naver_web_login(req: NaverWebLoginRequest):
    """
    웹: 브라우저 리다이렉트로 받은 인가 코드(code)를 access_token으로 교환한 뒤 JWT 발급.
    client_secret이 필요하므로 반드시 서버에서만 처리 (프론트에 노출 금지).
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="네이버 클라이언트 정보가 서버에 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.get(
            "https://nid.naver.com/oauth2.0/token",
            params={
                "grant_type":    "authorization_code",
                "client_id":     NAVER_CLIENT_ID,
                "client_secret": NAVER_CLIENT_SECRET,
                "code":          req.code,
                "state":         req.state,
                "redirect_uri":  req.redirect_uri,
            },
        )

    token_data = token_resp.json()

    if "access_token" not in token_data:
        raise HTTPException(
            status_code=401,
            detail=f"네이버 토큰 발급 실패: {token_data.get('error_description', token_data)}"
        )

    return await _naver_login_with_access_token(token_data["access_token"])


# ──────────────────────────────────────────────────────────
# 인증 엔드포인트 — Kakao
# ──────────────────────────────────────────────────────────

async def _kakao_login_with_access_token(access_token: str) -> dict:
    """카카오 access_token으로 프로필 조회 → upsert → JWT 발급 (모바일/웹 공용 로직)"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail=f"카카오 토큰 검증 실패 (status={resp.status_code})"
        )

    info = resp.json()

    if "id" not in info:
        raise HTTPException(status_code=401, detail="카카오 토큰에 사용자 정보가 없습니다.")

    kakao_account = info.get("kakao_account", {})
    profile       = kakao_account.get("profile", {})

    user = upsert_user(
        provider    = "kakao",
        provider_id = str(info["id"]),
        email       = kakao_account.get("email", ""),
        nickname    = profile.get("nickname", ""),
    )

    token = create_access_token(user["id"], user["role"])

    logger.info("카카오 로그인: [%s] %s (role=%s)", user["id"], kakao_account.get("email", ""), user["role"])

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["id"],
        "role":         user["role"],
        "nickname":     user["nickname"],
        "email":        kakao_account.get("email", ""),
    }


@router.post("/kakao")
async def kakao_login(req: KakaoLoginRequest):
    """모바일: kakao_flutter_sdk_user가 발급한 access_token 검증 → JWT 발급"""
    return await _kakao_login_with_access_token(req.access_token)


@router.post("/kakao/web")
async def kakao_web_login(req: KakaoWebLoginRequest):
    """
    웹: 브라우저 리다이렉트로 받은 인가 코드(code)를 access_token으로 교환한 뒤 JWT 발급.
    client_secret이 필요하므로 반드시 서버에서만 처리 (프론트에 노출 금지).
    """
    if not KAKAO_REST_API_KEY or not KAKAO_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="카카오 클라이언트 정보가 서버에 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            "https://kauth.kakao.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            data={
                "grant_type":    "authorization_code",
                "client_id":     KAKAO_REST_API_KEY,
                "client_secret": KAKAO_CLIENT_SECRET,
                "redirect_uri":  req.redirect_uri,
                "code":          req.code,
            },
        )

    token_data = token_resp.json()

    if "access_token" not in token_data:
        raise HTTPException(
            status_code=401,
            detail=f"카카오 토큰 발급 실패: {token_data.get('error_description', token_data)}"
        )

    return await _kakao_login_with_access_token(token_data["access_token"])


# ──────────────────────────────────────────────────────────
# 사용자 정보 조회
# ──────────────────────────────────────────────────────────

@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """현재 로그인한 사용자 정보를 반환합니다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, nickname, role, created_at
                FROM users
                WHERE id = %s
            """, (user["user_id"],))
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return {
        "id":          row[0],
        "email":       row[1],
        "nickname":    row[2],
        "role":        row[3],
        "created_at":  str(row[4]),
    }


# ──────────────────────────────────────────────────────────
# 채팅 기록 라우터 (chat_sessions / chat_messages) — 변경 없음
# ──────────────────────────────────────────────────────────

chat_router = APIRouter(prefix="/api/chat", tags=["chat-history"])


def get_or_create_session(
    user_id:        int,
    first_question: str,
    session_id:     int | None = None,
) -> int:
    """
    session_id가 주어지고 해당 세션이 이 사용자 소유이면 재사용합니다.
    그렇지 않으면 항상 새 세션을 생성합니다.
    Returns: session_id (int)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if session_id is not None:
                cur.execute(
                    "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                row = cur.fetchone()
                if row:
                    return session_id

            title = first_question[:30] + ("..." if len(first_question) > 30 else "")
            cur.execute("""
                INSERT INTO chat_sessions (user_id, title)
                VALUES (%s, %s)
                RETURNING id
            """, (user_id, title))
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id


def save_chat_message(
    user_id:    int,
    question:   str,
    answer:     str,
    sources:    dict,
    session_id: int | None = None,
):
    """질문(user) + 답변(assistant)을 chat_messages에 저장합니다."""
    session_id = get_or_create_session(user_id, question, session_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (%s, 'user', %s)
            """, (session_id, question))

            clean_sources = {
                k: v for k, v in sources.items()
                if k in ("web_docs", "book_docs", "video_docs")
            }
            cur.execute("""
                INSERT INTO chat_messages (session_id, role, content, sources)
                VALUES (%s, 'assistant', %s, %s::jsonb)
            """, (session_id, answer, json.dumps(clean_sources, ensure_ascii=False)))

            conn.commit()

    return session_id


@chat_router.get("/sessions")
def get_sessions(
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    """내 대화 세션 목록을 최신순으로 반환합니다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    COUNT(m.id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.id
                WHERE s.user_id = %s
                GROUP BY s.id, s.title, s.created_at
                ORDER BY s.created_at DESC
                LIMIT %s
            """, (user["user_id"], limit))
            rows = cur.fetchall()

    return [
        {
            "id":            r[0],
            "title":         r[1],
            "created_at":    str(r[2]),
            "message_count": r[3],
        }
        for r in rows
    ]


@chat_router.get("/sessions/{session_id}/messages")
def get_messages(
    session_id: int,
    user: dict = Depends(get_current_user),
):
    """세션의 메시지 목록을 시간순으로 반환합니다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM chat_sessions WHERE id = %s",
                (session_id,)
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if row[0] != user["user_id"]:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, role, content, sources, created_at
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at ASC
            """, (session_id,))
            rows = cur.fetchall()

    return [
        {
            "id":         r[0],
            "role":       r[1],
            "content":    r[2],
            "sources":    r[3],
            "created_at": str(r[4]),
        }
        for r in rows
    ]


@chat_router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    user: dict = Depends(get_current_user),
):
    """세션과 하위 메시지를 모두 삭제합니다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM chat_sessions WHERE id = %s",
                (session_id,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
            if row[0] != user["user_id"]:
                raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

            cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
            conn.commit()

    return {"ok": True, "deleted_session_id": session_id}
