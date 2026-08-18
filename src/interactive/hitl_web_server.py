"""Dedicated artifact-driven web interface for HITL workspaces.

This server deliberately does not share the ordinary interactive-manager page.
It exposes one durable snapshot endpoint and uses SSE solely as a refresh hint.
"""

from __future__ import annotations

import hashlib
import html
import json
import queue
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from core.hitl_lock import HitlWorkspaceRunActiveError
from core.hitl_manager_inbox import HitlWebInputError
from core.hitl_workspace_view import HitlWorkspaceView, HitlWorkspaceViewError
from interactive.channel import WebChannel


PAGE = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{TITLE}}</title>
    <link rel="stylesheet" href="/assets/hitl.css">
    <link rel="stylesheet" href="/assets/hitl-graph-key.css">
  </head>
  <body>
    <div id="app"></div>
    <script src="/assets/hitl.js" defer></script>
  </body>
</html>'''

ASSET_DIR = Path(__file__).with_name("static") / "hitl"
ASSET_TYPES = {
    "hitl.css": "text/css; charset=utf-8",
    "hitl-graph-key.css": "text/css; charset=utf-8",
    "hitl.js": "application/javascript; charset=utf-8",
}


def _session_cookie_name(access_token: str) -> str:
    fingerprint = hashlib.sha256(access_token.encode("utf-8")).hexdigest()[:12]
    return f"neurico_hitl_session_{fingerprint}"


def _access_url(base_url: str, access_token: str) -> str:
    parsed = urlsplit(base_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "token"
    ]
    query.append(("token", access_token))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _handler(
    channel: WebChannel,
    workspace: Path,
    title: str,
    run_launcher: Callable[[dict[str, Any]], dict[str, Any]],
    manager_provider: Callable[[], str],
    manager_provider_setter: Callable[[str], str],
    access_token: str,
    session_cookie_name: str,
):
    page = PAGE.replace("{{WORKSPACE}}", html.escape(workspace.name)).replace(
        "{{TITLE}}", html.escape(title)
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _has_access(self) -> bool:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except (KeyError, ValueError):
                return False
            value = cookie.get(session_cookie_name)
            return value is not None and secrets.compare_digest(
                value.value, access_token
            )

        def _bootstrap_access(self) -> bool:
            parsed = urlsplit(self.path)
            if parsed.path not in {"/", "/research"}:
                return False
            supplied = (parse_qs(parsed.query).get("token") or [""])[0]
            if not supplied or not secrets.compare_digest(supplied, access_token):
                return False
            self.send_response(302)
            self.send_header("Location", parsed.path or "/")
            self.send_header(
                "Set-Cookie",
                f"{session_cookie_name}={access_token}; HttpOnly; SameSite=Strict; Path=/",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True

        def _deny_access(self) -> None:
            body = b"HITL manager access denied."
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _same_origin_post(self) -> bool:
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            parsed = urlsplit(origin)
            return (
                parsed.scheme in {"http", "https"}
                and bool(host)
                and parsed.netloc.lower() == host.lower()
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
            )

        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError, OSError):
                # Browsers routinely abandon an in-flight poll while navigating.
                # The snapshot is read-only, so there is no server-side recovery
                # work to perform for a disconnected client.
                pass

        def do_GET(self) -> None:
            if self._bootstrap_access():
                return
            if not self._has_access():
                self._deny_access()
                return
            path = urlsplit(self.path).path
            if path in {"/", "/research"}:
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; connect-src 'self'; "
                    "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/assets/"):
                name = path.removeprefix("/assets/")
                content_type = ASSET_TYPES.get(name)
                asset = ASSET_DIR / name
                if content_type is None or not asset.is_file():
                    self.send_error(404)
                    return
                body = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/snapshot":
                try:
                    snapshot = HitlWorkspaceView(workspace).snapshot()
                    presentation_status = getattr(channel, "presentation_status", None)
                    if callable(presentation_status):
                        snapshot["manager_status"] = presentation_status()
                    live = snapshot.get("live") if isinstance(snapshot.get("live"), dict) else {}
                    current_provider = str(manager_provider() or "").strip().lower()
                    locked_provider = str(live.get("provider") or "").strip().lower()
                    snapshot["manager"] = {
                        "provider": locked_provider if live.get("active") else current_provider,
                        "provider_locked": bool(live.get("active")),
                    }
                    self._json(snapshot)
                except HitlWorkspaceViewError as exc:
                    self._json({"error": str(exc)}, 409)
                return
            if path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                events = channel.subscribe()
                try:
                    while True:
                        try:
                            event = events.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                            continue
                        name = event.get("event", "message")
                        self.wfile.write(
                            f"event: {name}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
                        )
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
                finally:
                    channel.unsubscribe(events)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if not self._has_access() or not self._same_origin_post():
                self._deny_access()
                return
            path = urlsplit(self.path).path
            if path not in {"/input", "/api/queue", "/api/run"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1_000_000:
                    raise ValueError
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if path == "/api/run":
                    self._json(run_launcher(payload), 202)
                    return
                if path == "/api/queue":
                    action = str(payload.get("action", ""))
                    item_id = str(payload.get("id", ""))
                    if action == "update":
                        result = channel.update_queued_input(item_id, str(payload.get("text", "")))
                    elif action == "remove":
                        channel.remove_queued_input(item_id)
                        result = {"status": "accepted", "id": item_id}
                    else:
                        raise ValueError("Unknown queued-message action.")
                    self._json(result, 202)
                    return
                input_kind = str(payload.get("input_kind", "conversation"))
                text = str(payload.get("text", "")).strip()
                if not text and not (
                    input_kind == "resolution_reply" and str(payload.get("option_id", "")).strip()
                ):
                    raise ValueError("Enter a message before sending it.")
                result = channel.submit_input(
                    text,
                    input_kind=input_kind,
                    request_key=payload.get("request_key"),
                    option_id=payload.get("option_id"),
                    client_turn_id=str(payload.get("client_turn_id", "")),
                )
            except HitlWebInputError as exc:
                status = 409 if exc.status in {"stale", "already_resolved"} else 400
                self._json({"status": exc.status, "error": str(exc)}, status)
                return
            except HitlWorkspaceRunActiveError as exc:
                self._json({"status": "conflict", "error": str(exc)}, 409)
                return
            except (ValueError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._json({"status": "invalid", "error": str(exc) or "Enter a message before sending it."}, 400)
                return
            self._json(dict(result), 202)

        def do_PATCH(self) -> None:
            if not self._has_access() or not self._same_origin_post():
                self._deny_access()
                return
            if urlsplit(self.path).path != "/api/manager":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1_000_000:
                    raise ValueError
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                selected = manager_provider_setter(str(payload.get("provider", "")))
            except (ValueError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._json({"status": "invalid", "error": str(exc)}, 400)
                return
            self._json({"status": "accepted", "provider": selected}, 202)

    return Handler


class HitlWebServer:
    """Small HITL-only web server with no generic interactive-manager feeds."""

    def __init__(
        self,
        *,
        channel: WebChannel,
        workspace: Path,
        project_root: Path,
        title: str,
        port: int = 7890,
        host: str = "localhost",
        access_token: Optional[str] = None,
    ) -> None:
        del project_root
        self.channel = channel
        self.workspace = Path(workspace)
        self.title = title
        self.host = host
        self.port = port
        self.access_token = (
            secrets.token_urlsafe(32)
            if access_token is None
            else str(access_token).strip()
        )
        if not self.access_token:
            raise ValueError("HITL web access token must be non-empty.")
        self.session_cookie_name = _session_cookie_name(self.access_token)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._run_launcher: Callable[[dict[str, Any]], dict[str, Any]] = self._run_unavailable
        self._manager_provider: Callable[[], str] = lambda: ""
        self._manager_provider_setter: Callable[[str], str] = self._provider_unavailable

    @staticmethod
    def _run_unavailable(_payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("AutoResearch launch is unavailable for this HITL workspace.")

    @staticmethod
    def _provider_unavailable(_provider: str) -> str:
        raise RuntimeError("Manager backend selection is unavailable for this workspace.")

    def set_run_launcher(
        self,
        launcher: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._run_launcher = launcher

    def set_manager_provider_getter(self, getter: Callable[[], str]) -> None:
        self._manager_provider = getter

    def set_manager_provider_setter(self, setter: Callable[[str], str]) -> None:
        self._manager_provider_setter = setter

    @property
    def url(self) -> str:
        return self.access_url(f"http://{self.host}:{self.port}")

    def access_url(self, base_url: str) -> str:
        return _access_url(base_url, self.access_token)

    def start(self) -> None:
        handler = _handler(
            self.channel,
            self.workspace,
            self.title,
            lambda payload: self._run_launcher(payload),
            lambda: self._manager_provider(),
            lambda provider: self._manager_provider_setter(provider),
            self.access_token,
            self.session_cookie_name,
        )
        last_error: Optional[OSError] = None
        for port in range(self.port, self.port + 10):
            try:
                self._httpd = ThreadingHTTPServer((self.host, port), handler)
                self.port = int(self._httpd.server_address[1])
                break
            except OSError as exc:
                last_error = exc
        if self._httpd is None:
            raise RuntimeError(f"Could not bind a HITL web port near {self.port}: {last_error}")
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
