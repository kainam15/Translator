"""Small local web UI and JSON API for the Google Translate RPC client."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google_translate_client import GoogleTranslateError, translate


PROJECT_DIR = Path(__file__).resolve().parent
INDEX_FILE = PROJECT_DIR / "static" / "index.html"
MAX_REQUEST_BYTES = 64 * 1024


class TranslatorHandler(BaseHTTPRequestHandler):
    server_version = "TranslatorLab/1.0"

    def _send_headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if path in {"/", "/index.html"}:
            try:
                body = INDEX_FILE.read_bytes()
            except OSError as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"无法读取 UI: {exc}"},
                )
                return
            self._send_headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return

        if path == "/favicon.ico":
            self._send_headers(HTTPStatus.NO_CONTENT, "image/x-icon", 0)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlsplit(self.path).path != "/api/translate":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"ok": False, "error": "Content-Type 必须是 application/json"},
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "请求体为空或过大"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "请求体必须是有效的 UTF-8 JSON"},
            )
            return

        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "JSON 根节点必须是 object"},
            )
            return

        text = payload.get("text")
        source = payload.get("source", "auto")
        target = payload.get("target", "zh-CN")
        if not all(isinstance(value, str) for value in (text, source, target)):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "text、source 和 target 必须是字符串"},
            )
            return

        try:
            result = translate(text, source=source, target=target)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except GoogleTranslateError as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "translation": result.text,
                "detectedSourceLanguage": result.detected_source_language,
                "targetLanguage": result.target_language,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动本地 Translator 测试 UI")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), TranslatorHandler)
    print(f"Translator UI: http://{args.host}:{server.server_port}")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
