"""Deterministic orchestration of one ideation round: context -> problem -> ideation -> idea_judge.

Layout for planner run ``<run>``:

    safety_kb/queue/proposals/<run>/ideation/   committed stage outputs: findings.json, registry_snapshot.json,
                                                dedup_candidates.json, context/*.md, problem.json, ideas.json,
                                                ideas_ranked.json, <stage>.notes.md, <stage>.kb_queries.jsonl
    safety_kb/queue/proposals/<run>/            <n>-<slug>.yaml job specs + planning_log.md (to_job), outcome.yaml (planner)
    safety_kb/queue/ideas/<run>-<slug>.yaml     the NeuriCo idea files (to_job)
    logs/safety/ideation/<run>/workspaces/<stage>/   one isolated workspace per agent stage: read-only input/,
                                                schemas/, tools/ (kb.py, scholar_search.py), AGENTS.md, the stage
                                                skill, input/kb.sqlite (a snapshot that hides this round's own ids)
    logs/safety/ideation/<run>/logs/            <stage>_prompt.txt, <stage>.log, <stage>_transcript.jsonl per attempt
    logs/safety/ideation/<run>/events.jsonl     append-only audit log (events.EventLog)

Each agent stage is one ``core.agent_factory`` launch of the role ``ideation.<stage>``
(config/agents.yaml): the factory owns retries (three attempts on crashes, one more on an invalid
artifact with the validator's message appended to the prompt), the JSON-schema check, the
cross-check (``_check_problem`` / ``_check_ideas`` / ``_check_ranked`` below), usage, cost, the
hard budget and the ledger line. This module owns the workspace, the artifacts, the events and the
hand-off to ``to_job``; ``safety.planner.run_planner`` then runs ``validate_proposals`` as for
every planner round.

Ported from sai-review ``src/sai_digest/runtime.py`` (see ``NOTICE.md``); the manifest/resume
machinery, the Codex runner, the KB sync and the digest stages were not.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from safety.kb import KB, PROJECT_ROOT
from safety import kbdb

from . import context as context_mod
from . import to_job
from .events import EventLog, sha256_bytes, sha256_file, utc_now
from .stages import AGENT_STAGE_IDS, CONTEXT_ARTIFACTS, STAGE_BY_ID, STAGES, Stage, artifact_name
from .writing_rules import IDEA_METHOD_JACCARD_MAX, check_detail_caps, method_overlaps

PKG = Path(__file__).resolve().parent
SCHEMAS_DIR = PKG / "schemas"
TEMPLATES_DIR = PROJECT_ROOT / "templates" / "ideation"
SKILLS_DIR = TEMPLATES_DIR / "skills"
AGENTS_MD_PATH = TEMPLATES_DIR / "AGENTS.md"
STAGE_PROMPT_PATH = TEMPLATES_DIR / "stage_prompt.md"
SCHOLAR_TOOL_PATH = PROJECT_ROOT / "templates" / "skills" / "safety-kb" / "scripts" / "scholar_search.py"
KB_QUERIES_FILE = "output/kb_queries.jsonl"
NOTES_FILE = "output/notes.md"
# Section of output/notes.md reserved for the agent's KB query notes; any other content in that
# file is treated as a suspicious-input report.
NOTES_KB_HEADING = "knowledge base"
MIN_AXES = 3


class StageFailure(RuntimeError):
    def __init__(self, stage_id: str, message: str):
        super().__init__(f"stage {stage_id}: {message}")
        self.stage_id = stage_id


class BudgetExceeded(StageFailure):
    pass


# -- prompts -----------------------------------------------------------------------------------------

def workspace_agents_md() -> str:
    return AGENTS_MD_PATH.read_text(encoding="utf-8")


def skill_path(skill: str) -> Path:
    return SKILLS_DIR / f"{skill}.md"


def stage_prompt(stage: Stage, *, planner_run: str, campaign_name: str, date: Optional[str] = None) -> str:
    """The task prompt for one stage; a validation retry gets the factory's rejection appended."""
    text = STAGE_PROMPT_PATH.read_text(encoding="utf-8")
    fields = {"skill": stage.skill, "stage": stage.id, "planner_run": planner_run, "campaign": campaign_name,
              "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
              "output": stage.outputs[0][0] if stage.outputs else "output/",
              "schema": stage.outputs[0][1] if stage.outputs and stage.outputs[0][1] else ""}
    for key, value in fields.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def prompt_version(skill: str) -> str:
    """Content-addressed prompt version: the skill file plus the shared workspace prompts."""
    ws = sha256_bytes(AGENTS_MD_PATH.read_bytes() + b"\0" + STAGE_PROMPT_PATH.read_bytes())
    return f"{skill}@{sha256_file(skill_path(skill))[:12]} ws@{ws[:12]}"


