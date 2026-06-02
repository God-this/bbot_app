# server.py — FastAPI 서버 (Flutter 앱 ↔ Python 백엔드 브릿지)
#
# 실행: uvicorn server:app --host 0.0.0.0 --port 8000
#
# 엔드포인트:
#   POST /api/auth/google                        — Google 로그인 → JWT 발급
#   GET  /api/auth/me                            — 내 정보 조회
#   GET  /api/health                             — 서버 상태 확인
#   POST /api/chat                               — 질문 → 답변 + 출처  [JWT 필요]
#   GET  /api/chat/sessions                      — 내 대화 세션 목록    [JWT 필요]
#   GET  /api/chat/sessions/{id}/messages        — 세션 메시지 조회     [JWT 필요]
#   DELETE /api/chat/sessions/{id}               — 세션 삭제            [JWT 필요]
#   GET  /api/admin/video-status                 — 영상 상태 조회        [관리자 JWT 필요]
#   POST /api/admin/video-status/refresh         — 영상 상태 즉시 재확인 [관리자 JWT 필요]

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 인증 라우터 및 의존성 임포트
from auth import router as auth_router, chat_router, get_current_user, require_admin, save_chat_message

app = FastAPI(title="BeBot API", version="2.0.0")

# ──────────────────────────────────────────────────────────
# 라우터 등록
# ──────────────────────────────────────────────────────────
app.include_router(auth_router)   # /api/auth/*
app.include_router(chat_router)   # /api/chat/sessions/*

# ──────────────────────────────────────────────────────────
# CORS (Flutter 앱에서 접근 허용)
# ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────
# 영상 상태 캐시 (기존 기능 유지)
# ──────────────────────────────────────────────────────────
_video_status_cache: dict = {"data": None, "checked_at": None}


async def _refresh_video_status():
    try:
        from video_health_checker import VideoHealthChecker
        checker = VideoHealthChecker()
        videos  = checker.get_all_videos()
        results = []
        for video in videos:
            youtube_id = video.get("youtube_id")
            if youtube_id:
                status, message = checker.check_video_status(youtube_id)
            else:
                status, message = "error", "YouTube ID 없음"
            results.append({
                "video_id":  video["video_id"],
                "title":     video["title"],
                "url":       video["url"],
                "youtube_id": youtube_id,
                "status":    status,
                "message":   message,
            })
        _video_status_cache["data"]       = results
        _video_status_cache["checked_at"] = datetime.now().isoformat()
        print(f"✅ 영상 상태 갱신 완료: {len(results)}건")
    except Exception as e:
        print(f"❌ 영상 상태 갱신 오류: {e}")


async def _video_status_scheduler():
    while True:
        await _refresh_video_status()
        await asyncio.sleep(7 * 24 * 3600)  # 1주일마다 반복


@app.on_event("startup")
async def startup():
    asyncio.create_task(_video_status_scheduler())


# ──────────────────────────────────────────────────────────
# Request / Response 모델
# ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str


class SourceDoc(BaseModel):
    title:    Optional[str]   = ""
    url:      Optional[str]   = ""
    content:  Optional[str]   = ""
    book:     Optional[str]   = ""
    page:     Optional[int]   = 0
    video_id: Optional[str]   = ""
    start:    Optional[float] = 0
    end:      Optional[float] = 0


class ChatResponse(BaseModel):
    answer:     str
    sources:    dict   # { web_docs: [...], book_docs: [...], video_docs: [...] }
    session_id: Optional[int] = None   # 저장된 세션 ID


# ──────────────────────────────────────────────────────────
# 공통 엔드포인트
# ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "BeBot API", "version": "2.0.0"}


# ──────────────────────────────────────────────────────────
# 채팅 엔드포인트 (JWT 인증 필수)
# ──────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    req:  ChatRequest,
    user: dict = Depends(get_current_user),   # ← JWT 인증
):
    """
    사용자 질문을 받아 bbot_graph.generate()를 호출하고
    답변 + 출처 정보를 JSON으로 반환합니다.
    대화 내용은 chat_sessions / chat_messages 테이블에 자동 저장됩니다.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    try:
        from bbot_graph import generate

        answer, sources_raw = generate(req.question.strip())

        # 출처 데이터 정리
        raw     = sources_raw if isinstance(sources_raw, dict) else {}
        sources = {
            "web_docs":   raw.get("web_docs",   []),
            "book_docs":  raw.get("book_docs",  []),
            "video_docs": raw.get("video_docs", []),
        }

        # 대화 기록 저장 (비동기로 처리해 응답 지연 최소화)
        session_id = None
        try:
            session_id = save_chat_message(
                user_id  = user["user_id"],
                question = req.question.strip(),
                answer   = answer,
                sources  = raw,
            )
        except Exception as save_err:
            # 저장 실패가 답변 반환을 막지 않도록 처리
            print(f"⚠️ 채팅 기록 저장 실패: {save_err}")

        return ChatResponse(answer=answer, sources=sources, session_id=session_id)

    except Exception as e:
        print(f"❌ 답변 생성 오류: {e}")
        raise HTTPException(status_code=500, detail=f"답변 생성 중 오류 발생: {str(e)}")


# ──────────────────────────────────────────────────────────
# Admin 엔드포인트 (관리자 JWT 필수)
# ──────────────────────────────────────────────────────────

@app.get("/api/admin/video-status")
async def get_video_status(user: dict = Depends(require_admin)):
    """영상 상태 데이터 반환 (캐시 우선). 관리자만 접근 가능."""
    if _video_status_cache["data"] is None:
        await _refresh_video_status()
    results = _video_status_cache["data"] or []
    return {
        "total":         len(results),
        "ok_count":      sum(1 for v in results if v["status"] == "ok"),
        "problem_count": sum(1 for v in results if v["status"] != "ok"),
        "videos":        results,
        "checked_at":    _video_status_cache["checked_at"],
    }


@app.post("/api/admin/video-status/refresh")
async def refresh_video_status(user: dict = Depends(require_admin)):
    """YouTube 상태를 즉시 재확인하고 결과 반환. 관리자만 접근 가능."""
    await _refresh_video_status()
    return await get_video_status(user)


# ──────────────────────────────────────────────────────────
# 직접 실행 시
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)