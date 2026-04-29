import os
import re
import requests
from config import get_conn


class VideoHealthChecker:
    def get_all_videos(self):
        """DB에서 고유 YouTube URL 기준으로 영상 목록 반환"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables WHERE table_name = 'video_db'
                        );
                    """)
                    if not cur.fetchone()[0]:
                        print("⚠️ video_db 테이블이 없습니다.")
                        return []

                    cur.execute("""
                        SELECT DISTINCT ON (video_id)
                            video_id, title, url
                        FROM video_db
                        ORDER BY video_id
                    """)
                    rows = cur.fetchall()
        except Exception as e:
            print(f"⚠️ DB 조회 오류: {e}")
            return []

        results = []
        for video_id, title, url in rows:
            youtube_id = self._extract_youtube_id(url or '')
            results.append({
                'video_id': video_id,
                'title': title or '',
                'url': url or '',
                'youtube_id': youtube_id,
            })
        return results

    def _extract_youtube_id(self, url: str):
        if not url:
            return None
        patterns = [
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
            r'[?&]v=([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    def check_video_status(self, youtube_id: str):
        """YouTube 영상 접근 가능 여부 확인. (status, message) 튜플 반환.
        status: 'ok' | 'private' | 'unlisted' | 'unavailable' | 'error'
        """
        if not youtube_id:
            return 'error', 'YouTube ID 없음'

        api_key = os.getenv('YOUTUBE_API_KEY')
        if api_key:
            return self._check_via_api(youtube_id, api_key)
        return self._check_via_oembed(youtube_id)

    def _check_via_api(self, youtube_id: str, api_key: str):
        try:
            resp = requests.get(
                'https://www.googleapis.com/youtube/v3/videos',
                params={'id': youtube_id, 'part': 'status,snippet', 'key': api_key},
                timeout=10,
            )
            data = resp.json()
            items = data.get('items', [])
            if not items:
                return 'unavailable', '영상 없음 또는 삭제됨'
            privacy = items[0].get('status', {}).get('privacyStatus', '')
            if privacy == 'private':
                return 'private', '비공개 영상'
            if privacy == 'unlisted':
                return 'unlisted', '일부 공개 영상'
            return 'ok', '정상'
        except Exception as e:
            return 'error', f'API 오류: {e}'

    def _check_via_oembed(self, youtube_id: str):
        # YouTube oEmbed: 공개 영상이면 200, 비공개면 401, 삭제/없음이면 404
        try:
            url = (
                'https://www.youtube.com/oembed'
                f'?url=https://www.youtube.com/watch?v={youtube_id}&format=json'
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return 'ok', '정상'
            if resp.status_code == 401:
                return 'private', '비공개 영상'
            if resp.status_code == 404:
                return 'unavailable', '영상 없음 또는 삭제됨'
            return 'error', f'HTTP {resp.status_code}'
        except Exception as e:
            return 'error', f'연결 오류: {e}'