def notes_flag_suspicious(text: str) -> bool:
    """True when ``output/notes.md`` holds anything outside a ``## Knowledge base ...`` section."""
    section_is_kb = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            section_is_kb = NOTES_KB_HEADING in stripped.lstrip("#").strip().lower()
            continue
        if stripped and not section_is_kb:
            return True
    return False


def default_planner_run() -> str:
    return datetime.now(timezone.utc).strftime("plan-%Y%m%d-%H%M%S-ideate")


# -- the run -------------------------------------------------------------------------------------------

class IdeationRun:
    """One ideation round for one campaign. See the module docstring for the layout."""

    def __init__(self, kb: KB, campaign_name: str, *, planner_run: Optional[str] = None,
                 provider: Optional[str] = None, model: Optional[str] = None, agent_auth: Optional[str] = None,
                 timeout: Optional[int] = None, only: Optional[List[str]] = None, dry_run: bool = False,
                 factory: Any = None, run_root: Optional[Path] = None, max_jobs: Optional[int] = None):
        self.kb = kb
        self.campaign_name = campaign_name
        self.campaign = kb.campaign(campaign_name)
        self.planner_run = planner_run or default_planner_run()
        self.provider, self.model, self.agent_auth, self.timeout = provider, model, agent_auth, timeout
        self.only: Set[str] = set(only or [])
        unknown = self.only - set(AGENT_STAGE_IDS)
        if unknown:
            raise ValueError(f"unknown stage(s) {sorted(unknown)}; agent stages are {AGENT_STAGE_IDS}")
        self.dry_run = dry_run
        self.max_jobs = max_jobs
        self._factory = factory
        self.proposal_dir = kb.queue_dir / "proposals" / self.planner_run
        self.artifacts = self.proposal_dir / "ideation"
        self.root = Path(run_root) if run_root else kb.logs_dir / "ideation" / self.planner_run
        self.workspaces = self.root / "workspaces"
        self.logs = self.root / "logs"
        self.events = EventLog(self.root / "events.jsonl")
        self.steps: Dict[str, Dict[str, Any]] = {}
        self.warnings: List[str] = []

    # -- plumbing --------------------------------------------------------------------------------------
    @property
    def factory(self):
        if self._factory is None:
            from core.agent_factory import AgentFactory
            self._factory = AgentFactory()
        return self._factory

    def _warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)
        self.events.append(run_id=self.planner_run, actor="system:ideation", action="warning", target=text[:200])

    def _spec_overrides(self, stage: Stage) -> Dict[str, Any]:
        overrides: Dict[str, Any] = {"provider": self.provider, "model": self.model, "auth": self.agent_auth,
                                     "transcript": {"logs_dir": self.logs, "stem": stage.id, "save_prompt": True}}
        if self.timeout is not None:
            overrides["timeout"] = self.timeout   # 0 = no limit; None keeps the role's budget (no limit unless configured)
        return overrides

    def _actor(self, spec: Any) -> str:
        return f"{getattr(spec, 'provider', 'agent')}:{getattr(spec, 'model', None) or 'default'}@{getattr(spec, 'auth', '-')}"

    def _outputs_present(self, stage: Stage) -> bool:
        if stage.kind == "code":
            return all((self.artifacts / n).exists() for n in CONTEXT_ARTIFACTS)
        return all((self.artifacts / artifact_name(src)).exists() for src, _ in stage.outputs)

    def _selected(self, stage: Stage) -> bool:
        if stage.kind == "code":
            return not self.only or not self._outputs_present(stage)
        return not self.only or stage.id in self.only

    # -- run ---------------------------------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        """Run the selected stages in order; returns the round summary. Raises StageFailure (or
        BudgetExceeded) after a stage's retries are exhausted."""
        for d in (self.artifacts, self.workspaces, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        self.events.append(run_id=self.planner_run, actor="system:ideation", action="run.started",
                           target=str(self.root), detail={"campaign": self.campaign_name, "only": sorted(self.only),
                                                          "dry_run": self.dry_run, "provider": self.provider,
                                                          "model": self.model})
        t0 = time.monotonic()
        proposals: Optional[Dict[str, Any]] = None
        try:
            for stage in STAGES:
                if not self._selected(stage):
                    self._skip(stage, "not selected" if self.only else "already complete")
                    continue
                if self.dry_run and stage.kind == "agent":
                    self._dry_run_stage(stage)
                    break
                self._step(stage)
            if not self.dry_run and (self.artifacts / "ideas_ranked.json").exists() and \
                    (not self.only or "idea_judge" in self.only):
                proposals = to_job.write_proposals(self.kb, self.campaign, self.planner_run, self.artifacts,
                                                   max_jobs=self.max_jobs)
                for w in proposals["written"]:
                    self.events.append(run_id=self.planner_run, actor="system:ideation", action="job.proposed",
                                       target=w["proposal"], detail=w)
        except BudgetExceeded as exc:
            self.events.append(run_id=self.planner_run, actor="system:ideation", action="run.failed",
                               target=str(self.root), detail={"error": str(exc)[:500], "status": "budget_exceeded"})
            raise
        except Exception as exc:
            self.events.append(run_id=self.planner_run, actor="system:ideation", action="run.failed",
                               target=str(self.root), detail={"error": str(exc)[:500]})
            raise
        summary = self.summary(proposals, seconds=round(time.monotonic() - t0, 1))
        self.events.append(run_id=self.planner_run, actor="system:ideation", action="run.finished",
                           target=str(self.root), detail={"cost_usd": summary["cost_usd"], "seconds": summary["seconds"],
                                                          "proposed": len((proposals or {}).get("written", []))})
        (self.artifacts / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
        return summary

    def summary(self, proposals: Optional[Dict[str, Any]] = None, *, seconds: float = 0.0) -> Dict[str, Any]:
        cost = sum(float(s.get("cost_usd") or 0.0) for s in self.steps.values())
        priced = any(s.get("cost_usd") is not None for s in self.steps.values())
        return {"ok": all(s.get("status") in ("ok", "skipped", "dry_run") for s in self.steps.values()),
                "planner_run": self.planner_run, "mode": "ideate", "campaign": self.campaign_name,
                "dry_run": self.dry_run, "proposal_dir": str(self.proposal_dir), "artifacts": str(self.artifacts),
                "run_root": str(self.root), "steps": self.steps, "cost_usd": round(cost, 4) if priced else None,
                "agent_run_ids": [s["run_id"] for s in self.steps.values() if s.get("run_id")],
                "warnings": list(self.warnings), "proposals": proposals, "seconds": seconds}

    def _skip(self, stage: Stage, reason: str) -> None:
        self.steps[stage.id] = {"status": "skipped", "reason": reason}
        self.events.append(run_id=self.planner_run, step=stage.id, actor="system:ideation", action="step.skipped",
                           target=stage.id, detail={"reason": reason})

    def _step(self, stage: Stage) -> None:
        for dep_id in stage.after:
            if not self._outputs_present(STAGE_BY_ID[dep_id]):
                raise StageFailure(stage.id, f"upstream stage {dep_id!r} has no outputs in {self.artifacts}")
        pv = prompt_version(stage.skill) if stage.kind == "agent" else None
        self.steps[stage.id] = {"status": "running", "started_at": utc_now(), "prompt_version": pv}
        self.events.append(run_id=self.planner_run, step=stage.id, actor="system:ideation", action="step.started",
                           target=stage.id, detail={"prompt_version": pv} if pv else None)
        t0 = time.monotonic()
        try:
            outputs, extra = (self._run_context(), {}) if stage.kind == "code" else self._run_agent_stage(stage)
        except Exception as exc:
            self.steps[stage.id].update(status="failed", error=str(exc)[:1000], seconds=round(time.monotonic() - t0, 1))
            self.events.append(run_id=self.planner_run, step=stage.id, actor="system:ideation", action="step.failed",
                               target=stage.id, detail={"error": str(exc)[:500], "prompt_version": pv})
            raise
        hashes = {str(p.relative_to(self.artifacts)): sha256_file(p) for p in outputs}
        self.steps[stage.id].update(status="ok", seconds=round(time.monotonic() - t0, 1), outputs=sorted(hashes), **extra)
        for rel, digest in hashes.items():
            self.events.append(run_id=self.planner_run, step=stage.id, actor=extra.get("actor", "system:ideation"),
                               action="artifact.written", target=rel, outputs_sha256={rel: digest})
        self.events.append(run_id=self.planner_run, step=stage.id, actor=extra.get("actor", "system:ideation"),
                           action="step.finished", target=stage.id, outputs_sha256=hashes,
                           detail={k: extra.get(k) for k in ("attempts", "cost_usd", "run_id", "usage", "model")},
                           session_id=extra.get("session_id"))

    # -- code stage -----------------------------------------------------------------------------------------
    def _run_context(self) -> List[Path]:
        return context_mod.write_context(self.kb, self.campaign_name, self.artifacts, planner_run=self.planner_run)

    # -- agent stages -----------------------------------------------------------------------------------------
    def _dry_run_stage(self, stage: Stage) -> None:
        """Stage the workspace and save the prompt without launching an agent."""
        workspace = self.workspaces / stage.id
        spec = self.factory.spec(stage.role, **self._spec_overrides(stage))
        self._prepare_workspace(workspace, stage, provider=spec.provider)
        prompt = stage_prompt(stage, planner_run=self.planner_run, campaign_name=self.campaign_name)
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        (self.proposal_dir / "prompt.md").write_text(
            f"<!-- dry run: stage {stage.id}, workspace {workspace} -->\n\n{prompt}", encoding="utf-8")
        self.steps[stage.id] = {"status": "dry_run", "workspace": str(workspace), "prompt_version": prompt_version(stage.skill)}
        self.events.append(run_id=self.planner_run, step=stage.id, actor="system:ideation", action="step.skipped",
                           target=stage.id, detail={"reason": "dry run", "workspace": str(workspace)})

    def _run_agent_stage(self, stage: Stage):
        from core.agent_factory import BudgetExceeded as FactoryBudgetExceeded

        workspace = self.workspaces / stage.id
        spec = self.factory.spec(stage.role, **self._spec_overrides(stage))
        self._prepare_workspace(workspace, stage, provider=spec.provider)
        env_extra = {"NEURICO_SAFETY_KB": str(workspace / "input"),
                     "NEURICO_KB_QUERY_LOG": str(workspace / KB_QUERIES_FILE)}
        handle = self.factory.build(spec, env_extra)
        prompt = stage_prompt(stage, planner_run=self.planner_run, campaign_name=self.campaign_name)
        actor = self._actor(spec)
        try:
            result = self.factory.run(handle, prompt, workspace, ledger_dir=self.kb.root)
        except FactoryBudgetExceeded as exc:
            raise BudgetExceeded(stage.id, str(exc)) from exc
        usage = result.usage.as_dict() if hasattr(result.usage, "as_dict") else dict(result.usage or {})
        extra = {"actor": actor, "attempts": result.attempts, "run_id": result.run_id, "cost_usd": usage.get("cost_usd"),
                 "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens")},
                 "session_id": usage.get("session_id"), "model": usage.get("model") or spec.model,
                 "provider": spec.provider, "auth": spec.auth, "log": str(result.log_file),
                 "workspace": str(workspace), "agent_status": result.status}
        if not result.success:
            detail = "; ".join(result.issues)[:800] if result.issues else result.status
            self.steps[stage.id].update(extra)
            raise StageFailure(stage.id, f"{result.status} after {result.attempts} attempt(s): {detail}")
        return self._commit_outputs(workspace, stage), extra

    def _prepare_workspace(self, workspace: Path, stage: Stage, *, provider: str = "codex") -> None:
        if workspace.exists():
            for p in workspace.rglob("*"):
                if p.is_file() and not (p.stat().st_mode & 0o200):
                    p.chmod(0o644)
            shutil.rmtree(workspace)
        (workspace / "input").mkdir(parents=True)
        (workspace / "scratch").mkdir()
        (workspace / "output").mkdir()
        agents_md = workspace_agents_md()
        (workspace / "AGENTS.md").write_text(agents_md, encoding="utf-8")
        (workspace / "CLAUDE.md").write_text(agents_md, encoding="utf-8")
        from core.agent_cli import provider_skill_root
        # Codex reads .agents/skills/<name>/SKILL.md, Claude Code .claude/skills/<name>/SKILL.md; stage both.
        for root in {workspace / ".agents" / "skills", workspace / provider_skill_root(provider)}:
            dst = root / stage.skill
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_path(stage.skill), dst / "SKILL.md")
        tools = workspace / "tools"
        tools.mkdir()
        shutil.copy2(kbdb.TOOL_PATH, tools / "kb.py")
        shutil.copy2(SCHOLAR_TOOL_PATH, tools / "scholar_search.py")
        for _, schema_name in stage.outputs:
            if schema_name:
                dst = workspace / "schemas" / schema_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SCHEMAS_DIR / schema_name, dst)
        for artifact, target in stage.inputs:
            src = self.artifacts / artifact
            if not src.exists():
                raise StageFailure(stage.id, f"missing input artifact {artifact}")
            dst = workspace / target
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            dst.chmod(0o444)
        kbdb.snapshot_to(self.kb, workspace / "input" / "kb.sqlite",
                         exclude_ids=context_mod.own_round_ids(self.kb, self.planner_run))
        (workspace / "PROMPT_VERSION").write_text(prompt_version(stage.skill) + "\n", encoding="utf-8")

    def _commit_outputs(self, workspace: Path, stage: Stage) -> List[Path]:
        out: List[Path] = []
        for source, _ in stage.outputs:
            dst = self.artifacts / artifact_name(source)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / source, dst)
            out.append(dst)
        notes = workspace / NOTES_FILE
        if notes.exists() and notes.stat().st_size:
            dst = self.artifacts / f"{stage.id}.notes.md"
            shutil.copy2(notes, dst)
            out.append(dst)
            if notes_flag_suspicious(notes.read_text(encoding="utf-8", errors="replace")):
                self._warn(f"stage {stage.id} reported suspicious input in {dst.relative_to(self.kb.root)}")
        queries = workspace / KB_QUERIES_FILE
        if queries.exists() and queries.stat().st_size:
            dst = self.artifacts / f"{stage.id}.kb_queries.jsonl"
            shutil.copy2(queries, dst)
            out.append(dst)
        else:
            self._warn(f"stage {stage.id} ran no knowledge-base query (a novelty verdict with no query behind it is a guess)")
        return out


