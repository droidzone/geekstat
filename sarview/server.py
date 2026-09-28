"""Loopback HTTP server for the viewer."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from sarview.config import Settings, viewer_payload
from sarview.errors import SarviewError
from sarview.validate import BIND_HOST, validate_bind, validate_port

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}


class ViewerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(service, port: int = 8765, bind: str = BIND_HOST, viewer: dict | None = None) -> ViewerServer:
    bind = validate_bind(bind)
    port = validate_port(port, allow_ephemeral=True)
    if viewer is None:
        viewer = viewer_payload(Settings())
    handler = _handler(service, WEB_ROOT, viewer)

    try:
        return ViewerServer((bind, port), handler)
    except OSError as exc:
        raise SarviewError(f"could not bind {bind}:{port}: {exc}", status=500) from exc


def _handler(service, web_root: Path, viewer: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            try:
                if path == "/api/settings":
                    self._json(200, viewer)
                    return
                if path == "/api/catalog":
                    payload = service.catalog_payload(refresh=_flag(query, "refresh"))
                    self._json(200, payload)
                    return
                if path == "/api/day":
                    day = _one(query, "date")
                    if not day:
                        raise SarviewError("date is required")
                    payload = service.get_day(
                        day,
                        refresh=_flag(query, "refresh"),
                        start=_one(query, "start"),
                        end=_one(query, "end"),
                    )
                    self._json(200, payload)
                    return
                if path == "/api/health":
                    self._json(200, {"ok": True, "bind": BIND_HOST})
                    return
                target = _static(web_root, path)
                if target is None:
                    self._bytes(404, b"Not found", "text/plain; charset=utf-8")
                    return
                content_type = _TYPES.get(target.suffix, mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                self._bytes(200, target.read_bytes(), content_type)
            except SarviewError as exc:
                self._json(exc.status, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - last-resort local error page
                self._json(500, {"error": str(exc)})

        def log_message(self, fmt, *args):
            message = fmt % args
            if "/api/" in message:
                super().log_message(fmt, *args)

        def _json(self, status: int, payload: dict) -> None:
            self._bytes(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _flag(query: dict, key: str) -> bool:
    return _one(query, key) in {"1", "true", "yes"}


def _one(query: dict, key: str) -> str | None:
    values = query.get(key) or []
    if not values or values[0] == "":
        return None
    return values[0]


def _static(root: Path, url_path: str) -> Path | None:
    relative = "index.html" if url_path in {"", "/"} else url_path.lstrip("/")
    if relative.startswith("/") or "\\" in relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None
