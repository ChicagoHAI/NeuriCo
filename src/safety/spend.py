"""Spend: what the engine's agents cost, read back from the run ledgers.

Every agent launch through ``core.agent_factory`` and every ``core.llm_client``
call appends one line to a ledger (``core.run_ledger``): the global
``logs/agent_runs.jsonl`` (shared with the containers through the ``logs``
mount), the per-workspace ``.neurico/agent_runs.jsonl`` and, for the planner,
ideator and scout, ``safety_kb/.neurico/agent_runs.jsonl``. The daemon tags the
processes it starts with ``NEURICO_AGENT_TAGS=job_id=...,campaign=...`` so the
lines can be grouped per job.

This module is the one reader the daemon (budget checks, status), the CLI
(``safety status``), the digest and the knowledge-base index share. Suites run
Inspect directly and do not price their calls; their usage is not in here.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from core.run_ledger import RunLedger, spend
from safety.jobs import JobSpec
from safety.kb import KB, PROJECT_ROOT, load_yaml

CAP_SUFFIX = "_daily_cap_usd"


def today(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def ledger_paths(kb: KB, state: Optional[Mapping[str, Any]] = None,
                 env: Optional[Mapping[str, str]] = None) -> List[Path]:
    """The ledgers that can hold engine spend: global, knowledge base, known job workspaces."""
    env = os.environ if env is None else env
    config = load_yaml(PROJECT_ROOT / "config" / "agents.yaml") or {}
    ledger = RunLedger.from_config(config.get("ledger"), env)
    paths = [ledger.global_path, kb.root / ledger.relative_path]
    if state:
        from safety.ingest import host_workspace_path
        for data in (state.get("jobs") or {}).values():
            workspace = host_workspace_path(kb, (data or {}).get("workspace"))
            if workspace is not None:
                paths.append(workspace / ledger.relative_path)
    out: List[Path] = []
    for path in paths:
        if path not in out:
            out.append(path)
    return out


def records(kb: KB, state: Optional[Mapping[str, Any]] = None,
            env: Optional[Mapping[str, str]] = None) -> List[Dict[str, Any]]:
    return RunLedger.collect(ledger_paths(kb, state, env))


def daily_caps(config: Mapping[str, Any]) -> Dict[str, float]:
    """``{lane: cap}`` from every ``<lane>_daily_cap_usd`` daemon setting that is set."""
    caps: Dict[str, float] = {}
    for key, value in config.items():
        if key.endswith(CAP_SUFFIX) and value is not None:
            try:
                caps[key[: -len(CAP_SUFFIX)]] = float(value)
            except (TypeError, ValueError):
                continue
    return caps


def job_lanes(spec: JobSpec, kb: KB, env: Optional[Mapping[str, str]] = None) -> Set[str]:
    """Billing lanes a job can spend on (``core.run_ledger.billing_lane`` names).

    NeuriCo jobs bill the agent's lane (``azure`` or the provider on OAuth) and
    OpenRouter, which the API roles of ``config/agents.yaml`` (eval verifier, idea
    converter) try first. Suites bill the access schemes of their subject models
    and judges; local vLLM models bill nothing.
    """
    env = os.environ if env is None else env
    if spec.uses_neurico:
        auth = spec.agent_auth or (env.get("NEURICO_AGENT_AUTH") or "oauth").strip().lower()
        return {"azure" if auth == "azure" else spec.provider, "openrouter"}
    lanes: Set[str] = set()
    models, evals = kb.models(), kb.evals()
    entries = [models[m] for m in spec.models if m in models]
    for eval_id in spec.evals:
        judge = (evals.get(eval_id) or {}).get("judge")
        if judge:
            try:
                from safety.suites import judge_entry
                entry = judge_entry(kb, judge)
            except Exception:  # noqa: BLE001 - an unknown judge fails at launch, not here
                entry = None
            if entry:
                entries.append(entry)
    for entry in entries:
        scheme = str(entry.get("access") or "").partition(":")[0]
        if scheme and scheme != "vllm":
            lanes.add(scheme)
    return lanes


def budget_block(spec: JobSpec, ledger: List[Dict[str, Any]], config: Mapping[str, Any], kb: KB, *,
                 day: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Why ``spec`` must not launch now, or None.

    The per-job budget (``resources.api_budget_usd``) compares with every ledger
    line tagged with the job id, so retries and continuations stop once the
    job as a whole has spent it. Daily caps (``<lane>_daily_cap_usd``) compare
    today's spend on each lane the job would bill with.
    """
    if spec.api_budget_usd and spec.api_budget_usd > 0:
        spent = spend(ledger, job_id=spec.id)["cost_usd"]
        if spent >= spec.api_budget_usd:
            return f"job budget: spent ${spent:.2f} of ${spec.api_budget_usd:.2f} (resources.api_budget_usd)"
    caps = daily_caps(config)
    if caps:
        day = day or today()
        for lane in sorted(job_lanes(spec, kb, env) & set(caps)):
            spent = spend(ledger, day=day, lane=lane)["cost_usd"]
            if spent >= caps[lane]:
                return f"daily cap: {lane} spent ${spent:.2f} of ${caps[lane]:.2f} on {day} ({lane}{CAP_SUFFIX})"
    return None


