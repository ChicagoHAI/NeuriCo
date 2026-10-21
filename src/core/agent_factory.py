"""AgentFactory: one way to describe, build and run a coding-agent session.

Why this exists (docs/AGENT_FACTORY_ASSESSMENT.md): command and environment
construction were already shared (``core.agent_cli``), but every launch site
re-implemented the policy around them: how long to wait, what counts as done,
whether to retry, where the logs go, and nothing recorded usage or cost. The
factory keeps ``build_agent_command`` / ``build_agent_environment`` /
``run_prebuilt_cli_agent`` as the implementation and puts the policy in one
``AgentSpec`` per role, with defaults in ``config/agents.yaml``::

    factory = AgentFactory()
    handle = factory.build(factory.spec("resource_finder", provider="codex"))
    result = factory.run(handle, prompt, work_dir)
    result.legacy_dict()      # exactly what run_prebuilt_cli_agent returns today

Design points, so later steps do not undo them by accident:

* ``AgentSpec`` is role policy; the prompt, work dir and per-launch env are
  ``run()`` arguments, so a spec is built once and run per attempt (ideation).
* Argv on the OAuth and Azure lanes is byte-for-byte what the call sites
  produce today when no optional field is set (pinned by
  tests/test_agent_characterisation.py); optional fields only *add* flags.
* The deadline and process-group cleanup belong to ``run_prebuilt_cli_agent``;
  the factory never spawns a process itself. Docker and host routes differ only
  in paths, which the factory never translates.
* Output contracts are evaluated in Python after the process exits; a failed
  contract is an "invalid output" attempt whose issues are appended to the next
  prompt (the trimmer's ``prior_error`` loop, generalised).
* Every launch writes one ledger line (``core.run_ledger``) with usage parsed
  from the provider transcript; cost is ``None`` when unknown, never a guess.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import shlex
import shutil
import signal
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

import yaml

from core import agent_auth, azure_config
from core.agent_cli import build_agent_command, build_agent_environment, provider_skill_root
from core.agent_runner import RunTracker, next_attempt_number, run_prebuilt_cli_agent
from core.run_ledger import RunLedger, build_entry, tags_from_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "agents.yaml"

Provider = Literal["claude", "codex", "gemini"]
AuthLane = Literal["oauth", "azure"]
PROVIDERS: Tuple[str, ...] = ("claude", "codex", "gemini")
PERMISSION_MODES: Tuple[str, ...] = ("bypass", "inherit", "workspace", "read_only", "mcp_only", "no_tools")
OUTPUT_KINDS: Tuple[str, ...] = ("return_code", "marker", "files", "validator", "json_stdout",
                                 "json_schema", "json_file", "runtime")
Status = Literal["ok", "contract_failed", "timeout", "max_turns", "budget_exceeded",
                 "provider_failed", "stopped", "background_terminated", "error"]

PROVIDER_ENV_VAR = "NEURICO_AGENT_PROVIDER"
MODEL_ENV_VAR = "NEURICO_AGENT_MODEL"
AUTH_ENV_VAR = agent_auth.AGENT_AUTH_ENV_VAR
REJECTION_HEADER = "Previous attempt rejected:"


class AgentConfigError(ValueError):
    """config/agents.yaml or an override names something the factory cannot build."""


class BudgetExceeded(RuntimeError):
    """A run with ``budget.hard`` cost more than ``budget.max_cost_usd``."""


# -- spec types ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Permissions:
    """What the agent may do without asking.

    ``bypass`` is today's ``full_permissions=True``; ``inherit`` is today's
    ``full_permissions=False`` (the CLI's own default, no flag added). The other
    modes add provider flags: ``mcp_only`` is the HITL manager's bridged turn
    (Claude: ``--tools ToolSearch --allowedTools ToolSearch,<allowed_tools>`` plus
    ``--dangerously-skip-permissions``; Codex: read-only sandbox, approvals off),
    ``no_tools`` its tool-less turn (Claude: ``--safe-mode --tools ""``).
    """

    mode: str = "bypass"
    allowed_tools: Tuple[str, ...] = ()
    disallowed_tools: Tuple[str, ...] = ()
    bare: bool = False


@dataclass(frozen=True)
class Budget:
    """Limits on one run; every field is opt-in (config/agents.yaml ``budget`` or a caller override).

    The defaults impose nothing: ``timeout_s`` 0 or None means no wall-clock limit,
    ``max_turns`` / ``max_cost_usd`` / ``max_prompt_chars`` None means no cap, and
    ``hard`` False means an overrun is recorded (status ``budget_exceeded``) but never
    raised. Call sites use the convention ``timeout=None`` -> "use the role's config"
    and ``timeout=0`` -> "no limit" (``AgentFactory._apply_overrides``).
    """

    timeout_s: Optional[int] = None
    max_turns: Optional[int] = None
    max_cost_usd: Optional[float] = None
    max_prompt_chars: Optional[int] = None
    hard: bool = False  # raise BudgetExceeded instead of only recording


@dataclass(frozen=True)
class OutputContract:
    """How success is decided once the process has exited.

    ``validator`` and ``check`` may be callables or ``"module:function"``
    strings (resolved lazily so loading the YAML never imports agent modules);
    ``schema`` may be a dict or a path (relative to the project root).
    """

    kind: str = "return_code"
    marker: Optional[str] = None
    required_files: Tuple[str, ...] = ()
    path: Optional[str] = None
    validator: Any = None
    schema: Any = None
    check: Any = None
    min_chars: int = 0
    tolerate_nonzero: bool = False


@dataclass(frozen=True)
class RetryPolicy:
    """Adopted from IDEATION_INTEGRATION.md 4.3; research agents default to one attempt."""

    max_attempts: int = 1
    max_invalid_outputs: int = 0
    backoff_s: float = 30.0
    rate_limit_backoff_s: float = 90.0
    retry_on_timeout: bool = False


@dataclass(frozen=True)
class TranscriptPolicy:
    """The single place that knows the on-disk names of prompt, log and transcript."""

    logs_dir: Optional[Path] = None  # default <work_dir>/logs
    prefix: str = ""  # default: role name
    stem: str = ""  # full artifact stem (planner/scout name files by run id, not by provider)
    attempt_numbered: bool = False
    save_prompt: bool = True
    tracker_run_id: Optional[str] = None
    stream_json: bool = True  # False: plain-text output (manifest trimmer)
    echo: bool = True  # False: the stream is parsed, never printed (manager turns)
    separate_stderr: Optional[bool] = None  # None = provider default (Codex yes, others merged into the transcript)


@dataclass(frozen=True)
class AgentSpec:
    role: str
    provider: str = "claude"
    model: Optional[str] = None
    auth: str = "oauth"
    permissions: Permissions = Permissions()
    budget: Budget = Budget()
    output: OutputContract = OutputContract()
    extra_outputs: Tuple[OutputContract, ...] = ()
    retry: RetryPolicy = RetryPolicy()
    transcript: TranscriptPolicy = TranscriptPolicy()
    reasoning_effort: Optional[str] = None
    system_prompt: Optional[str] = None
    append_system_prompt: bool = True
    mcp_config: Optional[Path] = None
    mcp_startup_timeout_s: Optional[float] = None
    use_scribe: bool = False
    gemini_skip_trust: bool = True
    skills: Tuple[Path, ...] = ()
    env_allowlist: Optional[Tuple[str, ...]] = None
    isolate_home: bool = False
    extra_args: Tuple[str, ...] = ()
    env_extra: Mapping[str, str] = field(default_factory=dict)
    tags: Mapping[str, Any] = field(default_factory=dict)
    defer_provider_failure_to_runtime: bool = False
    hitl_budget_context: bool = True  # append the active HITL run's budget prompt (run_prebuilt_cli_agent)
    extras: Mapping[str, Any] = field(default_factory=dict)  # role keys the factory does not interpret

    @property
    def is_api_role(self) -> bool:
        return str(self.extras.get("kind", "cli")) == "api"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    model: Optional[str] = None
    session_id: Optional[str] = None
    duration_api_ms: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentHandle:
    spec: AgentSpec
    argv: Tuple[str, ...]
    env: Mapping[str, str]
    adapter: "ProviderAdapter"
    description: str


@dataclass
class AgentResult:
    status: str
    success: bool
    return_code: Optional[int]
    elapsed_s: float
    prompt_file: Optional[Path]
    log_file: Path
    transcript_file: Path
    outputs: Dict[str, str] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    structured: Any = None
    usage: Usage = field(default_factory=Usage)
    run_id: str = ""
    attempts: int = 1
    timed_out: bool = False
    stopped: bool = False
    background_processes_terminated: bool = False
    provider_process_failed: bool = False
    final_text: Optional[str] = None
    stderr_file: Optional[Path] = None  # set when the transcript policy keeps stderr apart
    extra: Dict[str, Any] = field(default_factory=dict)

    def legacy_dict(self) -> Dict[str, Any]:
        """The dict today's callers consume: ``run_prebuilt_cli_agent``'s nine keys,
        plus ``outputs`` / ``issues`` / ``structured`` only when the contract produced
        them, plus any caller-specific keys placed in ``extra``."""
        out: Dict[str, Any] = {
            "success": self.success,
            "return_code": self.return_code,
            "elapsed_time": self.elapsed_s,
            "log_file": str(self.log_file),
            "transcript_file": str(self.transcript_file),
            "timed_out": self.timed_out,
            "stopped": self.stopped,
            "background_processes_terminated": self.background_processes_terminated,
            "provider_process_failed": self.provider_process_failed,
        }
        if self.outputs:
            out["outputs"] = dict(self.outputs)
        if self.issues:
            out["issues"] = list(self.issues)
        if self.structured is not None:
            out["structured"] = self.structured
        out.update(self.extra)
        return out


# -- provider adapters -----------------------------------------------------------------------------------

class ProviderAdapter:
    """Provider-specific argv additions and transcript parsing.

    Argv starts from ``build_agent_command`` so the auth lane, model mapping
    and transcript flags stay exactly as today; the adapter only appends the
    flags for optional spec fields.
    """

    name: str = ""

    def full_permissions(self, spec: AgentSpec) -> bool:
        """Whether the provider's skip-approvals flag is added (today's ``full_permissions``)."""
        return spec.permissions.mode == "bypass"

    def argv(self, spec: AgentSpec) -> List[str]:
        base = build_agent_command(
            spec.provider,
            full_permissions=self.full_permissions(spec),
            use_scribe=spec.use_scribe,
            transcript_flags=None if spec.transcript.stream_json else {},
            gemini_skip_trust=spec.gemini_skip_trust,
            model=spec.model,
            agent_auth=spec.auth,
        )
        argv = shlex.split(base)
        argv += self.permission_args(spec)
        argv += self.budget_args(spec)
        argv += self.prompt_args(spec)
        argv += self.schema_args(spec)
        argv += list(spec.extra_args)
        return argv

    def env(self, spec: AgentSpec, env_extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        merged: Dict[str, str] = dict(spec.env_extra)
        merged.update({str(k): str(v) for k, v in (env_extra or {}).items()})
        return build_agent_environment(spec.provider, merged, agent_auth=spec.auth)

    # Hooks with provider-neutral defaults. Subclasses override what differs.
    def permission_args(self, spec: AgentSpec) -> List[str]:
        return []

    def budget_args(self, spec: AgentSpec) -> List[str]:
        return []

    def prompt_args(self, spec: AgentSpec) -> List[str]:
        return []

    def schema_args(self, spec: AgentSpec) -> List[str]:
        return []

    def resume_args(self, argv: Sequence[str], session_id: str) -> List[str]:
        raise AgentConfigError(f"{self.name} sessions cannot be resumed by the factory yet")

    def inline_system_prompt(self, spec: AgentSpec, prompt: str) -> str:
        """Providers without a system-prompt flag get it prepended to the prompt."""
        if spec.system_prompt:
            return f"{spec.system_prompt.rstrip()}\n\n{prompt}"
        return prompt

    def parse_transcript(self, transcript: Path) -> Tuple[Usage, Any, Optional[str], Optional[str]]:
        """-> (usage, structured_output, terminal_subtype, final_text)."""
        return Usage(), None, None, None


def _json_lines(path: Path):
    """Yield parsed JSON objects, skipping anything that is not one line of JSON."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _schema_text(schema: Any) -> str:
    return json.dumps(load_schema(schema))


