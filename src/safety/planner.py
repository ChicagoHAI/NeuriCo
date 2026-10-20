"""Planner agent: proposes new jobs from the knowledge base.

The planner is a coding-agent session (Claude Code or Codex, launched with the same
machinery as NeuriCo's other agents) that runs with the knowledge base as its
working directory. It reads the campaign, catalogs, findings, run history and inbox,
and writes:

- ``queue/proposals/<planner_run>/*.yaml``  job specs (see safety.jobs.JobSpec.to_dict)
- ``queue/ideas/<id>.yaml``                 NeuriCo idea YAMLs for research/optimise/explore jobs
- ``queue/proposals/<planner_run>/planning_log.md``  rationale, triage of inbox items

Python then validates every proposal (schema, catalog ids, de-duplication against
existing jobs, campaign policy) and moves the accepted ones to ``queue/pending/``
with ``approved`` set according to the campaign's approval policy.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.jobs import JobSpec, Queue
from safety.kb import KB, PROJECT_ROOT, load_yaml, save_yaml, utc_now

TEMPLATES = {
    "replicate": PROJECT_ROOT / "templates" / "agents" / "safety_planner.txt",
    "ideate": PROJECT_ROOT / "templates" / "agents" / "safety_ideator.txt",
}
TEMPLATE = TEMPLATES["replicate"]
PLANNER_MODES = tuple(TEMPLATES)
MAX_CHARS = {"campaign": 6000, "catalog_evals": 12000, "catalog_models": 6000, "findings": 8000,
             "runs": 10000, "inbox": 8000, "jobs": 6000, "gaps": 12000}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _read(path: Path, limit: int) -> str:
    return _clip(path.read_text(encoding="utf-8", errors="replace"), limit) if path.exists() else "(none)"


def build_context(kb: KB, campaign_name: str) -> Dict[str, str]:
    queue = Queue(kb)
    jobs_lines = []
    for state in ("running", "pending", "done", "failed"):
        for spec in queue.list(state):
            jobs_lines.append(f"- [{state}] {spec.id} ({spec.kind}): {spec.title}")
    runs_lines = []
    for run in sorted(kb.list_runs(), key=lambda r: r.get("finished") or "", reverse=True)[:40]:
        pairs = run.get("pairs") or []
        summary = "; ".join(f"{p.get('eval')}x{p.get('model')}={p.get('metrics')}" for p in pairs[:6])
        runs_lines.append(f"- {run['run_id']} [{run.get('kind')}] {run.get('title')} -> "
                          f"{run.get('github_url') or run.get('workspace') or ''} {summary}")
    findings_lines = [f"- {f['id']} [{f.get('status')}] {f.get('title')} models={f.get('models')}"
                      for f in kb.list_findings()]
    inbox_lines = [f"- {p.name}: {p.read_text(encoding='utf-8', errors='replace')[:300].strip()}"
                   for p in sorted(kb.inbox_dir.glob('*.md'))[:30]]
    gaps = ""
    for path in sorted((kb.root / "gaps").glob("*.md")):
        gaps += f"\n### {path.name}\n" + path.read_text(encoding="utf-8", errors="replace")[:4000]
    return {
        "campaign": _read(kb.campaigns_dir / f"{campaign_name}.yaml", MAX_CHARS["campaign"]),
        "catalog_evals": _read(kb.catalog_dir / "evals.yaml", MAX_CHARS["catalog_evals"]),
        "catalog_models": _read(kb.catalog_dir / "models.yaml", MAX_CHARS["catalog_models"]),
        "findings": _clip("\n".join(findings_lines) or "(none)", MAX_CHARS["findings"]),
        "runs": _clip("\n".join(runs_lines) or "(none)", MAX_CHARS["runs"]),
        "inbox": _clip("\n".join(inbox_lines) or "(none)", MAX_CHARS["inbox"]),
        "jobs": _clip("\n".join(jobs_lines) or "(none)", MAX_CHARS["jobs"]),
        "gaps": _clip(gaps or "(none)", MAX_CHARS["gaps"]),
    }


def choose_mode(kb: KB, campaign: Dict[str, Any]) -> str:
    """Pick the next planner mode from the campaign's `planner.modes` weights, round-robin.

    The sequence is derived from past rounds (queue/proposals/*/outcome.yaml) so the mix holds
    over time, e.g. {ideate: 0.6, replicate: 0.4} -> ideate, replicate, ideate, ideate, replicate...
    """
    weights = (campaign.get("planner") or {}).get("modes") or {"replicate": 1.0}
    weights = {m: float(w) for m, w in weights.items() if m in PLANNER_MODES and float(w) > 0} or {"replicate": 1.0}
    done: Dict[str, int] = {m: 0 for m in weights}
    for outcome in (kb.queue_dir / "proposals").glob("*/outcome.yaml"):
        mode = (load_yaml(outcome) or {}).get("mode", "replicate")
        if mode in done:
            done[mode] += 1
    total = sum(done.values()) + 1
    # the mode furthest below its target share goes next
    return max(weights, key=lambda m: weights[m] / sum(weights.values()) - done[m] / total)


def render_prompt(kb: KB, campaign_name: str, planner_run: str, mode: str = "replicate") -> str:
    template = TEMPLATES[mode].read_text(encoding="utf-8")
    context = build_context(kb, campaign_name)
    campaign = kb.campaign(campaign_name)
    context.update({"planner_run": planner_run, "kb_root": str(kb.root), "campaign_name": campaign_name,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "max_new_jobs": str((campaign.get("planner") or {}).get("max_new_jobs_per_run", 3))})
    for key, value in context.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def validate_proposals(kb: KB, campaign: Dict[str, Any], proposal_dir: Path, mode: str = "replicate") -> Dict[str, Any]:
    queue = Queue(kb)
    evals, models = kb.evals(), kb.models()
    existing = {queue.signature(spec) for state in ("pending", "running", "done")
                for spec in queue.list(state)}
    policy = (campaign.get("planner") or {}).get("approval", "human")
    max_new = int((campaign.get("planner") or {}).get("max_new_jobs_per_run", 3))
    accepted, rejected = [], []
    for path in sorted(proposal_dir.glob("*.yaml")):
        data = load_yaml(path)
        if not isinstance(data, dict) or "kind" not in data:
            rejected.append((path.name, "not a job spec"))
            continue
        data.setdefault("id", queue.new_id(data["kind"], data.get("title", path.stem)))
        data["created_by"] = "planner"
        data.setdefault("campaign", campaign.get("name"))
        # Campaign-level agent defaults (backbone provider/model/auth) apply unless the proposal sets them.
        defaults = (campaign.get("defaults") or {}).get("neurico") or {}
        if data.get("kind") != "suite" and defaults:
            neurico = data.setdefault("neurico", {})
            for key, value in defaults.items():
                if neurico.get(key) in (None, "", "claude") and key in ("provider", "model", "agent_auth"):
                    neurico[key] = value
                elif key not in neurico:
                    neurico[key] = value
        # Ideation metadata travels with the job (novelty argument, pre-registered criterion).
        extra = data.setdefault("extra", {})
        for key in ("novelty", "finding_criterion", "rationale"):
            if data.get(key) and key != "rationale":
                extra[key] = data.pop(key)
        extra.setdefault("planner_run", proposal_dir.name)
        extra.setdefault("planner_mode", mode)
        try:
            spec = JobSpec.from_dict(data)
        except Exception as e:  # noqa: BLE001
            rejected.append((path.name, f"invalid: {e}"))
            continue
        if spec.kind == "suite":
            unknown = [e for e in spec.evals if e not in evals] + [m for m in spec.models if m not in models]
            if unknown:
                rejected.append((path.name, f"unknown catalog ids {unknown}"))
                continue
            if spec.gpu_memory_gb <= 0:
                spec.gpu_memory_gb = max(float(models[m].get("gpu_memory_gb", 0)) for m in spec.models)
        else:
            idea = PROJECT_ROOT / spec.idea_file if spec.idea_file else None
            if not idea or not idea.exists():
                rejected.append((path.name, f"idea file missing: {spec.idea_file}"))
                continue
            if not (load_yaml(idea) or {}).get("idea", {}).get("hypothesis"):
                rejected.append((path.name, "idea file has no idea.hypothesis"))
                continue
        if queue.signature(spec) in existing:
            rejected.append((path.name, "duplicate of an existing job"))
            continue
        if len(accepted) >= max_new:
            rejected.append((path.name, f"over max_new_jobs_per_run={max_new}"))
            continue
        spec.approved = policy == "auto" and not (spec.kind == "explore" and _targets_api_model(spec, models))
        queue.add(spec)
        existing.add(queue.signature(spec))
        accepted.append(spec.id)
    return {"accepted": accepted, "rejected": rejected}


def _targets_api_model(spec: JobSpec, models: Dict[str, Any]) -> bool:
    """True when the idea names an API model as a *subject* (judges do not count)."""
    idea = load_yaml(PROJECT_ROOT / spec.idea_file) if spec.idea_file else None
    text = str(idea).lower() if idea else ""
    return any(m.get("api") and not str(m.get("role", "")).startswith("judge") and m["id"].lower() in text
               for m in models.values())


def run_planner(kb: KB, campaign_name: str, *, provider: str = "claude", model: Optional[str] = None,
                timeout: Optional[int] = 3600, dry_run: bool = False, mode: Optional[str] = None) -> Dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from core.agent_cli import build_agent_command, build_agent_environment
    from core.agent_runner import run_prebuilt_cli_agent

    kb.ensure_layout()
    campaign = kb.campaign(campaign_name)
    mode = mode or choose_mode(kb, campaign)
    if mode not in PLANNER_MODES:
        raise ValueError(f"unknown planner mode {mode!r}; expected one of {PLANNER_MODES}")
    planner_run = datetime.now(timezone.utc).strftime(f"plan-%Y%m%d-%H%M%S-{mode}")
    proposal_dir = kb.queue_dir / "proposals" / planner_run
    proposal_dir.mkdir(parents=True, exist_ok=True)
    prompt = render_prompt(kb, campaign_name, planner_run, mode)
    (proposal_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    if dry_run:
        save_yaml(proposal_dir / "outcome.yaml", {"planner_run": planner_run, "mode": mode, "dry_run": True,
                                                  "at": utc_now(), "campaign": campaign_name, "proposed": 0})
        return {"ok": True, "planner_run": planner_run, "mode": mode, "prompt": str(proposal_dir / "prompt.md"), "proposed": 0}

    log_dir = kb.logs_dir / "planner"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = build_agent_command(provider, full_permissions=True, model=model)
    env = build_agent_environment(provider, {"NEURICO_SAFETY_KB": str(kb.root)})
    result = run_prebuilt_cli_agent(
        command_argv=shlex.split(command), prompt=prompt, work_dir=kb.root,
        log_file=log_dir / f"{planner_run}.log", transcript_file=log_dir / f"{planner_run}_transcript.jsonl",
        env=env, timeout=timeout, provider=provider,
    )
    outcome = validate_proposals(kb, campaign, proposal_dir, mode)
    record = {"ok": bool(result.get("success", True)), "planner_run": planner_run, "mode": mode, "at": utc_now(),
              "campaign": campaign_name, "proposed": len(outcome["accepted"]), "accepted": outcome["accepted"],
              "rejected": outcome["rejected"], "log": str(log_dir / f"{planner_run}.log")}
    save_yaml(proposal_dir / "outcome.yaml", record)
    return record
