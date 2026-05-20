# server.py — FastAPI 서버 (Flutter 앱 ↔ Python 백엔드 브릿지)
#
# 기존 bbot_graph.generate() 함수를 REST API로 노출합니다.
# 실행: uvicorn server:app --host 0.0.0.0 --port 8000
#
# 엔드포인트:
#   POST /api/chat                       — 질문 → 답변 + 출처
#   GET  /api/health                     — 서버 상태 확인
#   GET  /api/admin/video-status         — 영상 상태 조회 (캐시)
#   POST /api/admin/video-status/refresh — 영상 상태 즉시 재확인

import sys
import asyncio
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="BeBot API", version="1.0.0")

_images_dir = Path(__file__).parent / "extracted_images"
if _images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")

# 영상 상태 캐시 
_video_status_cache: dict = {"data": None, "checked_at": None}


async def _refresh_video_status():
    try:
        from video_health_checker import VideoHealthChecker
        checker = VideoHealthChecker()
        videos = checker.get_all_videos()
        results = []
        for video in videos:
            youtube_id = video.get("youtube_id")
            if youtube_id:
                status, message = checker.check_video_status(youtube_id)
            else:
                status, message = "error", "YouTube ID 없음"
            results.append({
                "video_id": video["video_id"],
                "title": video["title"],
                "url": video["url"],
                "youtube_id": youtube_id,
                "status": status,
                "message": message,
            })
        _video_status_cache["data"] = results
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

# CORS 설정 (Flutter 앱에서 접근 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────── Request / Response 모델 ────────
class ChatRequest(BaseModel):
    question: str


class SourceDoc(BaseModel):
    title: Optional[str] = ""
    url: Optional[str] = ""
    content: Optional[str] = ""
    book: Optional[str] = ""
    page: Optional[int] = 0
    video_id: Optional[str] = ""
    start: Optional[float] = 0
    end: Optional[float] = 0


class ChatResponse(BaseModel):
    answer: str
    sources: dict          # { web_docs: [...], book_docs: [...], video_docs: [...] }
    top_sources: list      # 관련성 상위 3개 (score 기준, UI 표시용)
    images: list[str] = []

# ──────── 엔드포인트 ────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "BeBot API"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    사용자 질문을 받아 bbot_graph.generate()를 호출하고
    답변 + 출처 정보를 JSON으로 반환합니다.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    try:
        from bbot_graph import generate

        answer, sources_raw = generate(req.question.strip())

        # 출처 데이터 정리
        raw = sources_raw if isinstance(sources_raw, dict) else {}
        sources = {
            "web_docs":   raw.get("web_docs", []),
            "book_docs":  raw.get("book_docs", []),
            "video_docs": raw.get("video_docs", []),
        }

        image_urls = []
        for doc in sources["book_docs"]:
            image_urls.extend(doc.get("images", []))

        top_sources = raw.get("top_sources", [])

        return ChatResponse(answer=answer, sources=sources, top_sources=top_sources, images=image_urls)

    except Exception as e:
        print(f"❌ 답변 생성 오류: {e}")
        raise HTTPException(status_code=500, detail=f"답변 생성 중 오류 발생: {str(e)}")


# ──────── Admin 엔드포인트 ────────
@app.get("/api/admin/video-status")
async def get_video_status():
    """영상 상태 데이터 반환 (캐시 우선)"""
    if _video_status_cache["data"] is None:
        await _refresh_video_status()
    results = _video_status_cache["data"] or []
    return {
        "total": len(results),
        "ok_count": sum(1 for v in results if v["status"] == "ok"),
        "problem_count": sum(1 for v in results if v["status"] != "ok"),
        "videos": results,
        "checked_at": _video_status_cache["checked_at"],
    }


@app.post("/api/admin/video-status/refresh")
async def refresh_video_status():
    """YouTube 상태를 즉시 재확인하고 결과 반환"""
    await _refresh_video_status()
    return await get_video_status()


# ──────── 직접 실행 시 ────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
