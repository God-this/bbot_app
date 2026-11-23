"""점검 모드 리허설용 가짜 백엔드 — /api/health만 FastAPI와 같은 형태로 응답.

deploy/nginx/test/run.sh backend 로 실행. 끄면 '백엔드 다운', 켜면 '복구' 상황이 됨.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            body = {"status": "ok", "service": "BeBot API (fake)", "version": "test"}
            self._send(200, json.dumps(body).encode())
        else:
            self._send(404, b'{"detail":"Not Found"}')

    def do_OPTIONS(self):
        self._send(204)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"fake backend on :{port} (Ctrl+C로 종료 = 백엔드 다운)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
