"""Standalone idea-submission lobby served on localhost.

This server is deliberately independent of the workspace-scoped interactive
and HITL pages: submission happens before any workspace exists. It serves a
form that builds an idea spec, previews the generated YAML, and submits it
through the same IdeaManager path as the submit CLI.
"""

from __future__ import annotations

import hashlib
import html
import json
import secrets
import threading
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from core.config_loader import ConfigLoader
from core.idea_manager import IdeaManager, resolve_ideas_dir


PAGE = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{TITLE}}</title>
    <link rel="stylesheet" href="/assets/submit.css">
  </head>
  <body>
    <div id="app"></div>
    <script src="/assets/submit.js" defer></script>
  </body>
</html>'''

ASSET_DIR = Path(__file__).with_name("static") / "submit"
ASSET_TYPES = {
    "submit.css": "text/css; charset=utf-8",
    "submit.js": "application/javascript; charset=utf-8",
}

COMPUTE_OPTIONS = ["any", "cpu_only", "gpu_required", "multi_gpu", "tpu"]

# Idea sections the form manages. On edit these are replaced wholesale by the
# form's values; every other key in the stored idea (metadata, expected_outputs,
# local resources, ...) is preserved untouched.
FORM_KEYS = ("title", "domain", "hypothesis", "background", "methodology", "constraints")

# Only ideas that no run has consumed yet are editable.
EDITABLE_STATUS = "submitted"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_clean(v) for v in values) if item]


def _clean_rows(rows: Any, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """Keep rows that have at least one non-empty field, dropping empty keys."""
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = {f: _clean(row.get(f)) for f in fields}
        entry = {k: v for k, v in entry.items() if v}
        if entry:
            cleaned.append(entry)
    return cleaned


def build_idea_spec(payload: dict[str, Any]) -> dict[str, Any]:
    """Build an idea spec dict from the submission form payload.

    Empty optional fields and sections are omitted so the generated YAML stays
    as minimal as the hand-written examples.
    """
    idea: dict[str, Any] = {
        "title": _clean(payload.get("title")),
        "domain": _clean(payload.get("domain")),
        "hypothesis": _clean(payload.get("hypothesis")),
    }

    background: dict[str, Any] = {}
    description = _clean(payload.get("background_description"))
    if description:
        background["description"] = description
    papers = _clean_rows(payload.get("papers"), ("url", "description"))
    if papers:
        background["papers"] = papers
    datasets = _clean_rows(payload.get("datasets"), ("name", "source"))
    if datasets:
        background["datasets"] = datasets
    if background:
        idea["background"] = background

    methodology: dict[str, Any] = {}
    approach = _clean(payload.get("approach"))
    if approach:
        methodology["approach"] = approach
    for key in ("steps", "baselines", "metrics"):
        values = _clean_list(payload.get(key))
        if values:
            methodology[key] = values
    if methodology:
        idea["methodology"] = methodology

    constraints: dict[str, Any] = {}
    compute = _clean(payload.get("compute"))
    if compute:
        constraints["compute"] = compute
    time_limit = payload.get("time_limit")
    if time_limit not in (None, ""):
        try:
            constraints["time_limit"] = int(time_limit)
        except (TypeError, ValueError):
            constraints["time_limit"] = time_limit  # let validation report it
    if constraints:
        idea["constraints"] = constraints

    return {"idea": idea}


def render_idea_yaml(idea_spec: dict[str, Any]) -> str:
    """Render the spec exactly as IdeaManager.submit_idea would write it."""
    return yaml.dump(
        idea_spec, default_flow_style=False, sort_keys=False, allow_unicode=True
    )


def merge_edit(existing_spec: dict[str, Any], new_spec: dict[str, Any]) -> dict[str, Any]:
    """Overlay the form-managed sections onto an existing stored idea.

    Form sections absent from the new spec (e.g. all papers removed) are
    dropped; unmanaged keys keep their original values and relative order.
    """
    new_idea = new_spec.get("idea", {})
    merged: dict[str, Any] = {k: v for k, v in new_idea.items() if k in FORM_KEYS}
    for key, value in (existing_spec.get("idea") or {}).items():
        if key not in FORM_KEYS:
            merged[key] = value
    return {"idea": merged}


def next_step_commands(idea_id: str) -> list[dict[str, str]]:
    return [
        {
            "label": "Open the HITL workspace page",
            "native": f"uv run python src/cli/hitl_web.py {idea_id}",
            "docker": f"./neurico hitl-web {idea_id}",
        },
        {
            "label": "Run the research pipeline once",
            "native": (
                f"uv run python src/core/runner.py {idea_id}"
                " --provider claude --no-github --full-permissions"
            ),
            "docker": f"./neurico run {idea_id} --provider claude --full-permissions",
        },
    ]


def _session_cookie_name(access_token: str) -> str:
    fingerprint = hashlib.sha256(access_token.encode("utf-8")).hexdigest()[:12]
    return f"neurico_submit_session_{fingerprint}"


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
    project_root: Path,
    title: str,
    access_token: str,
    session_cookie_name: str,
):
    page = PAGE.replace("{{TITLE}}", html.escape(title))

    def context_payload() -> dict[str, Any]:
        config = ConfigLoader().get_domains_config()
        domains = [
            {
                "id": domain_id,
                "name": entry.get("name", domain_id),
                "description": entry.get("description", ""),
            }
            for domain_id, entry in (config.get("domains") or {}).items()
        ]
        manager = IdeaManager(resolve_ideas_dir(project_root))
        return {
            "domains": domains,
            "default_domain": config.get("default_domain", ""),
            "compute_options": COMPUTE_OPTIONS,
            "ideas": manager.list_ideas(),
        }

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
            if parsed.path != "/":
                return False
            supplied = (parse_qs(parsed.query).get("token") or [""])[0]
            if not supplied or not secrets.compare_digest(supplied, access_token):
                return False
            self.send_response(302)
            self.send_header("Location", "/")
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
            body = b"Idea submission access denied."
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

        def do_GET(self) -> None:
            if self._bootstrap_access():
                return
            if not self._has_access():
                self._deny_access()
                return
            path = urlsplit(self.path).path
            if path == "/":
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
            if path == "/api/context":
                try:
                    self._json(context_payload())
                except (OSError, yaml.YAMLError) as exc:
                    self._json({"error": str(exc)}, 500)
                return
            if path.startswith("/api/ideas/"):
                idea_id = path.removeprefix("/api/ideas/")
                manager = IdeaManager(resolve_ideas_dir(project_root))
                spec = manager.get_idea(idea_id)
                if spec is None:
                    self._json({"error": f"Idea not found: {idea_id}"}, 404)
                    return
                status = spec.get("idea", {}).get("metadata", {}).get("status", "unknown")
                self._json(
                    {
                        "idea_id": idea_id,
                        "status": status,
                        "editable": status == EDITABLE_STATUS,
                        "path": str(manager.get_idea_path(idea_id)),
                        "yaml": render_idea_yaml(spec),
                        "spec": spec,
                    }
                )
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if not self._has_access() or not self._same_origin_post():
                self._deny_access()
                return
            path = urlsplit(self.path).path
            is_update = path.startswith("/api/ideas/")
            if path not in {"/api/preview", "/api/submit"} and not is_update:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1_000_000:
                    raise ValueError("Request too large.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._json({"error": str(exc) or "Invalid request."}, 400)
                return

            manager = IdeaManager(resolve_ideas_dir(project_root))
            spec = build_idea_spec(payload)

            # Editing (and previewing an edit) merges the form sections onto
            # the stored idea so unmanaged fields are never silently dropped.
            edit_id = (
                path.removeprefix("/api/ideas/")
                if is_update
                else _clean(payload.get("idea_id"))
            )
            existing = None
            if edit_id:
                existing = manager.get_idea(edit_id)
                if existing is None:
                    self._json({"errors": [f"Idea not found: {edit_id}"]}, 404)
                    return
                spec = merge_edit(existing, spec)

            validation = manager.validate_idea(spec)

            if path == "/api/preview":
                self._json(
                    {
                        "yaml": render_idea_yaml(spec),
                        "valid": validation["valid"],
                        "errors": validation["errors"],
                        "warnings": validation["warnings"],
                    }
                )
                return

            if not validation["valid"]:
                self._json(
                    {"errors": validation["errors"], "warnings": validation["warnings"]},
                    400,
                )
                return

            if is_update:
                status = existing.get("idea", {}).get("metadata", {}).get("status", "unknown")
                if status != EDITABLE_STATUS:
                    self._json(
                        {"errors": [f"Only '{EDITABLE_STATUS}' ideas can be edited; "
                                    f"this idea is '{status}'."]},
                        409,
                    )
                    return
                spec["idea"].setdefault("metadata", {})["updated_at"] = (
                    datetime.now().isoformat()
                )
                try:
                    idea_path = manager.get_idea_path(edit_id)
                    with open(idea_path, "w", encoding="utf-8") as handle:
                        yaml.dump(
                            spec, handle, default_flow_style=False, sort_keys=False
                        )
                except (OSError, FileNotFoundError) as exc:
                    self._json({"errors": [str(exc)]}, 500)
                    return
                self._json(
                    {
                        "idea_id": edit_id,
                        "updated": True,
                        "path": str(idea_path),
                        "warnings": validation["warnings"],
                        "next_steps": next_step_commands(edit_id),
                    }
                )
                return

            try:
                idea_id = manager.submit_idea(spec, validate=False)
            except (OSError, ValueError) as exc:
                self._json({"errors": [str(exc)]}, 500)
                return
            self._json(
                {
                    "idea_id": idea_id,
                    "path": str(manager.get_idea_path(idea_id)),
                    "warnings": validation["warnings"],
                    "next_steps": next_step_commands(idea_id),
                },
                201,
            )

    return Handler


class SubmitWebServer:
    """Localhost server for the idea-submission lobby page."""

    def __init__(
        self,
        *,
        project_root: Path,
        title: str = "NeuriCo · Submit an idea",
        port: int = 7891,
        host: str = "localhost",
        access_token: Optional[str] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.title = title
        self.host = host
        self.port = port
        self.access_token = (
            secrets.token_urlsafe(32)
            if access_token is None
            else str(access_token).strip()
        )
        if not self.access_token:
            raise ValueError("Submission web access token must be non-empty.")
        self.session_cookie_name = _session_cookie_name(self.access_token)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return _access_url(f"http://{self.host}:{self.port}", self.access_token)

    def start(self) -> None:
        handler = _handler(
            self.project_root, self.title, self.access_token, self.session_cookie_name
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
            raise RuntimeError(
                f"Could not bind a submission web port near {self.port}: {last_error}"
            )
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
