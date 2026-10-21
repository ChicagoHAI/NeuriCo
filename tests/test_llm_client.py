"""core.llm_client against a fake HTTP transport (no network).

Step 5 of docs/AGENT_FACTORY_ASSESSMENT.md: route order and key resolution from
config/agents.yaml, fallback on 401/402/429 with the paper-finder cooldown, the
outer wall-clock deadline, schema parsing, OpenRouter privacy flags and the
ledger line every call writes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import core.llm_client as lc  # noqa: E402
from core.agent_factory import AgentConfigError  # noqa: E402
from core.llm_client import LLMClient, LLMHTTPError, LLMProvidersUnavailableError, LLMResponseInvalidError  # noqa: E402
from core.run_ledger import RunLedger  # noqa: E402

KEY_VARS = ("OPENROUTER_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "NEURICO_AZURE", "AZURE_OPENAI_API_KEY", "AZURE_FOUNDRY_RESOURCE", "AZURE_OPENAI_DEPLOYMENTS",
            "NEURICO_EVAL_VERIFIER_MODEL", "NEURICO_AGENT_MODEL")
MESSAGES = [{"role": "system", "content": "Judge."}, {"role": "user", "content": "evidence"}]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NEURICO_AGENT_LEDGER", str(tmp_path / "global-ledger.jsonl"))
    lc.reset_cooldowns()
    yield
    lc.reset_cooldowns()


def chat_body(text: str = '{"pass": true}', *, cost=0.0123, tool_calls=None) -> dict:
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "gen-1", "model": "openai/gpt-4.1", "choices": [{"message": message}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cost": cost,
                      "prompt_tokens_details": {"cached_tokens": 100}}}


class FakeAPI:
    """Scripted HTTP endpoint: ``status_by_host`` decides the reply, ``requests`` records every call."""

    def __init__(self, status_by_host=None, body=None):
        self.status_by_host = dict(status_by_host or {})
        self.body = body if body is not None else chat_body()
        self.requests: list = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.status_by_host.get(request.url.host, 200)
        if isinstance(status, tuple):
            status, body = status
        else:
            body = self.body if status == 200 else {"error": {"message": f"http {status}: key sk-SECRET", "code": None}}
        return httpx.Response(status, json=body)

    def hosts(self):
        return [r.url.host for r in self.requests]


def client(role="eval_verifier", api=None, **kw) -> LLMClient:
    api = api or FakeAPI()
    return LLMClient.for_role(role, transport=api.transport(), ledger=RunLedger(enabled=False), **kw)


# -- routes ---------------------------------------------------------------------------------------------------

def test_routes_follow_config_order_and_key_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    c = client()
    assert [(r.name, r.model, r.api_key_env) for r in c.routes] == [
        ("openrouter", "openai/gpt-4.1", "OPENROUTER_KEY"), ("openai", "gpt-4.1", "OPENAI_API_KEY")]
    assert c.params == {"temperature": 0, "max_tokens": 4096, "timeout_s": 180, "response_format": "json_object"}
    assert "or-key" not in c.describe() and "OPENROUTER_KEY" in c.describe()


def test_openrouter_alias_and_missing_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "alias")
    c = client()
    assert [r.api_key_env for r in c.routes] == ["OPENROUTER_API_KEY"]
    assert c.skipped == ["openai: set OPENAI_API_KEY"]

    monkeypatch.delenv("OPENROUTER_API_KEY")
    c = client()
    assert not c.available and not c.routes
    with pytest.raises(LLMProvidersUnavailableError, match="OPENROUTER_KEY or OPENROUTER_API_KEY"):
        c.chat(MESSAGES)


def test_model_override_precedence_per_route(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("NEURICO_EVAL_VERIFIER_MODEL", "gpt-4.1-mini")
    assert [r.model for r in client().routes] == ["openai/gpt-4.1-mini", "gpt-4.1-mini"]
    assert [r.model for r in client(model="openai/gpt-5.4").routes] == ["openai/gpt-5.4", "gpt-5.4"]
    assert [r.model for r in client("idea_converter").routes] == ["openai/gpt-4.1", "gpt-4.1"]


def test_role_params_override_and_non_api_roles_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    c = client("idea_converter", timeout_s=None, max_tokens=99)
    assert c.params["timeout_s"] == 60 and c.params["max_tokens"] == 99 and c.params["temperature"] == 0.1
    assert c.params["response_format"] is None
    with pytest.raises(AgentConfigError, match="not an API role"):
        client("resource_finder")
    with pytest.raises(AgentConfigError, match="unknown LLM route"):
        lc.resolve_routes({"routes": [{"name": "bedrock", "model": "x"}]}, {})


def test_route_names_restrict_to_the_backend_lane(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENROUTER_KEY", "o")
    both = client("interactive_manager_api")
    assert [r.name for r in both.routes] == ["anthropic", "openrouter"]
    only = client("interactive_manager_api", route_names=("openrouter",))
    assert [(r.name, r.model) for r in only.routes] == [("openrouter", "anthropic/claude-sonnet-4")]


# -- request shape ------------------------------------------------------------------------------------------------

def test_openrouter_request_carries_privacy_flags_and_no_tools(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "or-secret")
    api = FakeAPI()
    response = client(api=api).chat(MESSAGES)
    request = api.requests[0]
    body = json.loads(request.content)
    assert request.url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer or-secret"
    assert body["provider"] == {"zdr": True, "data_collection": "deny"}
    assert body["usage"] == {"include": True}
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0 and body["max_tokens"] == 4096 and body["model"] == "openai/gpt-4.1"
    assert "store" not in body and "tools" not in body and "tool_choice" not in body
    assert response.text == '{"pass": true}' and response.parsed == {"pass": True}
    assert response.route.name == "openrouter" and response.cost_usd == 0.0123
    assert response.usage.input_tokens == 120 and response.usage.cache_read_tokens == 100


def test_direct_openai_request_disables_storage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-secret")
    api = FakeAPI(body=chat_body(cost=None))
    response = client(api=api).chat(MESSAGES, max_tokens=10, temperature=0.5)
    body = json.loads(api.requests[0].content)
    assert api.requests[0].url == "https://api.openai.com/v1/chat/completions"
    assert body["store"] is False and "provider" not in body and "usage" not in body
    assert body["max_tokens"] == 10 and body["temperature"] == 0.5 and body["model"] == "gpt-4.1"
    assert response.cost_usd is None  # no config/prices.yaml: unknown, never guessed


def test_anthropic_wire_and_tool_calls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-secret")
    reply = {"id": "msg_1", "model": "claude-sonnet-4-6",
             "content": [{"type": "text", "text": "Looking."},
                         {"type": "tool_use", "id": "tu_1", "name": "read_file", "input": {"path": "a"}}],
             "usage": {"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 2}}
    api = FakeAPI(body=reply)
    tools = [{"name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {}}}]
    messages = [*MESSAGES, {"role": "tool_result", "tool_call_id": "tu_0", "content": "done"}]
    response = client("interactive_manager_api", api=api, route_names=("anthropic",)).chat(messages, tools=tools)
    request = api.requests[0]
    body = json.loads(request.content)
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "an-secret" and request.headers["anthropic-version"]
    assert body["system"] == "Judge." and body["messages"][0] == {"role": "user", "content": "evidence"}
    assert body["messages"][1]["content"][0]["type"] == "tool_result"
    assert body["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert "response_format" not in body
    assert response.text == "Looking." and response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "a"} and response.usage.cache_read_tokens == 2


def test_chat_completions_tool_calls_and_tool_role(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    calls = [{"id": "c1", "type": "function", "function": {"name": "ls", "arguments": '{"d": "."}'}},
             {"id": "c2", "type": "function", "function": {"name": "ls", "arguments": "not json"}}]
    api = FakeAPI(body=chat_body("", tool_calls=calls))
    messages = [*MESSAGES, {"role": "tool_result", "tool_call_id": "c0", "content": "x"}]
    response = client("interactive_manager_api", api=api).chat(messages, tools=[{"name": "ls"}])
    body = json.loads(api.requests[0].content)
    assert body["messages"][-1] == {"role": "tool", "tool_call_id": "c0", "content": "x"}
    assert body["tools"][0]["type"] == "function"
    assert [(c.id, c.arguments) for c in response.tool_calls] == [("c1", {"d": "."}), ("c2", {"raw": "not json"})]


def test_azure_openai_route_uses_deployment_and_api_key_header(monkeypatch, tmp_path):
    monkeypatch.setenv("NEURICO_AZURE", "1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-secret")
    monkeypatch.setenv("AZURE_FOUNDRY_RESOURCE", "labres")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENTS", "gpt-4.1-mini,gpt-5.4")
    config = tmp_path / "agents.yaml"
    config.write_text(yaml.safe_dump({"roles": {"azure_judge": {"kind": "api", "routes": [
        {"name": "openrouter", "model": "openai/gpt-4.1"}, {"name": "azure_openai", "model": None}]}}}))
    api = FakeAPI()
    c = LLMClient.for_role("azure_judge", config_path=config, transport=api.transport(), ledger=RunLedger(enabled=False))
    assert [(r.name, r.model) for r in c.routes] == [("azure_openai", "gpt-4.1-mini")]
    c.chat(MESSAGES)
    request = api.requests[0]
    assert request.url == "https://labres.openai.azure.com/openai/v1/chat/completions"
    assert request.headers["api-key"] == "az-secret" and "authorization" not in request.headers


# -- fallback and cooldown ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 402, 403])
def test_key_errors_fall_back_and_mark_the_route_down(monkeypatch, status):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI({"openrouter.ai": status})
    c = client(api=api)
    first = c.chat(MESSAGES)
    assert first.route.name == "openai" and first.attempts == 2
    assert api.hosts() == ["openrouter.ai", "api.openai.com"]
    assert "sk-SECRET" not in (lc.route_down_reason("openrouter") or "")
    assert lc.route_down_reason("openrouter").startswith(lc._KEY_ERROR_REASONS[status])

    second = c.chat(MESSAGES)                      # marked down: OpenRouter is not even asked
    assert second.route.name == "openai" and second.attempts == 1
    assert api.hosts() == ["openrouter.ai", "api.openai.com", "api.openai.com"]

    now = time.monotonic()
    monkeypatch.setattr(lc.time, "monotonic", lambda: now + lc.PROVIDER_COOLDOWN_SECONDS + 1)
    api.status_by_host.clear()
    third = c.chat(MESSAGES)                       # cooldown over: tried again and, now healthy, cleared
    assert third.route.name == "openrouter" and lc.route_down_reason("openrouter") is None


def test_rate_limit_falls_back_without_cooldown(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI({"openrouter.ai": 429})
    c = client(api=api)
    assert c.chat(MESSAGES).route.name == "openai"
    assert lc.route_down_reason("openrouter") is None
    c.chat(MESSAGES)
    assert api.hosts() == ["openrouter.ai", "api.openai.com", "openrouter.ai", "api.openai.com"]


def test_insufficient_quota_429_is_a_key_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI({"openrouter.ai": (429, {"error": {"message": "quota", "code": "insufficient_quota"}})})
    client(api=api).chat(MESSAGES)
    assert lc.route_down_reason("openrouter") is not None


def test_server_errors_do_not_fall_back(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI({"openrouter.ai": 500})
    with pytest.raises(LLMHTTPError) as info:
        client(api=api).chat(MESSAGES)
    assert info.value.status_code == 500 and "sk-SECRET" not in str(info.value)
    assert api.hosts() == ["openrouter.ai"]


def test_all_routes_failing_is_a_credentials_problem(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI({"openrouter.ai": 401, "api.openai.com": 402})
    with pytest.raises(LLMProvidersUnavailableError, match="credentials or budget") as info:
        client(api=api).chat(MESSAGES)
    assert "sk-SECRET" not in str(info.value) and "invalid API key" in str(info.value)


def test_empty_reply_is_invalid_not_unavailable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    with pytest.raises(LLMResponseInvalidError):
        client(api=FakeAPI(body=chat_body("   "))).chat(MESSAGES)
    with pytest.raises(LLMResponseInvalidError):
        client(api=FakeAPI(body={"choices": []})).chat(MESSAGES)


# -- deadline ------------------------------------------------------------------------------------------------------

def test_outer_deadline_cancels_the_request_and_closes_the_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    state = {"cancelled": False, "closed": False}

    class SlowTransport(httpx.MockTransport):
        async def handle_async_request(self, request):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            return httpx.Response(200, json=chat_body())

        async def aclose(self):
            state["closed"] = True

    ledger = RunLedger(tmp_path / "ledger.jsonl")
    c = LLMClient.for_role("eval_verifier", transport=SlowTransport(lambda r: None), ledger=ledger)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        c.chat(MESSAGES, timeout_s=0.05)
    assert time.monotonic() - started < 1
    assert state == {"cancelled": True, "closed": True}
    [entry] = RunLedger.read(tmp_path / "ledger.jsonl")
    assert entry["status"] == "error" and entry["error.type"] == "TimeoutError"


# -- schema parsing ------------------------------------------------------------------------------------------------

SCHEMA = {"type": "object", "required": ["pass"], "properties": {"pass": {"type": "boolean"}}}


@pytest.mark.parametrize("text, parsed, error", [
    ('{"pass": true}', {"pass": True}, None),
    ('{"pass": "yes"}', None, "pass"),
    ('not json', None, "invalid JSON"),
])
def test_schema_parsing(monkeypatch, text, parsed, error):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    response = client(api=FakeAPI(body=chat_body(text))).chat(MESSAGES, response_schema=SCHEMA)
    assert response.parsed == parsed
    assert (error is None and response.parsing_error is None) or error in response.parsing_error
    assert response.text == text


def test_json_mode_without_schema_still_parses(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert client(api=FakeAPI(body=chat_body('{"a": 1}'))).chat(MESSAGES).parsed == {"a": 1}
    plain = client("idea_converter", api=FakeAPI(body=chat_body("title: x"))).chat(MESSAGES)
    assert plain.parsed is None and plain.parsing_error is None


# -- ledger ------------------------------------------------------------------------------------------------------

def test_every_call_writes_one_ledger_line(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_KEY", "or-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-secret")
    api = FakeAPI({"openrouter.ai": 429})
    work = tmp_path / "ws"
    c = LLMClient.for_role("eval_verifier", transport=api.transport(), work_dir=work, tags={"idea_id": "i1"})
    c.chat(MESSAGES)
    per_idea = RunLedger.read(work / ".neurico" / "agent_runs.jsonl")
    global_ = RunLedger.read(tmp_path / "global-ledger.jsonl")
    assert len(per_idea) == 1 and len(global_) == 1
    entry = per_idea[0]
    assert entry["gen_ai.operation.name"] == "chat" and entry["gen_ai.agent.name"] == "eval_verifier"
    assert entry["gen_ai.provider.name"] == "openai" and entry["gen_ai.request.model"] == "gpt-4.1"
    assert entry["auth"] == "OPENAI_API_KEY" and entry["permissions"] == "api" and entry["argv"] == []
    assert entry["gen_ai.usage.input_tokens"] == 120 and entry["gen_ai.usage.output_tokens"] == 30
    assert entry["cost_usd"] == 0.0123 and entry["attempts"] == 2 and entry["status"] == "ok"
    assert entry["tags"]["idea_id"] == "i1" and entry["tags"]["fallbacks"][0].startswith("openrouter:")
    text = json.dumps(entry)
    assert "or-secret" not in text and "oa-secret" not in text and "evidence" not in text


# -- migrated call sites ------------------------------------------------------------------------------------

def _patch_for_role(monkeypatch, module, api: FakeAPI):
    """Make ``module.LLMClient.for_role`` build clients over ``api`` with the ledger off."""
    real = LLMClient.for_role

    class Patched(LLMClient):
        @classmethod
        def for_role(cls, role, **kw):
            kw.setdefault("transport", api.transport())
            kw.setdefault("ledger", RunLedger(enabled=False))
            return real.__func__(cls, role, **kw)

    monkeypatch.setattr(module, "LLMClient", Patched)


def test_manager_openrouter_backend_keeps_its_interface(monkeypatch):
    import interactive.llm_backend as llm_backend
    monkeypatch.setenv("OPENROUTER_KEY", "k")
    calls = [{"id": "c1", "type": "function", "function": {"name": "ls", "arguments": '{"d": "."}'}}]
    api = FakeAPI(body=chat_body("Listing.", tool_calls=calls))
    _patch_for_role(monkeypatch, llm_backend, api)

    backend = llm_backend.LLMBackend(backend="openrouter")
    response = backend.send(MESSAGES, tools=[{"name": "ls", "parameters": {"type": "object"}}], timeout_seconds=7)

    assert isinstance(response, llm_backend.LLMResponse) and response.text == "Listing."
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("c1", "ls", {"d": "."})]
    body = json.loads(api.requests[0].content)
    assert body["model"] == "anthropic/claude-sonnet-4" and body["max_tokens"] == 4096
    assert api.requests[0].url.host == "openrouter.ai"

    monkeypatch.delenv("OPENROUTER_KEY")
    with pytest.raises(ValueError, match="OPENROUTER_KEY or OPENROUTER_API_KEY"):
        llm_backend.LLMBackend(backend="openrouter").send(MESSAGES)


def test_manager_anthropic_backend_uses_only_its_lane(monkeypatch):
    import interactive.llm_backend as llm_backend
    monkeypatch.setenv("OPENROUTER_KEY", "k")       # present, but the anthropic lane must not use it
    reply = {"id": "m", "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "Hi"}],
             "usage": {"input_tokens": 1, "output_tokens": 1}}
    api = FakeAPI(body=reply)
    _patch_for_role(monkeypatch, llm_backend, api)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        llm_backend.LLMBackend(backend="anthropic_api").send(MESSAGES)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    response = llm_backend.LLMBackend(backend="anthropic_api", model="claude-opus-4-6").send(MESSAGES)
    assert response.text == "Hi" and api.requests[0].url.host == "api.anthropic.com"
    assert json.loads(api.requests[0].content)["model"] == "claude-opus-4-6"


IDEA = {"title": "Probing attention heads", "description": "Study whether attention heads encode syntax in LLMs.",
        "tags": ["nlp"], "path": "/tmp/idea.md"}


def test_idea_converter_uses_template_without_a_key(monkeypatch, capsys):
    import cli.submit_local as submit_local
    result = submit_local.convert_to_yaml(dict(IDEA))
    assert result["parsed"]["idea"]["title"] == IDEA["title"]
    assert "template-based conversion" in capsys.readouterr().out


def test_idea_converter_parses_model_yaml_and_falls_back_on_failure(monkeypatch, capsys):
    import cli.submit_local as submit_local
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    api = FakeAPI(body=chat_body("```yaml\nidea:\n  title: 'Heads'\n  domain: nlp\n  hypothesis: 'Heads encode syntax'\n```"))
    _patch_for_role(monkeypatch, lc, api)   # submit_local imports LLMClient lazily
    result = submit_local.convert_to_yaml(dict(IDEA))
    assert result["parsed"]["idea"]["title"] == "Heads"
    body = json.loads(api.requests[0].content)
    assert body["temperature"] == 0.1 and body["max_tokens"] == 2000 and "response_format" not in body

    api.status_by_host["api.openai.com"] = 500
    result = submit_local.convert_to_yaml(dict(IDEA))
    assert result["parsed"]["idea"]["title"] == IDEA["title"]
    assert "Falling back to template-based conversion" in capsys.readouterr().out