# -- cross-checks (referenced from config/agents.yaml as ideation.runtime:_check_*) ----------------------------
# Signature ``check(data, workspace)``: the factory calls them after the schema passed; raise ValueError
# with a message the agent can act on. ``workspace`` is the stage workspace (inputs under input/).

def _caps(stage_id: str, data: Dict[str, Any]) -> None:
    errs = check_detail_caps(stage_id, data)
    if errs:
        raise ValueError(f"{len(errs)} writing-rule violation(s): " + "; ".join(errs[:10]))


def _check_problem(data: Dict[str, Any], workspace: Path) -> None:
    _caps("problem", data)
    ids = context_mod.feed_ids(Path(workspace))
    bad = [e for e in data["evidence_ids"] if e not in ids]
    if bad:
        raise ValueError(f"problem cites ids that are not in input/findings.json: {bad}")


def _check_ideas(data: Dict[str, Any], workspace: Path) -> None:
    _caps("ideation", data)
    ids = context_mod.feed_ids(Path(workspace))
    axes = {i["axis"] for i in data["ideas"]}
    if len(axes) < MIN_AXES:
        raise ValueError(f"ideas span only {len(axes)} axes (need >= {MIN_AXES}): {sorted(axes)}")
    for idea in data["ideas"]:
        bad = [b for b in idea["builds_on"] if b not in ids]
        if bad:
            raise ValueError(f"{idea['id']} builds_on ids that are not in input/findings.json: {bad}")
        n = idea.get("neurico") or {}
        kind = n.get("job_kind")
        if kind == "validate" and not n.get("finding_id"):
            raise ValueError(f"{idea['id']}: job_kind validate needs neurico.finding_id")
        if kind == "optimise" and not n.get("evaluation"):
            raise ValueError(f"{idea['id']}: job_kind optimise needs neurico.evaluation (the sealed metric)")
        if n.get("finding_id") and f"finding:{n['finding_id']}" not in ids and n["finding_id"] not in ids:
            raise ValueError(f"{idea['id']}: finding_id {n['finding_id']} is not a finding in input/findings.json")
    dupes = method_overlaps(data["ideas"])
    if dupes:
        shown = ", ".join(f"{a}~{b} ({j})" for a, b, j in dupes[:8])
        raise ValueError(
            f"{len(dupes)} idea pair(s) share the same experimental scaffold (method Jaccard > "
            f"{IDEA_METHOD_JACCARD_MAX}): {shown}. Ideas must differ in mechanism, measurement "
            "or intervention; rewrite the overlapping ones as genuinely different experiments, "
            "not variants of one design")


