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
TAGS_ENV_VAR = "NEURICO_AGENT_TAGS"
DEFAULT_RELATIVE_PATH = Path(".neurico") / "agent_runs.jsonl"
DEFAULT_GLOBAL_PATH = PROJECT_ROOT / "logs" / "agent_runs.jsonl"

# Providers whose records bill a lane of their own, whatever the auth field says.
_LANE_PROVIDERS = {"openrouter": "openrouter", "azure_openai": "azure", "azure_foundry": "azure"}


def tags_from_env(env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Tags every launch in this process should carry, from ``NEURICO_AGENT_TAGS``.

    The safety daemon sets ``job_id=<id>,campaign=<name>`` on the environment of
    the ``./neurico`` processes it starts so the records their agents write can be
    found again per job. The value is ``key=value`` pairs separated by commas, or
    a JSON object; keys without a value and malformed input are ignored.
    """
    env = os.environ if env is None else env
    raw = (env.get(TAGS_ENV_VAR) or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    out: Dict[str, str] = {}
    for part in raw.split(","):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def billing_lane(record: Mapping[str, Any]) -> str:
    """Which bill a record lands on: ``openrouter``, ``azure`` or the provider name (oauth lanes)."""
    provider = str(record.get("gen_ai.provider.name") or "unknown")
    if provider in _LANE_PROVIDERS:
        return _LANE_PROVIDERS[provider]
    if str(record.get("auth") or "") == "azure":
        return "azure"
    return provider


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
    def collect(cls, paths: Iterable[Path]) -> List[Dict[str, Any]]:
        """Records from several ledger files, each run once (``run_id`` de-duplicates
        the per-work-dir copy against the global one)."""
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for path in paths:
            for rec in cls.read(Path(path)):
                key = rec.get("run_id") or json.dumps(rec, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                out.append(rec)
        return out

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


def spend(source: Path | Iterable[Mapping[str, Any]], *, day: Optional[str] = None, since: Optional[str] = None,
          until: Optional[str] = None, job_id: Optional[str] = None, campaign: Optional[str] = None,
          role: Optional[str] = None, lane: Optional[str] = None) -> Dict[str, Any]:
    """Cost aggregated by day, role, provider, model, auth lane, billing lane and job.

    ``source`` is a ledger path or records (``RunLedger.collect`` for several files).
    Filters are inclusive ISO dates (``day`` = that date only, ``since``/``until`` a
    range on ``ts_start``) and exact matches on ``tags.job_id``, ``tags.campaign``,
    the role and the billing lane. Records without a cost count in ``runs`` and
    ``unpriced_runs`` but add nothing: a missing price is never a guess.
    """
    records = RunLedger.read(source) if isinstance(source, (str, Path)) else list(source)
    groups: Dict[str, Dict[str, float]] = {k: defaultdict(float) for k in
                                           ("day", "role", "provider", "model", "auth", "lane", "job")}
    total = runs = unpriced = 0.0
    for rec in records:
        stamp = str(rec.get("ts_start") or "")[:10]
        tags = rec.get("tags") or {}
        if day and stamp != day:
            continue
        if since and stamp < since:
            continue
        if until and stamp > until:
            continue
        if job_id and str(tags.get("job_id") or "") != job_id:
            continue
        if campaign and str(tags.get("campaign") or "") != campaign:
            continue
        rec_role = str(rec.get("gen_ai.agent.name") or "unknown")
        rec_lane = billing_lane(rec)
        if role and rec_role != role:
            continue
        if lane and rec_lane != lane:
            continue
        runs += 1
        cost = rec.get("cost_usd")
        if cost is None:
            unpriced += 1
            continue
        cost = float(cost)
        total += cost
        groups["day"][stamp or "unknown"] += cost
        groups["role"][rec_role] += cost
        groups["provider"][str(rec.get("gen_ai.provider.name") or "unknown")] += cost
        groups["model"][str(rec.get("gen_ai.response.model") or rec.get("gen_ai.request.model") or "unknown")] += cost
        groups["auth"][str(rec.get("auth") or "unknown")] += cost
        groups["lane"][rec_lane] += cost
        groups["job"][str(tags.get("job_id") or "-")] += cost
    return {
        "cost_usd": round(total, 6), "runs": int(runs), "unpriced_runs": int(unpriced),
        **{f"by_{name}": {k: round(v, 6) for k, v in sorted(bucket.items())} for name, bucket in groups.items()},
    }
