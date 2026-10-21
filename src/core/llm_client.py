"""Direct (non-agent) model calls: one key order, one fallback policy, one ledger.

Why this exists (docs/AGENT_FACTORY_ASSESSMENT.md 2.4, 4.2, step 5): five call
sites each built their own OpenAI-compatible client with their own key
preference, default-model literal, timeout and privacy flags, and none of them
recorded usage or cost. ``LLMClient`` replaces them with one object built from
the ``kind: api`` roles in ``config/agents.yaml``::

    client = LLMClient.for_role("eval_verifier", timeout_s=180)   # timeout_s: opt-in deadline, default none
    response = client.chat(messages, response_schema=VERDICT_SCHEMA)
    response.text, response.parsed, response.usage, response.cost_usd, response.route

Design choices, each deliberate:

* **Routes come from the YAML, keys from the environment.** A role lists
  ``routes`` in fallback order (``openrouter`` then ``openai`` for the judge
  family). A route is usable when its key variable is set; ``for_role`` keeps
  the usable ones and remembers *why* the others were skipped, naming the
  variable but never its value.
* **Raw HTTP, one request per call.** The verifier already disabled SDK
  retries because a second request silently doubles the cost and the wait; the
  anthropic SDK is not even installed. Speaking ``/chat/completions`` and
  ``/v1/messages`` through ``httpx`` keeps "one call, one request" true by
  construction and lets tests inject an ``httpx.MockTransport``.
* **Outer wall-clock deadline, opt-in.** With ``params.timeout_s`` set (per role
  in config/agents.yaml, or ``timeout_s=`` on the call) ``achat`` runs the whole
  route loop under ``asyncio.wait_for`` and the per-request HTTP timeout is
  whatever remains, so a slow provider cannot push the call past it. Unset, null
  or 0 (the default) means no deadline at all: the HTTP client waits for the
  reply however long it takes, because a deadline here is not retried and would
  fail the caller's work, and a slow judge or verifier is better late than
  failed. A dead connection is still reported by the OS (connection reset).
* **Fallback lifted from paper-finder's ``ProviderFallback``.** A rejected key
  (401), no credits (402), a key limit (403) or an ``insufficient_quota`` 429
  cannot be fixed by retrying that provider, so the route is marked down for a
  cooldown and the next route is tried; a plain 429 falls through to the next
  route without a cooldown because rate limits clear in seconds. Anything else
  (5xx, network, timeout) is raised as it is: the caller's failure kinds decide
  what that means.
* **Privacy flags live on the route.** OpenRouter routes carry
  ``privacy: {zdr, data_collection}`` which becomes the request's ``provider``
  object; direct OpenAI carries ``{store: false}``. The verifier's "fail rather
  than route sealed source to a retaining upstream" rule is therefore config,
  not code, and applies to every role that extends ``judge``.
* **One ledger line per call** through ``core.run_ledger`` with the OTel field
  names; cost is OpenRouter's reported cost when available, else
  ``config/prices.yaml``, else ``None`` (never a guess).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import httpx

from core import azure_config
from core.agent_auth import agent_model as _azure_agent_model
from core.agent_factory import (
    DEFAULT_CONFIG_PATH, AgentConfigError, Usage, load_agents_config, new_run_id, price_usage,
    resolve_role_config, validate_against_schema,
)
from core.run_ledger import RunLedger, build_entry

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

# How long a route is skipped after it failed with a key-level error (paper-finder's value).
PROVIDER_COOLDOWN_SECONDS = 600.0

_KEY_ERROR_REASONS = {
    401: "invalid API key",
    402: "insufficient credits",
    403: "key limit exceeded or permission denied",
}

WIRE_CHAT_COMPLETIONS = "chat_completions"
WIRE_ANTHROPIC_MESSAGES = "anthropic_messages"

# route name -> (base URL or resolver, ordered key variables, wire protocol, needs NEURICO_AZURE)
_ROUTE_TABLE: Dict[str, Dict[str, Any]] = {
    "openrouter": {"base_url": OPENROUTER_BASE_URL, "keys": ("OPENROUTER_KEY", "OPENROUTER_API_KEY"),
                   "wire": WIRE_CHAT_COMPLETIONS, "azure": False},
    "openai": {"base_url": OPENAI_BASE_URL, "keys": ("OPENAI_API_KEY",),
               "wire": WIRE_CHAT_COMPLETIONS, "azure": False},
    "anthropic": {"base_url": ANTHROPIC_BASE_URL, "keys": ("ANTHROPIC_API_KEY",),
                  "wire": WIRE_ANTHROPIC_MESSAGES, "azure": False},
    "azure_openai": {"base_url": azure_config.azure_openai_base_url, "keys": ("AZURE_OPENAI_API_KEY",),
                     "wire": WIRE_CHAT_COMPLETIONS, "azure": True},
    "azure_foundry": {"base_url": azure_config.foundry_anthropic_base_url,
                      "keys": ("ANTHROPIC_FOUNDRY_API_KEY", "AZURE_OPENAI_API_KEY"),
                      "wire": WIRE_ANTHROPIC_MESSAGES, "azure": True},
}
ROUTE_NAMES = tuple(_ROUTE_TABLE)

# route name -> (monotonic time until which it is skipped, why it was marked down); process-wide
# on purpose: every client in the process shares the same keys, so one rejection is everyone's.
_routes_down: Dict[str, Tuple[float, str]] = {}


class LLMProvidersUnavailableError(RuntimeError):
    """No configured route could answer: a credentials, budget or quota problem, not a bug."""


class LLMResponseInvalidError(ValueError):
    """The provider answered 2xx, but the body carried no usable message."""


class LLMHTTPError(RuntimeError):
    """A non-2xx reply. ``status_code``/``code`` are what the fallback policy reads; the body
    is kept only as ``detail`` (first clause, key material stripped) so callers can log it."""

    def __init__(self, route: "ProviderRoute", status_code: int, body: Any) -> None:
        self.route = route
        self.status_code = status_code
        self.code = _error_code(body)
        self.detail = _error_detail(body)
        super().__init__(f"{route.name} {route.model}: HTTP {status_code}{': ' + self.detail if self.detail else ''}")


@dataclass(frozen=True)
class ProviderRoute:
    name: str
    base_url: Optional[str]
    api_key_env: str                                      # the variable name; never the value
    model: str
    wire: str = WIRE_CHAT_COMPLETIONS
    privacy: Mapping[str, Any] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.name} ({self.model}, key {self.api_key_env})"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    parsed: Any = None                                    # JSON (schema-validated when a schema was given)
    parsing_error: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    route: Optional[ProviderRoute] = None
    raw: Any = None
    attempts: int = 1                                     # routes tried, including the one that answered

    @property
    def cost_usd(self) -> Optional[float]:
        return self.usage.cost_usd

    @property
    def model(self) -> Optional[str]:
        return self.usage.model or (self.route.model if self.route else None)


# -- error classification (paper-finder's rules) -----------------------------------------------------------

def _error_code(body: Any) -> Optional[str]:
    """OpenAI's ``error.code`` (``insufficient_quota`` is the one the fallback policy reads)."""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return str(code) if isinstance(code, (str, int)) else None


