"""Minimal stdio MCP adapter for the runtime-owned HITL manager tool surface.

The adapter deliberately owns no HITL state and executes no manager action. It
only translates MCP ``tools/list`` and ``tools/call`` requests into authenticated
loopback requests handled by the long-running :class:`HitlManager` process.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict


_PROTOCOL_VERSION = "2024-11-05"


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _runtime_request(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    base_url = os.environ.get("NEURICO_HITL_MANAGER_URL", "").strip().rstrip("/")
    token = os.environ.get("NEURICO_HITL_MANAGER_TOKEN", "").strip()
    if not base_url or not token:
        raise RuntimeError("HITL manager runtime bridge is unavailable.")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            message = body
        raise RuntimeError(str(message)) from exc
    except OSError as exc:
        raise RuntimeError(f"HITL manager runtime request failed: {exc}") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("HITL manager runtime returned invalid JSON.") from exc
    if not isinstance(decoded, dict) or not decoded.get("ok"):
        raise RuntimeError(str(decoded.get("error", "HITL manager runtime rejected request.")))
    return decoded


def _handle(request: Dict[str, Any]) -> Dict[str, Any] | None:
    request_id = request.get("id")
    method = str(request.get("method", ""))
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _error(request_id, -32602, "MCP request params must be an object.")

    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "neurico-hitl-manager", "version": "1.0"},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    try:
        if method == "tools/list":
            return _result(request_id, {"tools": _runtime_request("/mcp/tools", {}).get("tools", [])})
        if method == "tools/call":
            name = str(params.get("name", "")).strip()
            arguments = params.get("arguments") or {}
            if not name or not isinstance(arguments, dict):
                return _error(request_id, -32602, "tools/call requires a tool name and object arguments.")
            response = _runtime_request("/mcp/call", {"name": name, "arguments": arguments})
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": str(response.get("content", ""))}],
                    "isError": bool(response.get("is_error", False)),
                },
            )
    except RuntimeError as exc:
        return _result(
            request_id,
            {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
        )
    return _error(request_id, -32601, f"Unsupported MCP method: {method}")


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("MCP request must be an object.")
            response = _handle(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = _error(None, -32700, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
