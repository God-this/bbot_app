# auth.py — 인증 라우터 (Google 소셜 로그인 + JWT)
#
# 엔드포인트:
#   POST /api/auth/google          — Google idToken 검증 → JWT 발급
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

# ──────────────────────────────────────────────────────────
# 설정값 (환경변수)
# ──────────────────────────────────────────────────────────

SECRET_KEY  = os.getenv("JWT_SECRET_KEY", "CHANGE-THIS-SECRET-IN-PRODUCTION")
ALGORITHM   = "HS256"
# 토큰 유효기간: 7일 (모바일 앱은 길게 설정하는 것이 UX상 유리)
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

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
    profile_img: str,
) -> dict:
    """
    소셜 로그인 시 사용자 정보를 upsert합니다.
    - 최초 로그인: INSERT (role='user')
    - 재로그인: 이메일/닉네임/프로필 이미지만 UPDATE (role은 유지)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (provider, provider_id, email, nickname, profile_img)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (provider, provider_id) DO UPDATE
                    SET email       = EXCLUDED.email,
                        nickname    = EXCLUDED.nickname,
                        profile_img = EXCLUDED.profile_img
                RETURNING id, role, nickname, profile_img
            """, (provider, provider_id, email, nickname, profile_img))
            row = cur.fetchone()
            conn.commit()

    return {
        "id":          row[0],
        "role":        row[1],
        "nickname":    row[2],
        "profile_img": row[3],
    }


# ──────────────────────────────────────────────────────────
# Request 모델
# ──────────────────────────────────────────────────────────

class GoogleLoginRequest(BaseModel):
    id_token: str  # Flutter google_sign_in 패키지에서 받은 idToken


# ──────────────────────────────────────────────────────────
# 인증 엔드포인트
# ──────────────────────────────────────────────────────────

@router.post("/google")
async def google_login(req: GoogleLoginRequest):
    """
    Flutter에서 전달받은 Google idToken을 검증하고 JWT를 발급합니다.

    Flow:
      1. Google tokeninfo API로 idToken 유효성 검증
      2. users 테이블 upsert
      3. JWT 발급 후 반환
    """
    # Google 공식 tokeninfo 엔드포인트로 검증
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": req.id_token},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail=f"Google 토큰 검증 실패 (status={resp.status_code})"
        )

    info = resp.json()

    # 필수 필드 확인
    if "sub" not in info:
        raise HTTPException(status_code=401, detail="Google 토큰에 사용자 정보가 없습니다.")

    user = upsert_user(
        provider    = "google",
        provider_id = info["sub"],
        email       = info.get("email", ""),
        nickname    = info.get("name", ""),
        profile_img = info.get("picture", ""),
    )

    token = create_access_token(user["id"], user["role"])

    print(f"✅ Google 로그인: [{user['id']}] {info.get('email', '')} (role={user['role']})")

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user["id"],
        "role":         user["role"],
        "nickname":     user["nickname"],
        "profile_img":  user["profile_img"],
        "email":        info.get("email", ""),
    }


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """현재 로그인한 사용자 정보를 반환합니다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, nickname, profile_img, role, created_at
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
        "profile_img": row[3],
        "role":        row[4],
        "created_at":  str(row[5]),
    }


# ──────────────────────────────────────────────────────────
# 채팅 기록 라우터 (chat_sessions / chat_messages)
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
            # 기존 세션 검증
            if session_id is not None:
                cur.execute(
                    "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                row = cur.fetchone()
                if row:
                    return session_id

            # 새 세션 생성 (첫 질문 앞 30자를 제목으로)
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
            # 사용자 질문
            cur.execute("""
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (%s, 'user', %s)
            """, (session_id, question))

            # 어시스턴트 답변 + 출처
            # sources에서 chat_history 키 제거 (DB 저장 불필요)
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
            # 본인 세션인지 확인
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
            "sources":    r[3],   # JSONB → dict (psycopg2가 자동 파싱)
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
