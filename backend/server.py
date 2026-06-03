# server.py — FastAPI 서버 (Flutter 앱 ↔ Python 백엔드 브릿지)
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
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import router as auth_router, chat_router, get_current_user, require_admin, save_chat_message

app = FastAPI(title="BeBot API", version="2.0.0")

# ──────────────────────────────────────────────────────────
# 영상 상태 갱신 기능 플래그
# False = 비활성화
# ──────────────────────────────────────────────────────────
VIDEO_HEALTH_CHECK_ENABLED = False

# ──────────────────────────────────────────────────────────
# 정적 파일 (책 이미지)
# ──────────────────────────────────────────────────────────
_images_dir = Path(__file__).parent / "extracted_images"
if _images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")

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
    if not VIDEO_HEALTH_CHECK_ENABLED:
        return
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
                "video_id":   video["video_id"],
                "title":      video["title"],
                "url":        video["url"],
                "youtube_id": youtube_id,
                "status":     status,
                "message":    message,
            })
        _video_status_cache["data"]       = results
        _video_status_cache["checked_at"] = datetime.now().isoformat()
        print(f"✅ 영상 상태 갱신 완료: {len(results)}건")
    except Exception as e:
        print(f"❌ 영상 상태 갱신 오류: {e}")


async def _video_status_scheduler():
    while True:
        await _refresh_video_status()
        await asyncio.sleep(7 * 24 * 3600)


@app.on_event("startup")
async def startup():
    if VIDEO_HEALTH_CHECK_ENABLED:
        asyncio.create_task(_video_status_scheduler())


# ──────────────────────────────────────────────────────────
# Request / Response 모델
# ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question:   str
    session_id: Optional[int] = None


class ChatResponse(BaseModel):
    answer:      str
    sources:     dict
    top_sources: list       = []
    images:      list[str]  = []
    session_id:  Optional[int] = None


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
    user: dict = Depends(get_current_user),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    try:
        from bbot_graph import generate

        answer, sources_raw = generate(req.question.strip())

        raw = sources_raw if isinstance(sources_raw, dict) else {}
        sources = {
            "web_docs":   raw.get("web_docs",   []),
            "book_docs":  raw.get("book_docs",  []),
            "video_docs": raw.get("video_docs", []),
        }

        image_urls  = []
        for doc in sources["book_docs"]:
            image_urls.extend(doc.get("images", []))

        top_sources = raw.get("top_sources", [])

        session_id = None
        try:
            session_id = save_chat_message(
                user_id    = user["user_id"],
                question   = req.question.strip(),
                answer     = answer,
                sources    = raw,
                session_id = req.session_id,
            )
        except Exception as save_err:
            print(f"⚠️ 채팅 기록 저장 실패: {save_err}")

        return ChatResponse(
            answer      = answer,
            sources     = sources,
            top_sources = top_sources,
            images      = image_urls,
            session_id  = session_id,
        )

    except Exception as e:
        print(f"❌ 답변 생성 오류: {e}")
        raise HTTPException(status_code=500, detail=f"답변 생성 중 오류 발생: {str(e)}")


# ──────────────────────────────────────────────────────────
# Admin 엔드포인트 (관리자 JWT 필수)
# ──────────────────────────────────────────────────────────

@app.get("/api/admin/video-status")
async def get_video_status(user: dict = Depends(require_admin)):
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
    await _refresh_video_status()
    return await get_video_status(user)


# ──────────────────────────────────────────────────────────
# 직접 실행 시
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