def _error_detail(body: Any) -> str:
    """First clause of the provider's message, without URLs or anything that looks like a key."""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else (body if isinstance(body, str) else None)
    if not isinstance(message, str):
        return ""
    return re.split(r"[.:]\s|[.:]$|https?://|sk-", message)[0].strip()[:80]


def is_key_error(error: BaseException) -> bool:
    """Errors about the key itself; retrying the same provider cannot fix them."""
    status = getattr(error, "status_code", None)
    return status in _KEY_ERROR_REASONS or (status == 429 and getattr(error, "code", None) == "insufficient_quota")


def should_fall_back(error: BaseException) -> bool:
    return is_key_error(error) or getattr(error, "status_code", None) == 429


def describe_provider_error(error: BaseException) -> str:
    status = getattr(error, "status_code", None)
    reason = _KEY_ERROR_REASONS.get(status, "rate limit or quota exhausted")
    detail = getattr(error, "detail", "") or ""
    return f"{reason} ({status} {type(error).__name__}{': ' + detail if detail else ''})"


def reset_cooldowns() -> None:
    """Forget every marked-down route (tests, and an operator who just fixed a key)."""
    _routes_down.clear()


def route_down_reason(name: str) -> Optional[str]:
    """Why ``name`` is currently skipped, or None when it is live."""
    until, reason = _routes_down.get(name, (0.0, ""))
    return reason if time.monotonic() < until else None


# -- route resolution -----------------------------------------------------------------------------------------