def _check_ranked(data: Dict[str, Any], workspace: Path) -> None:
    _caps("idea_judge", data)
    ideas_path = Path(workspace) / "input" / "ideas.json"
    if not ideas_path.exists():
        ideas_path = Path(workspace) / "ideas.json"
    ideas = json.loads(ideas_path.read_text(encoding="utf-8"))
    known = {i["id"] for i in ideas["ideas"]}
    scored = {s["idea_id"] for s in data["scored"]}
    if scored != known:
        raise ValueError(f"judge scored {sorted(scored)} but the ideas are {sorted(known)}; score every idea once")
    by_id = {s["idea_id"]: s for s in data["scored"]}
    top_ids = [t["idea_id"] for t in data["top"]]
    for t in data["top"]:
        if t["idea_id"] not in known:
            raise ValueError(f"top idea {t['idea_id']} is not a known idea")
        reasons = [r for r in by_id[t["idea_id"]].get("reject_reasons", []) if r != "none"]
        if reasons:
            raise ValueError(f"top idea {t['idea_id']} carries reject reasons {reasons}; "
                             "an idea with a reject reason cannot be in top")
    ranks = [t["rank"] for t in data["top"]]
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise ValueError(f"top ranks must be 1..n, got {ranks}")
    for tid in top_ids:
        for sib in by_id[tid].get("sibling_of", []) or []:
            if sib in top_ids:
                raise ValueError(f"top contains sibling ideas {tid} and {sib} (same experimental scaffold); keep one")
    for s in data["scored"]:
        if "duplicates_sibling" in (s.get("reject_reasons") or []) and not s.get("sibling_of"):
            raise ValueError(f"{s['idea_id']} is rejected as duplicates_sibling but names no sibling_of")
