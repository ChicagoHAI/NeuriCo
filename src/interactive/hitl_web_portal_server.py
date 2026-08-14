"""Authenticated multi-idea web portal for HITL workspaces."""

from __future__ import annotations

import html
import json
import queue
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from cli.hitl_web_portal import HitlWebWorkspaceRegistry
from core.hitl_lock import HitlWorkspaceRunActiveError, resolve_hitl_manager_provider
from core.hitl_manager_inbox import HitlWebInputError
from core.hitl_workspace_view import HitlWorkspaceViewError
from interactive.hitl_web_server import (
    ASSET_DIR,
    ASSET_TYPES,
    PAGE,
    _access_url,
    _session_cookie_name,
)


def _handler(
    registry: HitlWebWorkspaceRegistry,
    title: str,
    initial_idea_id: str,
    access_token: str,
    session_cookie_name: str,
):
    page = PAGE.replace("{{TITLE}}", html.escape(title))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def _has_access(self) -> bool:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except (KeyError, ValueError):
                return False
            value = cookie.get(session_cookie_name)
            return value is not None and secrets.compare_digest(value.value, access_token)

        def _bootstrap_access(self) -> bool:
            parsed = urlsplit(self.path)
            if parsed.path not in {"/", "/research"}:
                return False
            supplied = (parse_qs(parsed.query).get("token") or [""])[0]
            if not supplied or not secrets.compare_digest(supplied, access_token):
                return False
            query = [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if key != "token"
            ]
            location = urlunsplit(("", "", parsed.path or "/", urlencode(query), ""))
            self.send_response(302)
            self.send_header("Location", location)
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
            body = b"HITL portal access denied."
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
                pass

        def _payload(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                raise ValueError("Request body is too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        @staticmethod
        def _scoped_idea(path: str, suffix: str) -> Optional[str]:
            prefix = "/api/ideas/"
            if not path.startswith(prefix) or not path.endswith(suffix):
                return None
            encoded = path[len(prefix) : len(path) - len(suffix)]
            idea_id = unquote(encoded.strip("/"))
            return idea_id or None

        def _alias_idea(self) -> str:
            if not initial_idea_id:
                raise ValueError("Select an idea first.")
            return initial_idea_id

        def _workspace_input(self, idea_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            session = registry.session(idea_id)
            channel = session.channel
            input_kind = str(payload.get("input_kind", "conversation"))
            text = str(payload.get("text", "")).strip()
            if not text and not (
                input_kind == "resolution_reply" and str(payload.get("option_id", "")).strip()
            ):
                raise ValueError("Enter a message before sending it.")
            return channel.submit_input(
                text,
                input_kind=input_kind,
                request_key=payload.get("request_key"),
                option_id=payload.get("option_id"),
                provider=resolve_hitl_manager_provider(
                    session.work_dir,
                    str(payload.get("provider", "")),
                ),
                client_turn_id=str(payload.get("client_turn_id", "")),
            )

        def _workspace_queue(self, idea_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            channel = registry.session(idea_id).channel
            action = str(payload.get("action", ""))
            item_id = str(payload.get("id", ""))
            if action == "update":
                return channel.update_queued_input(item_id, str(payload.get("text", "")))
            if action == "remove":
                channel.remove_queued_input(item_id)
                return {"status": "accepted", "id": item_id}
            raise ValueError("Unknown queued-message action.")

        def _stream(self, idea_id: str) -> None:
            channel = registry.session(idea_id).channel
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
            try:
                if path == "/api/ideas":
                    self._json(registry.catalog())
                    return
                if path == "/api/idea-schema":
                    self._json(registry.schema())
                    return
                idea_id = self._scoped_idea(path, "/definition")
                if idea_id is not None:
                    self._json(registry.definition(idea_id))
                    return
                idea_id = self._scoped_idea(path, "/snapshot")
                if idea_id is not None:
                    self._json(registry.snapshot(idea_id))
                    return
                idea_id = self._scoped_idea(path, "/stream")
                if idea_id is not None:
                    self._stream(idea_id)
                    return
                if path == "/api/snapshot":
                    self._json(registry.snapshot(self._alias_idea()))
                    return
                if path == "/stream":
                    self._stream(self._alias_idea())
                    return
            except HitlWorkspaceViewError as exc:
                self._json({"error": str(exc)}, 409)
                return
            except (ValueError, RuntimeError, OSError) as exc:
                self._json({"error": str(exc)}, 404 if "not found" in str(exc).lower() else 409)
                return
            self.send_error(404)

        def _mutate(self, method: str) -> None:
            if not self._has_access() or not self._same_origin_post():
                self._deny_access()
                return
            path = urlsplit(self.path).path
            try:
                payload = self._payload()
                if method == "POST" and path == "/api/ideas":
                    idea_id = registry.submit(payload.get("idea", payload))
                    self._json({"status": "accepted", "idea_id": idea_id}, 201)
                    return
                if method == "PUT" and path == "/api/ideas/order":
                    order = payload.get("order")
                    if not isinstance(order, list):
                        raise ValueError("Idea order must be a list.")
                    registry.reorder([str(value) for value in order])
                    self._json({"status": "accepted"})
                    return
                idea_id = self._scoped_idea(path, "/presentation")
                if method == "PATCH" and idea_id is not None:
                    registry.rename(idea_id, str(payload.get("display_name", "")))
                    self._json({"status": "accepted"})
                    return
                idea_id = self._scoped_idea(path, "/input")
                if method == "POST" and idea_id is not None:
                    self._json(self._workspace_input(idea_id, payload), 202)
                    return
                idea_id = self._scoped_idea(path, "/queue")
                if method == "POST" and idea_id is not None:
                    self._json(self._workspace_queue(idea_id, payload), 202)
                    return
                idea_id = self._scoped_idea(path, "/run")
                if method == "POST" and idea_id is not None:
                    self._json(registry.session(idea_id).controller.launch(payload), 202)
                    return
                if method == "POST" and path == "/input":
                    self._json(self._workspace_input(self._alias_idea(), payload), 202)
                    return
                if method == "POST" and path == "/api/queue":
                    self._json(self._workspace_queue(self._alias_idea(), payload), 202)
                    return
                if method == "POST" and path == "/api/run":
                    result = registry.session(self._alias_idea()).controller.launch(payload)
                    self._json(result, 202)
                    return
                self.send_error(404)
            except HitlWebInputError as exc:
                status = 409 if exc.status in {"stale", "already_resolved"} else 400
                self._json({"status": exc.status, "error": str(exc)}, status)
            except HitlWorkspaceRunActiveError as exc:
                self._json({"status": "conflict", "error": str(exc)}, 409)
            except (ValueError, RuntimeError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._json({"status": "invalid", "error": str(exc)}, 400)

        def do_POST(self) -> None:
            self._mutate("POST")

        def do_PATCH(self) -> None:
            self._mutate("PATCH")

        def do_PUT(self) -> None:
            self._mutate("PUT")

    return Handler


class HitlWebPortalServer:
    """One local authenticated server for the complete idea catalog."""

    def __init__(
        self,
        *,
        registry: HitlWebWorkspaceRegistry,
        initial_idea_id: str = "",
        title: str = "NeuriCo",
        port: int = 7890,
        host: str = "localhost",
        access_token: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.initial_idea_id = str(initial_idea_id).strip()
        self.title = title
        self.host = host
        self.port = port
        self.access_token = secrets.token_urlsafe(32) if access_token is None else access_token.strip()
        if not self.access_token:
            raise ValueError("HITL web access token must be non-empty.")
        self.session_cookie_name = _session_cookie_name(self.access_token)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        query = f"?idea={quote(self.initial_idea_id)}" if self.initial_idea_id else ""
        return _access_url(f"http://{self.host}:{self.port}/{query}", self.access_token)

    def access_url(self, base_url: str) -> str:
        parsed = urlsplit(base_url)
        query = list(parse_qsl(parsed.query, keep_blank_values=True))
        if self.initial_idea_id and not any(key == "idea" for key, _value in query):
            query.append(("idea", self.initial_idea_id))
        return _access_url(
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)),
            self.access_token,
        )

    def start(self) -> None:
        handler = _handler(
            self.registry,
            self.title,
            self.initial_idea_id,
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