def _model_for_route(name: str, configured: Optional[str], override: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """The model string a route receives.

    An override (``NEURICO_EVAL_VERIFIER_MODEL``, ``--model``) is one name that has to
    fit every route: OpenRouter wants ``vendor/model`` (the vendor is taken from the
    route's configured default), direct providers want the bare name, and Azure wants
    a deployment (``core.agent_auth.agent_model`` already knows that rule).
    """
    if name == "azure_openai":
        return _azure_agent_model("codex", "azure", override or configured, env)
    if not override:
        return configured
    if name == "openrouter":
        if "/" in override:
            return override
        vendor = configured.split("/", 1)[0] if configured and "/" in configured else "openai"
        return f"{vendor}/{override}"
    return override.split("/", 1)[1] if "/" in override else override


def _route_from_config(entry: Mapping[str, Any], env: Mapping[str, str], override_model: Optional[str]
                       ) -> Tuple[Optional[ProviderRoute], Optional[str]]:
    """``(route, None)`` when usable, ``(None, reason)`` when it must be skipped."""
    name = str(entry.get("name") or "")
    table = _ROUTE_TABLE.get(name)
    if table is None:
        raise AgentConfigError(f"unknown LLM route {name!r}; expected one of {ROUTE_NAMES}")
    if table["azure"] and not azure_config.azure_active(env):
        return None, f"{name}: NEURICO_AZURE is off"
    key_env = next((var for var in table["keys"] if (env.get(var) or "").strip()), None)
    if key_env is None:
        return None, f"{name}: set {' or '.join(table['keys'])}"
    base_url = table["base_url"]
    if callable(base_url):
        base_url = base_url(env)
        if not base_url:
            return None, f"{name}: no base URL (set AZURE_FOUNDRY_RESOURCE / *_BASE_URL)"
    model = _model_for_route(name, entry.get("model"), override_model, env)
    if not model:
        return None, f"{name}: no model configured"
    return ProviderRoute(name=name, base_url=str(entry.get("base_url") or base_url).rstrip("/"), api_key_env=key_env,
                         model=model, wire=table["wire"], privacy=dict(entry.get("privacy") or {}),
                         headers=dict(entry.get("headers") or {})), None


def resolve_routes(cfg: Mapping[str, Any], env: Mapping[str, str], *, model: Optional[str] = None,
                   route_names: Optional[Iterable[str]] = None) -> Tuple[List[ProviderRoute], List[str]]:
    """Usable routes in configured order plus the reasons the others were skipped."""
    model = model or (env.get(str(cfg.get("model_env") or "")) or "").strip() or cfg.get("model") or None
    wanted = set(route_names) if route_names is not None else None
    routes, skipped = [], []
    for entry in cfg.get("routes") or []:
        if wanted is not None and entry.get("name") not in wanted:
            continue
        route, reason = _route_from_config(entry, env, model)
        if route is not None:
            routes.append(route)
        else:
            skipped.append(reason or "")
    return routes, skipped


# -- request / response translation -------------------------------------------------------------------------------

def _split_system(messages: Sequence[Mapping[str, Any]]) -> Tuple[str, List[Mapping[str, Any]]]:
    system = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    return system, [m for m in messages if m.get("role") != "system"]


def _chat_messages(messages: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI-style messages; the manager's ``tool_result`` role becomes the wire's ``tool`` role."""
    out = []
    for m in messages:
        if m.get("role") == "tool_result":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m.get("content", "")})
        else:
            out.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "name", "tool_call_id")})
    return out


def _anthropic_messages(messages: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in messages:
        if m.get("role") == "tool_result":
            out.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                                                     "content": m.get("content", "")}]})
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


def _chat_tools(tools: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("parameters", {"type": "object", "properties": {}})}}
            for t in tools]


def _anthropic_tools(tools: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"name": t["name"], "description": t.get("description", ""),
             "input_schema": t.get("parameters", {"type": "object", "properties": {}})} for t in tools]


def build_request(route: ProviderRoute, messages: Sequence[Mapping[str, Any]], *, max_tokens: int,
                  temperature: Optional[float], json_mode: bool, tools: Optional[Sequence[Mapping[str, Any]]]
                  ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    """``(url, headers, body)`` for one request on ``route``; the key is read here and nowhere else."""
    api_key = os.environ.get(route.api_key_env, "")
    headers = {"Content-Type": "application/json", **route.headers}
    if route.wire == WIRE_ANTHROPIC_MESSAGES:
        system, rest = _split_system(messages)
        body: Dict[str, Any] = {"model": route.model, "max_tokens": max_tokens, "messages": _anthropic_messages(rest)}
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = _anthropic_tools(tools)
        headers.update({"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION})
        if route.name == "azure_foundry":
            headers["api-key"] = api_key
        return f"{route.base_url}/v1/messages", headers, body
    body = {"model": route.model, "messages": _chat_messages(messages), "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = _chat_tools(tools)
    if route.name == "openrouter":
        if route.privacy:
            body["provider"] = dict(route.privacy)     # enforced per request by OpenRouter (zdr / data_collection)
        body["usage"] = {"include": True}              # OpenRouter reports the priced cost with the usage block
    elif route.privacy:
        body.update(route.privacy)                     # direct OpenAI: store=false
    if route.name == "azure_openai":
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return f"{route.base_url}/chat/completions", headers, body


def _parse_tool_arguments(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}
    return value if isinstance(value, dict) else {"raw": raw}


def _usage_from_chat(data: Mapping[str, Any]) -> Usage:
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    cost = usage.get("cost")
    return Usage(input_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0),
                 cache_read_tokens=int(details.get("cached_tokens") or 0),
                 cost_usd=float(cost) if cost is not None else None, model=data.get("model"), session_id=data.get("id"))


def _usage_from_anthropic(data: Mapping[str, Any]) -> Usage:
    usage = data.get("usage") or {}
    return Usage(input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0),
                 cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                 cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                 model=data.get("model"), session_id=data.get("id"))


def parse_response(route: ProviderRoute, data: Any) -> LLMResponse:
    """Text, tool calls and usage from a 2xx body; an empty or shapeless body is ``LLMResponseInvalidError``."""
    if not isinstance(data, dict):
        raise LLMResponseInvalidError("LLM response body is not a JSON object")
    if route.wire == WIRE_ANTHROPIC_MESSAGES:
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMResponseInvalidError("LLM response did not contain message content")
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [ToolCall(id=b.get("id", ""), name=b.get("name", ""), arguments=_parse_tool_arguments(b.get("input")))
                 for b in blocks if b.get("type") == "tool_use"]
        usage = _usage_from_anthropic(data)
    else:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseInvalidError("LLM response did not contain message content") from exc
        text = message.get("content") or ""
        if not isinstance(text, str):
            raise LLMResponseInvalidError("LLM response content is not text")
        calls = [ToolCall(id=tc.get("id", ""), name=(tc.get("function") or {}).get("name", ""),
                          arguments=_parse_tool_arguments((tc.get("function") or {}).get("arguments")))
                 for tc in message.get("tool_calls") or []]
        usage = _usage_from_chat(data)
    if not text.strip() and not calls:
        raise LLMResponseInvalidError("LLM returned an empty response")
    if usage.cost_usd is None:
        usage.cost_usd = price_usage(usage, usage.model or route.model)
    return LLMResponse(text=text, tool_calls=calls, usage=usage, route=route, raw=data)


def parse_structured(response: LLMResponse, schema: Optional[Mapping[str, Any]], expect_json: bool) -> LLMResponse:
    """Fill ``parsed`` / ``parsing_error``: one JSON object, validated locally when a schema is given.

    The wire asks for ``json_object`` rather than ``json_schema`` because that is the one
    shape OpenRouter and OpenAI accept for every model; strictness comes from
    ``jsonschema`` here, which also makes the failure visible instead of a 400.
    """
    if not (schema or expect_json):
        return response
    try:
        data = json.loads(response.text.strip())
    except json.JSONDecodeError as exc:
        response.parsing_error = f"invalid JSON: {exc.msg}"
        return response
    if schema:
        issues = validate_against_schema(data, dict(schema))
        if issues:
            response.parsing_error = "; ".join(issues)
            return response
    response.parsed = data
    return response


# -- the client -----------------------------------------------------------------------------------------------

_PARAM_KEYS = ("max_tokens", "temperature", "timeout_s", "response_format")


class LLMClient:
    """A role's routes plus its default parameters; ``chat``/``achat`` make one call."""

    def __init__(self, role: str, routes: Sequence[ProviderRoute], params: Optional[Mapping[str, Any]] = None, *,
                 skipped: Sequence[str] = (), ledger: Optional[RunLedger] = None, work_dir: Optional[Path] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None, tags: Optional[Mapping[str, Any]] = None) -> None:
        self.role = role
        self.routes = list(routes)
        self.params = {k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS}
        self.skipped = list(skipped)
        self.ledger = ledger
        self.work_dir = Path(work_dir) if work_dir else None
        self.transport = transport
        self.tags = dict(tags or {})

    @classmethod
    def for_role(cls, role: str, *, config_path: Path = DEFAULT_CONFIG_PATH, env: Optional[Mapping[str, str]] = None,
                 model: Optional[str] = None, route_names: Optional[Iterable[str]] = None,
                 ledger: Optional[RunLedger] = None, work_dir: Optional[Path] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None, tags: Optional[Mapping[str, Any]] = None,
                 **params: Any) -> "LLMClient":
        """Build from ``roles.<role>`` in ``config/agents.yaml``.

        Precedence for the model: ``model=`` > the role's ``model_env`` variable
        (``NEURICO_EVAL_VERIFIER_MODEL`` ...) > the route's own entry. ``params``
        (``timeout_s``, ``max_tokens``, ``temperature``, ``response_format``)
        override the role's ``params`` block; ``None`` values are ignored so a
        caller can pass a flag that was not given. Construction never raises for a
        missing key: ``routes`` is simply empty and ``chat`` raises
        ``LLMProvidersUnavailableError``, which lets the idea converters choose
        their template fallback up front.
        """
        env = os.environ if env is None else env
        config = load_agents_config(config_path)
        cfg = resolve_role_config(config, role)
        if str(cfg.get("kind", "cli")) != "api":
            raise AgentConfigError(f"role {role!r} is not an API role (kind: api) in {config_path}")
        routes, skipped = resolve_routes(cfg, env, model=model, route_names=route_names)
        merged = {k: v for k, v in dict(cfg.get("params") or {}).items()}
        merged.update({k: v for k, v in params.items() if v is not None})
        if ledger is None:
            ledger = RunLedger.from_config(config.get("ledger"), env)
        return cls(role, routes, merged, skipped=skipped, ledger=ledger, work_dir=work_dir, transport=transport, tags=tags)

    # -- introspection ---------------------------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.routes)

    @property
    def timeout_s(self) -> Optional[float]:
        """The configured outer deadline in seconds; None = no deadline (the default)."""
        value = self.params.get("timeout_s")
        return float(value) if value else None

    def describe(self) -> str:
        """One line for logs: route names, models and key *names*; skipped routes with their reason."""
        live = ", ".join(r.describe() for r in self.routes) or "none"
        skipped = f"; skipped: {'; '.join(self.skipped)}" if self.skipped else ""
        return f"LLM role {self.role}: routes {live}{skipped}"

    def unavailable_message(self) -> str:
        return (f"role {self.role!r} has no usable LLM route: {'; '.join(self.skipped) or 'no routes configured'}")

    # -- calls ----------------------------------------------------------------------------------------------
    def chat(self, messages: Sequence[Mapping[str, Any]], *, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None, response_schema: Optional[Mapping[str, Any]] = None,
             tools: Optional[Sequence[Mapping[str, Any]]] = None, timeout_s: Optional[float] = None) -> LLMResponse:
        """Blocking ``achat``; the deadline is the same outer wall clock."""
        return asyncio.run(self.achat(messages, max_tokens=max_tokens, temperature=temperature,
                                      response_schema=response_schema, tools=tools, timeout_s=timeout_s))

    async def achat(self, messages: Sequence[Mapping[str, Any]], *, max_tokens: Optional[int] = None,
                    temperature: Optional[float] = None, response_schema: Optional[Mapping[str, Any]] = None,
                    tools: Optional[Sequence[Mapping[str, Any]]] = None, timeout_s: Optional[float] = None) -> LLMResponse:
        """One call: try routes in order (under one deadline when configured), record one ledger line."""
        timeout = float(timeout_s) if timeout_s else (self.timeout_s if timeout_s is None else None)
        started, ts_start = time.monotonic(), _utc_now()
        outcome: Dict[str, Any] = {"route": None, "attempts": 0, "fallbacks": []}
        try:
            # timeout None: no outer deadline (the default); wait_for(..., None) never cancels.
            response = await asyncio.wait_for(
                self._try_routes(messages, outcome, deadline=None if timeout is None else started + timeout,
                                 max_tokens=max_tokens, temperature=temperature, response_schema=response_schema,
                                 tools=tools), timeout)
        except BaseException as exc:
            self._record(outcome, None, ts_start, time.monotonic() - started, error=exc)
            raise
        self._record(outcome, response, ts_start, time.monotonic() - started)
        return response

    async def _try_routes(self, messages, outcome: Dict[str, Any], *, deadline: Optional[float], max_tokens, temperature,
                          response_schema, tools) -> LLMResponse:
        """paper-finder's ``ProviderFallback.ainvoke``, over ``ProviderRoute`` and HTTP status codes."""
        if not self.routes:
            raise LLMProvidersUnavailableError(self.unavailable_message())
        failures: List[str] = []
        for index, route in enumerate(self.routes):
            reason = route_down_reason(route.name)
            if reason:
                failures.append(f"{route.name}: {reason} (not retried, marked down)")
                continue
            outcome["route"], outcome["attempts"] = route, outcome["attempts"] + 1
            try:
                response = await self._request(route, messages, deadline=deadline, max_tokens=max_tokens,
                                               temperature=temperature, response_schema=response_schema, tools=tools)
            except LLMHTTPError as error:
                if not should_fall_back(error):
                    raise
                description = describe_provider_error(error)
                failures.append(f"{route.name}: {description}")
                outcome["fallbacks"].append(f"{route.name}: {description}")
                if is_key_error(error):
                    _routes_down[route.name] = (time.monotonic() + PROVIDER_COOLDOWN_SECONDS, description)
                    print(f"LLM route {route.name} failed ({description}); marked down for "
                          f"{PROVIDER_COOLDOWN_SECONDS:.0f}s" + self._next_route(index))
                else:
                    print(f"LLM route {route.name} failed ({description})" + self._next_route(index))
                continue
            _routes_down.pop(route.name, None)
            response.attempts = outcome["attempts"]
            return response
        raise LLMProvidersUnavailableError(
            "All LLM routes failed; this is a credentials or budget problem, not a bug. " + "; ".join(failures))

    def _next_route(self, index: int) -> str:
        return f", falling back to {self.routes[index + 1].name}" if index + 1 < len(self.routes) else ""

    async def _request(self, route: ProviderRoute, messages, *, deadline: Optional[float], max_tokens, temperature,
                       response_schema, tools) -> LLMResponse:
        """Exactly one HTTP request; the client is closed before control returns so a
        cancelled call (deadline or HITL stop) never leaves a connection behind."""
        max_tokens = int(max_tokens if max_tokens is not None else self.params.get("max_tokens") or 4096)
        if temperature is None:
            temperature = self.params.get("temperature")
        json_mode = bool(response_schema) or self.params.get("response_format") == "json_object"
        url, headers, body = build_request(route, messages, max_tokens=max_tokens, temperature=temperature,
                                           json_mode=json_mode and route.wire == WIRE_CHAT_COMPLETIONS, tools=tools)
        # No deadline (the default) = no HTTP timeout: the request is never cut short on elapsed time.
        remaining = None if deadline is None else max(deadline - time.monotonic(), 0.001)
        async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(remaining)) as http:
            reply = await http.post(url, headers=headers, json=body)
        try:
            data = reply.json()
        except ValueError:
            data = reply.text
        if reply.status_code >= 400:
            raise LLMHTTPError(route, reply.status_code, data)
        response = parse_response(route, data)
        return parse_structured(response, response_schema, expect_json=json_mode)

    # -- ledger --------------------------------------------------------------------------------------------
    def _record(self, outcome: Mapping[str, Any], response: Optional[LLMResponse], ts_start: str, elapsed_s: float,
                error: Optional[BaseException] = None) -> None:
        if self.ledger is None:
            return
        route: Optional[ProviderRoute] = outcome.get("route")
        usage = response.usage.as_dict() if response is not None else None
        tags = dict(self.tags)
        if outcome.get("fallbacks"):
            tags["fallbacks"] = list(outcome["fallbacks"])
        entry = build_entry(
            run_id=new_run_id(self.role), role=self.role, provider=route.name if route else "none",
            auth=route.api_key_env if route else "none", permissions="api", argv=[],
            status="ok" if error is None else "error", elapsed_s=elapsed_s, ts_start=ts_start, ts_end=_utc_now(),
            request_model=route.model if route else None, usage=usage,
            error_type=type(error).__name__ if error is not None else None,
            attempts=max(int(outcome.get("attempts") or 0), 1), tags=tags,
            work_dir=str(self.work_dir) if self.work_dir else None, operation="chat")
        self.ledger.record(entry, self.work_dir)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
