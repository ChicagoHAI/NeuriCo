"""Run ledger: one JSON line per agent launch, with usage and cost.

Why: until now nothing in NeuriCo recorded what a launch cost or which session
produced which artifact; the only link between a run and its files was the log
name. The ledger gives every launch a ``run_id`` and a record that the daemon
(budgets), ``./neurico safety status`` (spend) and the ideation outcome files
can read back. Field names follow the OpenTelemetry GenAI semantic conventions
(``gen_ai.*``) so an OTLP/Langfuse exporter is a short script over the JSONL.

Two files receive every record:

* ``<work_dir>/.neurico/agent_runs.jsonl`` next to RunTracker's ``.neurico/runs``
  (the per-idea ledger; planner, scout and ideation pass the KB root as work_dir);
* a global ``logs/agent_runs.jsonl`` under the project root, overridable with
  ``NEURICO_AGENT_LEDGER`` (the container's ``/app`` may be read-only, the host's
  ``$PROJECT_ROOT`` is not).

Secrets never enter the ledger: argv is passed through ``sanitize_text`` and the
environment is only ever described, never written.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.security import sanitize_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_ENV_VAR = "NEURICO_AGENT_LEDGER"
DEFAULT_RELATIVE_PATH = Path(".neurico") / "agent_runs.jsonl"
DEFAULT_GLOBAL_PATH = PROJECT_ROOT / "logs" / "agent_runs.jsonl"


def build_entry(
    *,
    run_id: str,
    role: str,
    provider: str,
    auth: str,
    permissions: str,
    argv: Iterable[str],
    status: str,
    elapsed_s: float,
    ts_start: str,
    ts_end: str,
    request_model: Optional[str] = None,
    response_model: Optional[str] = None,
    usage: Optional[Mapping[str, Any]] = None,
    prompt_file: Optional[str] = None,
    prompt_sha256: Optional[str] = None,
    template_id: Optional[str] = None,
    template_sha: Optional[str] = None,
    variables_sha: Optional[str] = None,
    error_type: Optional[str] = None,
    attempts: int = 1,
    tags: Optional[Mapping[str, Any]] = None,
    work_dir: Optional[str] = None,
    log_file: Optional[str] = None,
    transcript_file: Optional[str] = None,
    operation: str = "invoke_agent",
) -> Dict[str, Any]:
    """Assemble one ledger record with the OTel GenAI attribute names.

    ``usage`` is the flat dict ``Usage.as_dict()`` produces (input_tokens,
    output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, num_turns,
    session_id, duration_api_ms). Cost is ``None`` when unknown, never a guess.
    """
    usage = dict(usage or {})
    return {
        "run_id": run_id,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "gen_ai.operation.name": operation,
        "gen_ai.agent.name": role,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": request_model,
        "gen_ai.response.model": response_model or usage.get("model"),
        "gen_ai.conversation.id": usage.get("session_id"),
        "auth": auth,
        "permissions": permissions,
        "argv": [sanitize_text(str(arg)) for arg in argv],
        "prompt_file": prompt_file,
        "prompt_sha256": prompt_sha256,
        "template_id": template_id,
        "template_sha": template_sha,
        "variables_sha": variables_sha,
        "gen_ai.usage.input_tokens": usage.get("input_tokens"),
        "gen_ai.usage.output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "cache_write_tokens": usage.get("cache_write_tokens"),
        "cost_usd": usage.get("cost_usd"),
        "num_turns": usage.get("num_turns"),
        "session_id": usage.get("session_id"),
        "duration_api_ms": usage.get("duration_api_ms"),
        "status": status,
        "error.type": error_type,
        "elapsed_s": round(float(elapsed_s), 3),
        "attempts": attempts,
        "tags": dict(tags or {}),
        "work_dir": work_dir,
        "log_file": log_file,
        "transcript_file": transcript_file,
    }


class RunLedger:
    """Append-only JSONL writer plus small readers for spend summaries."""

    def __init__(
        self,
        global_path: Optional[Path] = None,
        relative_path: Path = DEFAULT_RELATIVE_PATH,
        *,
        env: Optional[Mapping[str, str]] = None,
        enabled: bool = True,
    ) -> None:
        env = os.environ if env is None else env
        override = (env.get(LEDGER_ENV_VAR) or "").strip()
        if global_path is None:
            global_path = Path(override) if override else DEFAULT_GLOBAL_PATH
        self.global_path = Path(global_path)
        self.relative_path = Path(relative_path)
        self.enabled = enabled

    @classmethod
    def from_config(cls, config: Optional[Mapping[str, Any]], env: Optional[Mapping[str, str]] = None) -> "RunLedger":
        """Build from the ``ledger:`` block of ``config/agents.yaml``."""
        config = dict(config or {})
        relative = Path(config.get("path") or DEFAULT_RELATIVE_PATH)
        global_path = config.get("global_path")
        env = os.environ if env is None else env
        if global_path and not (env.get(LEDGER_ENV_VAR) or "").strip():
            global_path = Path(global_path)
            if not global_path.is_absolute():
                global_path = PROJECT_ROOT / global_path
        else:
            global_path = None
        return cls(global_path, relative, env=env, enabled=config.get("enabled", True))

    def paths_for(self, work_dir: Optional[Path]) -> List[Path]:
        paths = [self.global_path]
        if work_dir is not None:
            paths.insert(0, Path(work_dir) / self.relative_path)
        return paths

    def record(self, entry: Mapping[str, Any], work_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Append ``entry`` to the per-work-dir and global ledgers.

        Write failures are reported, not raised: a full disk or read-only
        project root must never turn a finished agent run into a failure.
        """
        record = dict(entry)
        if not self.enabled:
            return record
        line = json.dumps(record, sort_keys=True, default=str)
        for path in self.paths_for(work_dir):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                print(f"run ledger: could not write {path}: {exc}")
        return record

    @staticmethod
    def read(path: Path) -> List[Dict[str, Any]]:
        """All records in one ledger file; malformed lines are skipped."""
        path = Path(path)
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    @classmethod
    def summary(cls, source: Path | Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        """Spend per role, provider and day; what ``safety status`` and the daemon read."""
        records = cls.read(source) if isinstance(source, (str, Path)) else list(source)
        per_role: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"runs": 0, "cost_usd": 0.0, "unpriced_runs": 0,
                                                                    "input_tokens": 0, "output_tokens": 0})
        per_provider: Dict[str, float] = defaultdict(float)
        per_day: Dict[str, float] = defaultdict(float)
        total = 0.0
        for rec in records:
            role = str(rec.get("gen_ai.agent.name") or "unknown")
            bucket = per_role[role]
            bucket["runs"] += 1
            bucket["input_tokens"] += int(rec.get("gen_ai.usage.input_tokens") or 0)
            bucket["output_tokens"] += int(rec.get("gen_ai.usage.output_tokens") or 0)
            cost = rec.get("cost_usd")
            if cost is None:
                bucket["unpriced_runs"] += 1
                continue
            bucket["cost_usd"] += float(cost)
            per_provider[str(rec.get("gen_ai.provider.name") or "unknown")] += float(cost)
            per_day[str(rec.get("ts_start") or "")[:10]] += float(cost)
            total += float(cost)
        return {"runs": len(records), "cost_usd": round(total, 6), "per_role": dict(per_role),
                "per_provider": dict(per_provider), "per_day": dict(per_day)}