def _schema_file(schema: Any) -> str:
    if isinstance(schema, (str, Path)) and not isinstance(schema, dict):
        return str(_resolve_project_path(Path(schema)))
    handle = tempfile.NamedTemporaryFile("w", suffix=".schema.json", delete=False, encoding="utf-8")
    with handle:
        handle.write(_schema_text(schema))
    return handle.name


class ClaudeCodeAdapter(ProviderAdapter):
    name = "claude"

    def full_permissions(self, spec: AgentSpec) -> bool:
        # The manager's MCP-only turns run with --dangerously-skip-permissions plus a tool allow-list.
        return spec.permissions.mode in ("bypass", "mcp_only")

    def permission_args(self, spec: AgentSpec) -> List[str]:
        p = spec.permissions
        args: List[str] = []
        if p.mode == "workspace":
            args += ["--permission-mode", "acceptEdits"]
        elif p.mode == "read_only":
            args += ["--permission-mode", "dontAsk"]
        elif p.mode == "mcp_only":
            # ToolSearch is the only built-in the bridged manager turn keeps; the MCP tools
            # are allow-listed by their global names (today's llm_backend._send_cli flags).
            allowed = list(dict.fromkeys(["ToolSearch", *(str(name) for name in p.allowed_tools)]))
            args += ["--tools", "ToolSearch", "--allowedTools", ",".join(allowed)]
        elif p.mode == "no_tools":
            # Safe mode also suppresses local hooks and project instructions while keeping
            # the CLI's own login; the manager's tools are parsed by the runtime, not the CLI.
            args += ["--safe-mode", "--tools", ""]
        if p.allowed_tools and p.mode != "mcp_only":
            args += ["--allowedTools", ",".join(p.allowed_tools)]
        if p.disallowed_tools:
            args += ["--disallowedTools", ",".join(p.disallowed_tools)]
        if p.bare:
            args.append("--bare")
        if spec.mcp_config is not None:
            args += ["--mcp-config", str(spec.mcp_config), "--strict-mcp-config"]
        return args

    def env(self, spec: AgentSpec, env_extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        env = super().env(spec, env_extra)
        if spec.mcp_config is not None and spec.mcp_startup_timeout_s:
            # Claude Code's own MCP startup window, in blocking mode so the init event
            # reports the servers' real status (the manager's readiness gate reads it).
            startup_ms = max(1, int(validated_mcp_startup_timeout(spec.mcp_startup_timeout_s) * 1000))
            env["MCP_CONNECTION_NONBLOCKING"] = "0"
            env["MCP_CONNECT_TIMEOUT_MS"] = str(startup_ms)
            env["MCP_TIMEOUT"] = str(startup_ms)
        return env

    def budget_args(self, spec: AgentSpec) -> List[str]:
        args: List[str] = []
        if spec.budget.max_turns:
            args += ["--max-turns", str(spec.budget.max_turns)]
        if spec.budget.max_cost_usd:
            args += ["--max-budget-usd", str(spec.budget.max_cost_usd)]
        if spec.reasoning_effort:
            args += ["--effort", spec.reasoning_effort]
        return args

    def prompt_args(self, spec: AgentSpec) -> List[str]:
        if not spec.system_prompt:
            return []
        flag = "--append-system-prompt" if spec.append_system_prompt else "--system-prompt"
        return [flag, spec.system_prompt]

    def schema_args(self, spec: AgentSpec) -> List[str]:
        if spec.output.kind == "json_schema" and spec.output.schema is not None:
            return ["--json-schema", _schema_text(spec.output.schema)]
        return []

    def inline_system_prompt(self, spec: AgentSpec, prompt: str) -> str:
        return prompt  # passed as a flag instead

    def resume_args(self, argv: Sequence[str], session_id: str) -> List[str]:
        return list(argv) + ["--resume", session_id]

    def parse_transcript(self, transcript: Path):
        usage, structured, subtype, text = Usage(), None, None, None
        for obj in _json_lines(transcript):
            if obj.get("type") == "system" and obj.get("model"):
                usage.model = usage.model or str(obj["model"])
                usage.session_id = usage.session_id or obj.get("session_id")
            if obj.get("type") != "result":
                continue
            raw = obj.get("usage") or {}
            usage.input_tokens = int(raw.get("input_tokens") or 0)
            usage.output_tokens = int(raw.get("output_tokens") or 0)
            usage.cache_read_tokens = int(raw.get("cache_read_input_tokens") or 0)
            usage.cache_write_tokens = int(raw.get("cache_creation_input_tokens") or 0)
            usage.cost_usd = obj.get("total_cost_usd")
            usage.num_turns = obj.get("num_turns")
            usage.session_id = obj.get("session_id") or usage.session_id
            usage.duration_api_ms = obj.get("duration_api_ms")
            models = obj.get("modelUsage") or {}
            if models:
                usage.model = next(iter(models))
            structured = obj.get("structured_output")
            subtype = obj.get("subtype")
            text = obj.get("result") if isinstance(obj.get("result"), str) else text
        return usage, structured, subtype, text


class CodexAdapter(ProviderAdapter):
    name = "codex"

    def permission_args(self, spec: AgentSpec) -> List[str]:
        p = spec.permissions
        codex = spec.extras.get("codex") or {}
        args: List[str] = []
        if p.mode == "workspace":
            args += ["--sandbox", "workspace-write"]
        elif p.mode in ("read_only", "mcp_only", "no_tools"):
            args += ["-c", 'approval_policy="never"', "--sandbox", "read-only"]
        elif p.mode == "inherit":
            # The role's `codex` block may still pin a sandbox (the interactive manager's
            # read-only turns); `bypass` is --yolo and ignores it.
            if codex.get("approval_policy"):
                args += ["-c", f'approval_policy="{codex["approval_policy"]}"']
            if codex.get("sandbox"):
                args += ["--sandbox", str(codex["sandbox"])]
        if codex.get("skip_git_repo_check"):
            args.append("--skip-git-repo-check")
        if p.bare:
            args.append("--ignore-user-config")
        if spec.mcp_config is not None:
            # Codex has no --mcp-config: the servers become -c mcp_servers.<name>.* overrides,
            # with the allow-listed tools and the startup window per server.
            args += codex_mcp_config_args(
                spec.mcp_config,
                allowed_mcp_tools=list(p.allowed_tools) if p.mode == "mcp_only" else None,
                startup_timeout_seconds=spec.mcp_startup_timeout_s,
            )
        return args

    def budget_args(self, spec: AgentSpec) -> List[str]:
        if spec.reasoning_effort:
            return ["-c", f'model_reasoning_effort="{spec.reasoning_effort}"']
        return []

    def schema_args(self, spec: AgentSpec) -> List[str]:
        if spec.output.kind == "json_schema" and spec.output.schema is not None:
            return ["--output-schema", _schema_file(spec.output.schema)]
        return []

    def resume_args(self, argv: Sequence[str], session_id: str) -> List[str]:
        argv = list(argv)
        idx = argv.index("exec") + 1 if "exec" in argv else 1
        return argv[:idx] + ["resume", session_id] + argv[idx:]

    def parse_transcript(self, transcript: Path):
        usage, text = Usage(), None
        for obj in _json_lines(transcript):
            kind = obj.get("type")
            if kind == "thread.started":
                usage.session_id = obj.get("thread_id") or usage.session_id
            elif kind == "turn.completed":
                raw = obj.get("usage") or {}
                usage.input_tokens += int(raw.get("input_tokens") or 0)
                usage.output_tokens += int(raw.get("output_tokens") or 0)
                usage.cache_read_tokens += int(raw.get("cached_input_tokens") or 0)
                usage.num_turns = (usage.num_turns or 0) + 1
            elif kind == "item.completed":
                item = obj.get("item") or {}
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    text = item["text"]
        return usage, None, None, text


class GeminiAdapter(ProviderAdapter):
    name = "gemini"

    def permission_args(self, spec: AgentSpec) -> List[str]:
        if spec.permissions.mode == "workspace":
            return ["--approval-mode", "auto_edit"]
        if spec.mcp_config is not None:
            raise AgentConfigError("mcp_config is wired for Claude only until the manager migrates (step 8)")
        return []

    def parse_transcript(self, transcript: Path):
        usage, text = Usage(), None
        for obj in _json_lines(transcript):
            kind = obj.get("type")
            if kind == "init":
                usage.session_id = obj.get("session_id") or usage.session_id
                usage.model = obj.get("model") or usage.model
            elif kind == "message" and obj.get("role") == "assistant" and isinstance(obj.get("content"), str):
                text = obj["content"]
            elif kind == "result":
                stats = obj.get("stats") or {}
                usage.input_tokens = int(stats.get("input_tokens") or 0)
                usage.output_tokens = int(stats.get("output_tokens") or 0)
                usage.cache_read_tokens = int(stats.get("cached") or 0)
                usage.duration_api_ms = stats.get("duration_ms")
        return usage, None, None, text


ADAPTERS: Dict[str, ProviderAdapter] = {
    "claude": ClaudeCodeAdapter(),
    "codex": CodexAdapter(),
    "gemini": GeminiAdapter(),
}


# -- MCP helpers (shared with interactive.llm_backend's legacy path) ---------------------------------------

def validated_mcp_startup_timeout(value: Any) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("MCP startup timeout must be a positive finite number")
    return timeout


def mcp_server_names(mcp_config_path: Path) -> List[str]:
    payload = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
    servers = payload.get("mcpServers") or payload.get("mcp_servers") or {}
    if not isinstance(servers, dict) or not servers:
        raise ValueError("MCP configuration must define at least one server")
    return [str(name) for name in servers]


def _codex_config_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def codex_mcp_config_args(mcp_config_path: Path, *, allowed_mcp_tools: Optional[Sequence[str]] = None,
                          startup_timeout_seconds: Optional[float] = None) -> List[str]:
    """Claude-style ``mcpServers`` JSON -> ``codex exec -c mcp_servers.<name>.<key>=...`` overrides.

    Every server is required; ``allowed_mcp_tools`` (global ``mcp__<server>__<tool>`` names)
    becomes the server's ``enabled_tools`` when given; ``startup_timeout_seconds`` is the
    per-server ``startup_timeout_sec``.
    """
    payload = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
    servers = payload.get("mcpServers") or payload.get("mcp_servers") or {}
    if not isinstance(servers, dict) or not servers:
        raise ValueError("Codex MCP configuration must define at least one server")
    args: List[str] = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            raise ValueError(f"Codex MCP server {name!r} must be an object")
        prefix = f"mcp_servers.{name}"
        for key in ("command", "args", "cwd", "url", "enabled"):
            if key in server:
                args.extend(["-c", f"{prefix}.{key}={_codex_config_value(server[key])}"])
        approval = server.get("default_tools_approval_mode", "approve")
        args.extend(["-c", f"{prefix}.default_tools_approval_mode={_codex_config_value(approval)}"])
        env = server.get("env")
        if isinstance(env, dict):
            for env_key, env_value in env.items():
                args.extend(["-c", f"{prefix}.env.{env_key}={_codex_config_value(str(env_value))}"])
        if "enabled" not in server:
            args.extend(["-c", f"{prefix}.enabled=true"])
        allowed_prefix = f"mcp__{name}__"
        enabled_tools = [
            tool_name[len(allowed_prefix):]
            for raw_name in allowed_mcp_tools or []
            if (tool_name := str(raw_name).strip()).startswith(allowed_prefix)
        ]
        if allowed_mcp_tools is not None:
            args.extend(["-c", f"{prefix}.enabled_tools={_codex_config_value(enabled_tools)}"])
        args.extend(["-c", f"{prefix}.required=true"])
        if startup_timeout_seconds is not None:
            timeout = validated_mcp_startup_timeout(startup_timeout_seconds)
            args.extend(["-c", f"{prefix}.startup_timeout_sec={timeout:g}"])
    return args


# -- pricing -----------------------------------------------------------------------------------------------

PRICES_PATH = PROJECT_ROOT / "config" / "prices.yaml"


def price_usage(usage: Usage, model: Optional[str], prices_path: Optional[Path] = None) -> Optional[float]:
    """USD for ``usage`` from ``config/prices.yaml`` (per-million-token rates), else None.

    The file documents its own format; it is optional, and a model that is missing
    or mapped to null yields None so a missing price is visible in the ledger
    (``unpriced_runs``) instead of looking free. ``prices_path`` defaults to
    ``PRICES_PATH`` at call time (tests point it elsewhere).
    """
    prices_path = Path(prices_path) if prices_path is not None else PRICES_PATH
    if not model or not prices_path.exists():
        return None
    try:
        table = yaml.safe_load(prices_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    rates = (table.get("models") or {}).get(model)
    if not isinstance(rates, dict):
        return None
    per_million = lambda key: float(rates.get(key) or 0) / 1_000_000  # noqa: E731
    return round(usage.input_tokens * per_million("input") + usage.output_tokens * per_million("output")
                 + usage.cache_read_tokens * per_million("cache_read")
                 + usage.cache_write_tokens * per_million("cache_write"), 6)


# -- structured output -------------------------------------------------------------------------------------------

def _resolve_project_path(path: Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_schema(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, dict):
        return schema
    path = _resolve_project_path(Path(schema))
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_callable(ref: Any) -> Optional[Callable[..., Any]]:
    """``"pkg.module:function"`` -> callable; callables pass through; None stays None."""
    if ref is None or callable(ref):
        return ref
    module_name, _, attr = str(ref).partition(":")
    if not module_name or not attr:
        raise AgentConfigError(f"callable reference must look like 'module:function', got {ref!r}")
    return getattr(importlib.import_module(module_name), attr)


def validate_against_schema(data: Any, schema: Any) -> List[str]:
    """Issues from jsonschema, or an empty list; silently a no-op when jsonschema is missing."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - optional dependency
        return []
    loaded = load_schema(schema)
    validator_cls = jsonschema.validators.validator_for(loaded)
    errors = sorted(validator_cls(loaded).iter_errors(data), key=lambda e: [str(p) for p in e.path])
    return [f"schema: {'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in errors]


def extract_json_object(text: str) -> Dict[str, Any]:
    """First balanced JSON object in free text (the manifest trimmer's extractor)."""
    from agents.manifest_trimmer import _extract_json_object

    return _extract_json_object(text)


@dataclass
class ContractOutcome:
    ok: bool
    outputs: Dict[str, str] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    structured: Any = None


def _validate_structured(contract: OutputContract, data: Any, work_dir: Path) -> List[str]:
    issues: List[str] = []
    if contract.schema is not None:
        issues += validate_against_schema(data, contract.schema)
    check = resolve_callable(contract.check)
    if check is not None and not issues:
        try:
            check(data, work_dir)
        except ValueError as exc:
            issues.append(f"check: {exc}")
    return issues


def evaluate_contract(contract: OutputContract, work_dir: Path, *, final_text: Optional[str] = None,
                      cli_structured: Any = None) -> ContractOutcome:
    """Decide the artifact side of success; the launch side is combined by the factory."""
    work_dir = Path(work_dir)
    kind = contract.kind
    if kind in ("return_code", "runtime"):
        return ContractOutcome(ok=True)
    if kind == "marker":
        marker = work_dir / (contract.marker or "")
        if marker.exists():
            return ContractOutcome(ok=True, outputs={"completion_marker": str(marker)})
        return ContractOutcome(ok=False, issues=[f"completion marker missing: {marker}"])
    if kind == "files":
        outputs, issues = {}, []
        for rel in contract.required_files:
            path = work_dir / rel
            if path.is_file() and path.stat().st_size > 0:
                outputs[rel] = str(path)
            else:
                issues.append(f"required file missing or empty: {path}")
        return ContractOutcome(ok=not issues, outputs=outputs, issues=issues)
    if kind == "validator":
        verdict = resolve_callable(contract.validator)(work_dir)
        found = {k: str(v) for k, v in (verdict.get("found") or {}).items()}
        return ContractOutcome(ok=bool(verdict.get("valid")), outputs=found, issues=list(verdict.get("issues") or []))
    if kind == "json_file":
        path = work_dir / (contract.path or "")
        if not path.is_file() or path.stat().st_size == 0:
            return ContractOutcome(ok=False, issues=[f"output file missing or empty: {path}"])
        text = path.read_text(encoding="utf-8")
        if contract.min_chars and len(text) < contract.min_chars:
            return ContractOutcome(ok=False, issues=[f"{path} is shorter than {contract.min_chars} chars"])
        if contract.schema is None and contract.check is None and not path.suffix == ".json":
            return ContractOutcome(ok=True, outputs={contract.path: str(path)}, structured=text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return ContractOutcome(ok=False, issues=[f"{path} is not valid JSON: {exc}"])
        issues = _validate_structured(contract, data, work_dir)
        return ContractOutcome(ok=not issues, outputs={contract.path: str(path)}, issues=issues,
                               structured=None if issues else data)
    if kind in ("json_stdout", "json_schema"):
        data = cli_structured
        if data is None:
            try:
                data = extract_json_object(final_text or "")
            except ValueError as exc:
                return ContractOutcome(ok=False, issues=[f"no JSON object in the agent's final answer: {exc}"])
        issues = _validate_structured(contract, data, work_dir)
        return ContractOutcome(ok=not issues, issues=issues, structured=None if issues else data)
    raise AgentConfigError(f"unknown output contract kind {kind!r}")


# -- config -------------------------------------------------------------------------------------------------

_SPEC_FIELDS = {f.name for f in fields(AgentSpec)}
_BLOCKS = {"permissions": Permissions, "budget": Budget, "output": OutputContract,
           "retry": RetryPolicy, "transcript": TranscriptPolicy}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_agents_config(path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    if not Path(path).exists():
        return {"version": 1, "default": {}, "roles": {}, "ledger": {}}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    data.setdefault("default", {})
    data.setdefault("roles", {})
    data.setdefault("ledger", {})
    return data


def resolve_role_config(config: Mapping[str, Any], role: str) -> Dict[str, Any]:
    """``default`` <- the ``extends`` chain <- the role block. Unknown roles get ``default``."""
    roles = config.get("roles") or {}
    chain: List[Mapping[str, Any]] = []
    name, seen = role, set()
    while name in roles:
        if name in seen:
            raise AgentConfigError(f"extends cycle at role {name!r}")
        seen.add(name)
        block = dict(roles[name] or {})
        chain.append(block)
        name = block.get("extends")
        if name is None:
            break
        if name not in roles:
            raise AgentConfigError(f"role {role!r} extends unknown role {name!r}")
    merged: Dict[str, Any] = dict(config.get("default") or {})
    for block in reversed(chain):
        block = {k: v for k, v in block.items() if k != "extends"}
        merged = _deep_merge(merged, block)
    return merged


def _build_block(cls, value: Any, name: str):
    if value is None:
        return cls()
    if isinstance(value, cls):
        return value
    if not isinstance(value, Mapping):
        raise AgentConfigError(f"{name} must be a mapping or {cls.__name__}, got {type(value).__name__}")
    allowed = {f.name for f in fields(cls)}
    unknown = set(value) - allowed
    if unknown:
        raise AgentConfigError(f"unknown {name} keys: {sorted(unknown)}")
    kwargs = dict(value)
    for key in ("required_files", "allowed_tools", "disallowed_tools"):
        if key in kwargs and kwargs[key] is not None:
            kwargs[key] = tuple(kwargs[key])
    if "logs_dir" in kwargs and kwargs["logs_dir"] is not None:
        kwargs["logs_dir"] = Path(kwargs["logs_dir"])
    return cls(**kwargs)


def spec_from_config(role: str, cfg: Mapping[str, Any]) -> AgentSpec:
    """Typed spec from a merged role mapping; keys the factory does not own go to ``extras``."""
    cfg = dict(cfg)
    kwargs: Dict[str, Any] = {"role": role}
    extras: Dict[str, Any] = {}
    for key, value in cfg.items():
        if key in _BLOCKS:
            kwargs[key] = _build_block(_BLOCKS[key], value, key)
        elif key == "extra_outputs":
            kwargs[key] = tuple(_build_block(OutputContract, v, "extra_outputs") for v in (value or ()))
        elif key == "skills":
            kwargs[key] = tuple(Path(v) for v in (value or ()))
        elif key in ("extra_args",):
            kwargs[key] = tuple(value or ())
        elif key == "env_allowlist":
            kwargs[key] = None if value is None else tuple(value)
        elif key == "mcp_config":
            kwargs[key] = None if value is None else Path(value)
        elif key in _SPEC_FIELDS:
            kwargs[key] = value
        else:
            extras[key] = value
    kwargs["extras"] = extras
    spec = AgentSpec(**kwargs)
    if spec.provider not in PROVIDERS and not spec.is_api_role:
        raise AgentConfigError(f"role {role!r}: unknown provider {spec.provider!r}")
    if spec.permissions.mode not in PERMISSION_MODES:
        raise AgentConfigError(f"role {role!r}: unknown permissions mode {spec.permissions.mode!r}")
    if spec.output.kind not in OUTPUT_KINDS:
        raise AgentConfigError(f"role {role!r}: unknown output kind {spec.output.kind!r}")
    return spec


# -- the factory ----------------------------------------------------------------------------------------------

def new_run_id(role: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{role}_{stamp}_{uuid.uuid4().hex[:4]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class _ArtifactNames:
    prompt: Optional[Path]
    log: Path
    transcript: Path
    stderr: Optional[Path]


class _LaunchTracker:
    """Duck-typed RunTracker: records the pid (for cancel) and forwards to a real tracker."""

    def __init__(self, inner: Optional[RunTracker], on_start: Optional[Callable[[int], None]]):
        self.inner = inner
        self.on_start = on_start
        self.pid: Optional[int] = None

    def mark_running(self, pid: int) -> None:
        self.pid = pid
        if self.on_start is not None:
            self.on_start(pid)
        if self.inner is not None:
            self.inner.mark_running(pid)

    def mark_stopped(self) -> None:
        if self.inner is not None:
            self.inner.mark_stopped()


class AgentFactory:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH, env: Optional[Mapping[str, str]] = None,
                 ledger: Optional[RunLedger] = None) -> None:
        self.config_path = Path(config_path)
        self.config = load_agents_config(self.config_path)
        self.env = env  # None = live os.environ (what build_agent_* read)
        self.ledger = ledger if ledger is not None else RunLedger.from_config(self.config.get("ledger"), env)

    # -- spec --------------------------------------------------------------------------------------------
    def spec(self, role: str, **overrides: Any) -> AgentSpec:
        """defaults(role) <- NEURICO_* env <- overrides. ``None`` overrides are ignored so
        CLI flags with no value do not clobber the configured default."""
        cfg = resolve_role_config(self.config, role)
        cfg = self._apply_env(cfg)
        cfg = self._apply_overrides(cfg, overrides)
        return spec_from_config(role, cfg)

    def _environ(self) -> Mapping[str, str]:
        return os.environ if self.env is None else self.env

    def _apply_env(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        env = self._environ()
        for var, key in ((PROVIDER_ENV_VAR, "provider"), (MODEL_ENV_VAR, "model"), (AUTH_ENV_VAR, "auth")):
            value = (env.get(var) or "").strip()
            if value:
                cfg[key] = value
        cfg["auth"] = agent_auth.resolve_agent_auth(cfg.get("auth"), env)
        env_tags = tags_from_env(env)
        if env_tags:  # NEURICO_AGENT_TAGS (job_id, campaign ...) under the role's own tags and overrides
            cfg["tags"] = _deep_merge(env_tags, cfg.get("tags") or {})
        return cfg

    @staticmethod
    def _apply_overrides(cfg: Dict[str, Any], overrides: Mapping[str, Any]) -> Dict[str, Any]:
        for key, value in overrides.items():
            if key == "timeout":
                # Call-site convention: None = use the role's configured budget (which is
                # "no limit" unless config/agents.yaml opts in), 0 = explicitly no limit.
                if value is None:
                    continue
                cfg["budget"] = _deep_merge(cfg.get("budget") or {}, {"timeout_s": int(value)})
                continue
            if value is None:
                continue
            if key == "full_permissions":  # today's flag, mapped onto the permissions block
                cfg["permissions"] = _deep_merge(cfg.get("permissions") or {}, {"mode": "bypass" if value else "inherit"})
            elif key in _BLOCKS and isinstance(value, Mapping):
                cfg[key] = _deep_merge(cfg.get(key) or {}, value)
            elif key in ("env_extra", "tags") and isinstance(value, Mapping):
                cfg[key] = _deep_merge(cfg.get(key) or {}, value)
            else:
                cfg[key] = value
        return cfg

    # -- build -------------------------------------------------------------------------------------------
    def build(self, spec: AgentSpec, env_extra: Optional[Mapping[str, str]] = None) -> AgentHandle:
        """Resolve argv and environment; no process is started."""
        if spec.is_api_role:
            raise AgentConfigError(f"role {spec.role!r} is an API role; use LLMClient, not the agent factory")
        adapter = ADAPTERS[spec.provider]
        argv = tuple(adapter.argv(spec))
        env = adapter.env(spec, env_extra)
        env = self._apply_isolation(spec, env)
        description = f"{agent_auth.describe(spec.provider, spec.auth, spec.model)} | {azure_config.describe()}"
        return AgentHandle(spec=spec, argv=argv, env=env, adapter=adapter, description=description)

    def _apply_isolation(self, spec: AgentSpec, env: Dict[str, str]) -> Dict[str, str]:
        """``env_allowlist`` keeps only named inherited keys; keys the lane or the caller
        added survive because the launch would not work without them."""
        if spec.env_allowlist is None:
            return env
        base = self._environ()
        keep = set(spec.env_allowlist) | {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "SHELL"}
        return {k: v for k, v in env.items()
                if k in keep or k.startswith("NEURICO_") or k not in base or base.get(k) != v}

    # -- run ---------------------------------------------------------------------------------------------
    def run(self, handle: AgentHandle, prompt: str, work_dir: Path, env_extra: Optional[Mapping[str, str]] = None,
            *, run_id: Optional[str] = None, prompt_meta: Any = None,
            on_start: Optional[Callable[[int], None]] = None, ledger_dir: Optional[Path] = None,
            on_line: Optional[Callable[[str], None]] = None) -> AgentResult:
        """1. prompt-size check  2. stage skills / isolation  3. attempts loop over
        ``run_prebuilt_cli_agent``  4. parse transcript  5. evaluate contracts
        6. ledger  7. return.

        ``ledger_dir`` is the per-idea ledger root when it differs from the process
        cwd (the AutoResearch proposer runs in an attempt directory but belongs to
        the workspace); ``on_start`` receives the pid as today's RunTracker does;
        ``on_line`` sees each transcript line as it streams (the manager's MCP gate)."""
        spec = handle.spec
        work_dir = Path(work_dir)
        run_id = run_id or new_run_id(spec.role)
        self._check_prompt_size(spec, prompt)
        self._stage_skills(spec, work_dir)
        env = self._run_env(handle, work_dir, env_extra)
        ts_start = _utc_now()
        attempt, invalid_outputs = 0, 0
        prompt_text = handle.adapter.inline_system_prompt(spec, prompt)
        base_prompt = prompt_text
        while True:
            attempt += 1
            result = self._launch_once(handle, prompt_text, work_dir, env, run_id, attempt, on_start, on_line)
            decision = self._retry_decision(spec, result, attempt, invalid_outputs)
            if decision is None:
                break
            reason, delay = decision
            if reason == "invalid":
                invalid_outputs += 1
                prompt_text = feedback_prompt(base_prompt, result.issues)
            if delay:
                time.sleep(delay)
        result.attempts = attempt
        result.run_id = run_id
        self._record(handle, result, Path(ledger_dir) if ledger_dir else work_dir, prompt, ts_start, prompt_meta)
        if spec.budget.hard and result.status == "budget_exceeded":
            raise BudgetExceeded(f"{spec.role}: cost {result.usage.cost_usd} exceeds {spec.budget.max_cost_usd} USD")
        return result

    def session(self, handle: AgentHandle, work_dir: Path, *, resume: bool = True) -> "AgentSession":
        return AgentSession(self, handle, Path(work_dir), resume=resume)

    # -- run internals --------------------------------------------------------------------------------------
    @staticmethod
    def _check_prompt_size(spec: AgentSpec, prompt: str) -> None:
        # Only when the role opts in (budget.max_prompt_chars): meant for a provider's real
        # context limit, where launching would fail anyway after the spend.
        limit = spec.budget.max_prompt_chars
        if limit and len(prompt) > limit:
            raise ValueError(f"{spec.role}: prompt is {len(prompt)} chars, over the {limit} limit")

    @staticmethod
    def _stage_skills(spec: AgentSpec, work_dir: Path) -> None:
        """Copy each skill directory into the provider's workspace skill root."""
        for skill in spec.skills:
            src = _resolve_project_path(Path(skill))
            if not src.is_dir():
                raise AgentConfigError(f"{spec.role}: skill directory not found: {src}")
            dst = work_dir / provider_skill_root(spec.provider) / src.name
            shutil.copytree(src, dst, dirs_exist_ok=True)

    def _run_env(self, handle: AgentHandle, work_dir: Path, env_extra: Optional[Mapping[str, str]]) -> Dict[str, str]:
        env = dict(handle.env)
        env.update({str(k): str(v) for k, v in (env_extra or {}).items()})
        if handle.spec.use_scribe:
            env["SCRIBE_RUN_DIR"] = str(work_dir)
        if handle.spec.isolate_home:
            home = work_dir / ".neurico" / "home"
            for sub in ("claude", "codex"):
                (home / sub).mkdir(parents=True, exist_ok=True)
            env.update({"HOME": str(home), "CODEX_HOME": str(home / "codex"), "CLAUDE_CONFIG_DIR": str(home / "claude")})
        return env

    def _artifact_names(self, spec: AgentSpec, work_dir: Path, attempt: int) -> _ArtifactNames:
        """Today's layout: ``<prefix>_prompt[_attemptN].txt``, ``<prefix>_<provider>[_attemptN].log``,
        ``<prefix>_<provider>[_attemptN]_transcript.jsonl``. Retries after the first attempt are
        always numbered so the first attempt's audit trail survives."""
        t = spec.transcript
        logs_dir = Path(t.logs_dir) if t.logs_dir is not None else work_dir / "logs"
        prefix = t.prefix or spec.role
        base = t.stem or f"{prefix}_{spec.provider}"
        if t.attempt_numbered:
            n = next_attempt_number(logs_dir, lambda i: f"{base}_attempt{i}.log")
            suffix = f"_attempt{n}"
        else:
            suffix = f"_attempt{attempt}" if attempt > 1 else ""
        stem = f"{base}{suffix}"
        prompt_stem = t.stem or prefix
        separate_stderr = spec.provider == "codex" if t.separate_stderr is None else bool(t.separate_stderr)
        return _ArtifactNames(
            prompt=(logs_dir / f"{prompt_stem}_prompt{suffix}.txt") if t.save_prompt else None,
            log=logs_dir / f"{stem}.log",
            transcript=logs_dir / f"{stem}_transcript.jsonl",
            stderr=(logs_dir / f"{stem}_stderr.log") if separate_stderr else None,
        )

    def _launch_once(self, handle: AgentHandle, prompt: str, work_dir: Path, env: Dict[str, str], run_id: str,
                     attempt: int, on_start: Optional[Callable[[int], None]],
                     on_line: Optional[Callable[[str], None]] = None) -> AgentResult:
        spec = handle.spec
        names = self._artifact_names(spec, work_dir, attempt)
        if names.prompt is not None:
            names.prompt.parent.mkdir(parents=True, exist_ok=True)
            names.prompt.write_text(prompt, encoding="utf-8")
        inner = RunTracker(work_dir, spec.transcript.tracker_run_id, spec.role) if spec.transcript.tracker_run_id else None
        tracker = _LaunchTracker(inner, on_start)
        launch = run_prebuilt_cli_agent(
            command_argv=list(handle.argv), prompt=prompt, work_dir=work_dir, log_file=names.log,
            transcript_file=names.transcript, env=env, timeout=spec.budget.timeout_s or None, tracker=tracker,
            provider=spec.provider, defer_provider_failure_to_runtime=spec.defer_provider_failure_to_runtime,
            stderr_file=names.stderr, on_line=on_line, echo_output=spec.transcript.echo,
            append_budget_prompt=spec.hitl_budget_context,
        )
        result = self._interpret(spec, handle.adapter, launch, names, work_dir)
        result.run_id = run_id
        if inner is not None:
            if result.success:
                inner.mark_completed(result.return_code or 0, result.legacy_dict())
            elif not result.stopped:
                inner.mark_failed(result.return_code, "; ".join(result.issues) or result.status)
        return result

    def _interpret(self, spec: AgentSpec, adapter: ProviderAdapter, launch: Mapping[str, Any], names: _ArtifactNames,
                   work_dir: Path) -> AgentResult:
        """Launch dict + transcript + contracts -> AgentResult with a single status."""
        usage, cli_structured, subtype, final_text = adapter.parse_transcript(names.transcript)
        if final_text is None and not spec.transcript.stream_json and names.transcript.exists():
            # plain-text mode: stdout *is* the final answer (the manifest trimmer's contract)
            final_text = names.transcript.read_text(encoding="utf-8", errors="replace")
        if usage.cost_usd is None:
            usage.cost_usd = price_usage(usage, usage.model or spec.model)
        result = AgentResult(
            status="ok", success=False, return_code=launch.get("return_code"), elapsed_s=float(launch.get("elapsed_time") or 0.0),
            prompt_file=names.prompt, log_file=names.log, transcript_file=names.transcript, usage=usage,
            timed_out=bool(launch.get("timed_out")), stopped=bool(launch.get("stopped")),
            background_processes_terminated=bool(launch.get("background_processes_terminated")),
            provider_process_failed=bool(launch.get("provider_process_failed")), final_text=final_text,
            stderr_file=names.stderr,
        )
        launch_ok = bool(launch.get("success")) or (
            spec.output.tolerate_nonzero and result.return_code is not None
            and not (result.timed_out or result.stopped or result.background_processes_terminated))
        status = self._launch_status(spec, result, launch_ok, subtype)
        if status is None:
            for contract in (spec.output, *spec.extra_outputs):
                outcome = evaluate_contract(contract, work_dir, final_text=final_text, cli_structured=cli_structured)
                result.outputs.update(outcome.outputs)
                result.issues.extend(outcome.issues)
                if contract is spec.output:
                    result.structured = outcome.structured
            status = "ok" if not result.issues else "contract_failed"
        result.status = status
        result.success = status == "ok"
        return result

    @staticmethod
    def _launch_status(spec: AgentSpec, result: AgentResult, launch_ok: bool, subtype: Optional[str]) -> Optional[str]:
        """Process-level failure status, or None when the contracts decide."""
        if result.stopped:
            return "stopped"
        if result.timed_out:
            return "timeout"
        if result.background_processes_terminated:
            return "background_terminated"
        if subtype == "error_max_turns":
            return "max_turns"
        cost = result.usage.cost_usd
        if spec.budget.max_cost_usd and cost is not None and cost > spec.budget.max_cost_usd:
            return "budget_exceeded"
        if subtype == "error_max_budget_usd":
            return "budget_exceeded"
        if not launch_ok:
            # A missing return code means the CLI never produced a verdict (could not be
            # started or reaped); a non-zero exit is an ordinary agent error. The HITL
            # ``provider_process_failed`` flag stays on the result for its runtime.
            return "provider_failed" if result.return_code is None else "error"
        return None

    @staticmethod
    def _retry_decision(spec: AgentSpec, result: AgentResult, attempt: int, invalid_outputs: int) -> Optional[Tuple[str, float]]:
        """(reason, delay_s) for another attempt, or None to stop."""
        policy = spec.retry
        if result.status == "contract_failed":
            return ("invalid", 0.0) if invalid_outputs < policy.max_invalid_outputs else None
        if result.status == "timeout":
            return ("timeout", policy.backoff_s) if policy.retry_on_timeout and attempt < policy.max_attempts else None
        if result.status in ("error", "provider_failed") and attempt < policy.max_attempts:
            rate_limited = _looks_rate_limited(result.log_file)
            return ("crash", policy.rate_limit_backoff_s if rate_limited else policy.backoff_s)
        return None

    def _record(self, handle: AgentHandle, result: AgentResult, work_dir: Path, prompt: str, ts_start: str,
                prompt_meta: Any) -> None:
        spec = handle.spec
        entry = build_entry(
            run_id=result.run_id, role=spec.role, provider=spec.provider, auth=spec.auth,
            permissions=spec.permissions.mode, argv=handle.argv, status=result.status, elapsed_s=result.elapsed_s,
            ts_start=ts_start, ts_end=_utc_now(), request_model=spec.model, response_model=result.usage.model,
            usage=result.usage.as_dict(), prompt_file=str(result.prompt_file) if result.prompt_file else None,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            template_id=getattr(prompt_meta, "template_id", None), template_sha=getattr(prompt_meta, "template_sha", None),
            variables_sha=getattr(prompt_meta, "variables_sha", None),
            error_type=None if result.success else result.status, attempts=result.attempts, tags=spec.tags,
            work_dir=str(work_dir), log_file=str(result.log_file), transcript_file=str(result.transcript_file),
        )
        self.ledger.record(entry, work_dir)


def feedback_prompt(prompt: str, issues: Sequence[str]) -> str:
    """The trimmer's ``prior_error`` pattern: the original prompt plus the validator's verdict."""
    bullets = "\n".join(f"- {issue}" for issue in issues) or "- output did not satisfy the contract"
    return f"{prompt.rstrip()}\n\n{REJECTION_HEADER}\n{bullets}\n"


def _looks_rate_limited(log_file: Path) -> bool:
    try:
        tail = Path(log_file).read_text(encoding="utf-8", errors="replace")[-20000:]
    except OSError:
        return False
    lowered = tail.lower()
    return "rate limit" in lowered or "rate_limit" in lowered or "429" in lowered


class AgentSession:
    """Multi-turn use of one handle: each ``send`` is a launch that, with
    ``resume=True``, resumes the provider session the previous turn reported.
    The HITL and interactive managers (``interactive.llm_backend.LLMBackend``)
    run with ``resume=False`` because every turn already carries the whole
    conversation in its prompt; ``session_id`` is still recorded per turn.
    ``cancel`` terminates the live process group. ``handle`` may be replaced
    between turns (the manager's allow-list and system prompt change per turn)."""

    def __init__(self, factory: AgentFactory, handle: AgentHandle, work_dir: Path, *, resume: bool = True) -> None:
        self.factory = factory
        self.handle = handle
        self.work_dir = work_dir
        self.resume = resume
        self.session_id: Optional[str] = None
        self.turns: List[AgentResult] = []
        self._live_pid: Optional[int] = None
        self._cancelled = False

    @property
    def live_pid(self) -> Optional[int]:
        """Pid of the turn in flight (its process group id), or None between turns."""
        return self._live_pid

    def _turn_handle(self) -> AgentHandle:
        if self.session_id is None or not self.resume:
            return self.handle
        argv = self.handle.adapter.resume_args(self.handle.argv, self.session_id)
        return replace(self.handle, argv=tuple(argv))

    def send(self, prompt: str, env_extra: Optional[Mapping[str, str]] = None, *,
             on_line: Optional[Callable[[str], None]] = None,
             tags: Optional[Mapping[str, Any]] = None) -> AgentResult:
        self._cancelled = False
        handle = self._turn_handle()
        # every turn gets its own numbered log/transcript so earlier turns are not overwritten
        turn_spec = replace(handle.spec, transcript=replace(handle.spec.transcript, attempt_numbered=True))
        if tags:
            turn_spec = replace(turn_spec, tags=_deep_merge(turn_spec.tags, tags))
        handle = replace(handle, spec=turn_spec)
        result = self.factory.run(handle, prompt, self.work_dir, env_extra, on_start=self._on_start, on_line=on_line)
        self._live_pid = None
        if self._cancelled:
            result.status, result.success, result.stopped = "stopped", False, True
        self.session_id = result.usage.session_id or self.session_id
        self.turns.append(result)
        return result

    def _on_start(self, pid: int) -> None:
        self._live_pid = pid

    def cancel(self) -> bool:
        """SIGTERM the live turn's process group; True when something was signalled."""
        pid = self._live_pid
        if pid is None:
            return False
        self._cancelled = True
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            return False
        return True