def report(kb: KB, campaign: Optional[str] = None, state: Optional[Mapping[str, Any]] = None, *,
           days: int = 7, env: Optional[Mapping[str, str]] = None,
           ledger: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Today's, the campaign's, the last ``days`` days' and the all-time spend."""
    ledger = records(kb, state, env) if ledger is None else ledger
    day = today()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {
        "generated": day, "ledgers": [str(p) for p in ledger_paths(kb, state, env)],
        "today": spend(ledger, day=day), "recent": spend(ledger, since=since), "recent_days": days,
        "total": spend(ledger),
        "campaign": spend(ledger, campaign=campaign) if campaign else None, "campaign_name": campaign,
    }


def format_report(rep: Mapping[str, Any], *, jobs: int = 10) -> List[str]:
    """Markdown lines for status.md, ``safety status`` and the digest."""
    lines = [f"- today ({rep['generated']}): {_usd_by_lane(rep['today'])}"]
    if rep.get("campaign") is not None:
        lines.append(f"- campaign {rep.get('campaign_name')}: {_usd_by_lane(rep['campaign'])}")
    lines.append(f"- last {rep.get('recent_days', 7)} day(s): {_usd_by_lane(rep['recent'])}")
    lines.append(f"- all ledgers: {_usd_by_lane(rep['total'])}")
    recent = rep["recent"]
    if recent.get("by_role"):
        lines.append("- by role (recent): " + ", ".join(
            f"{k} ${v:.2f}" for k, v in sorted(recent["by_role"].items(), key=lambda kv: -kv[1])))
    by_job = {k: v for k, v in recent.get("by_job", {}).items() if k != "-"}
    if by_job:
        top = sorted(by_job.items(), key=lambda kv: -kv[1])[:jobs]
        lines.append("- by job (recent): " + ", ".join(f"{k} ${v:.2f}" for k, v in top))
    if recent.get("by_day"):
        lines.append("- by day (recent): " + ", ".join(f"{k} ${v:.2f}" for k, v in sorted(recent["by_day"].items())))
    return lines


def _usd_by_lane(block: Mapping[str, Any]) -> str:
    parts = ", ".join(f"{lane} ${usd:.2f}" for lane, usd in sorted(block.get("by_lane", {}).items()))
    unpriced = f", {block['unpriced_runs']} unpriced" if block.get("unpriced_runs") else ""
    return f"${block['cost_usd']:.2f} over {block['runs']} run(s){unpriced}" + (f" [{parts}]" if parts else "")
