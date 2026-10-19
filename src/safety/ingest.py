"""Turn finished jobs into knowledge-base records.

- suite jobs: ``results/<job>/*.json`` (neurico-safety-result/v1) -> ``runs/<run_id>.json``
- NeuriCo jobs: the workspace's ``REPORT.md``, ``results/safety/*.json`` (same schema, written
  by the safety-evals skill) and ``findings/*.yaml`` (agent-authored candidate findings)
  -> ``runs/<run_id>.json`` plus ``findings/<finding_id>.yaml`` with status ``candidate``.

Findings are never created as anything other than ``candidate``; the validation gate
(``validate`` jobs) is the only path to ``reproduced`` / ``confirmed``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.jobs import JobSpec
from safety.kb import KB, PROJECT_ROOT, load_json, load_yaml, save_json, save_yaml, slugify, unique_id, utc_now

FINDING_SCHEMA = "neurico-safety-finding/v1"


def host_workspace_path(kb: KB, workspace: Optional[str]) -> Optional[Path]:
    """Map the container path printed by NeuriCo (/workspaces/<name>) to the host directory."""
    if not workspace:
        return None
    name = Path(workspace).name
    config = load_yaml(PROJECT_ROOT / "config" / "workspace.yaml") or {}
    parent = (config.get("workspace") or {}).get("parent_dir") or str(PROJECT_ROOT / "workspaces")
    candidate = Path(parent) / name
    if candidate.exists():
        return candidate
    direct = Path(workspace)
    return direct if direct.exists() else None


def load_results(results_dir: Path) -> List[Dict[str, Any]]:
    records = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        data = load_json(path)
        if isinstance(data, dict) and data.get("schema", "").startswith("neurico-safety-result"):
            records.append({k: v for k, v in data.items() if k != "per_item"} | {"file": str(path)})
    return records


def new_run_id(kb: KB, spec: JobSpec) -> str:
    existing = [p.stem for p in kb.runs_dir.glob("*.json")]
    return unique_id(f"run-{spec.kind}", existing)


def ingest_suite(kb: KB, spec: JobSpec, runtime: Dict[str, Any]) -> str:
    results_dir = kb.results_dir / spec.id
    records = load_results(results_dir)
    run_id = new_run_id(kb, spec)
    run = {
        "run_id": run_id, "job": spec.id, "kind": spec.kind, "campaign": spec.campaign, "title": spec.title,
        "started": runtime.get("started_at"), "finished": runtime.get("finished_at") or utc_now(),
        "attempts": runtime.get("attempts", 0) + 1, "log_file": runtime.get("log_file"),
        "results_dir": str(results_dir),
        "pairs": [{"eval": r["eval_id"], "model": r["model_id"], "status": r["status"], "n": r.get("n"),
                   "metrics": r.get("metrics"), "judge": r.get("judge"), "duration_s": r.get("duration_s"),
                   "file": r["file"]} for r in records],
        "summary": load_json(results_dir / "summary.json"),
    }
    save_json(kb.runs_dir / f"{run_id}.json", run)
    return run_id


def file_finding(kb: KB, data: Dict[str, Any], *, run_id: str, spec: JobSpec, workspace: Path,
                 source_file: Path) -> str:
    existing = [p.stem for p in kb.findings_dir.glob("*.yaml")]
    finding_id = f"{unique_id('finding', existing)}-{slugify(str(data.get('title', 'untitled')), 32)}"
    record = {
        "schema": FINDING_SCHEMA, "id": finding_id, "title": data.get("title", "untitled"),
        "status": "candidate", "created": utc_now(), "source_run": run_id, "source_job": spec.id,
        "campaign": spec.campaign, "category": data.get("category"), "models": data.get("models") or [],
        "summary": data.get("summary", ""), "evidence": data.get("evidence") or {},
        "reproduction": data.get("reproduction") or {},
        "provenance": {"workspace": str(workspace), "file": str(source_file),
                       "github_url": data.get("github_url")},
        "validation": [], "disclosure": {"state": "internal", "notes": ""},
    }
    save_yaml(kb.findings_dir / f"{finding_id}.yaml", record)
    md = source_file.with_suffix(".md")
    if md.exists():
        shutil.copyfile(md, kb.findings_dir / f"{finding_id}.md")
    return finding_id


def ingest_neurico(kb: KB, spec: JobSpec, runtime: Dict[str, Any]) -> str:
    workspace = host_workspace_path(kb, runtime.get("workspace"))
    run_id = new_run_id(kb, spec)
    run: Dict[str, Any] = {
        "run_id": run_id, "job": spec.id, "kind": spec.kind, "campaign": spec.campaign, "title": spec.title,
        "idea_file": spec.idea_file, "idea_id": runtime.get("idea_id"), "provider": spec.provider,
        "model": spec.model, "started": runtime.get("started_at"),
        "finished": runtime.get("finished_at") or utc_now(), "attempts": runtime.get("attempts", 0) + 1,
        "workspace": str(workspace) if workspace else runtime.get("workspace"),
        "github_url": runtime.get("github_url"), "log_file": runtime.get("log_file"),
        "report": None, "paper": None, "results": [], "findings": [],
    }
    if workspace:
        report = workspace / "REPORT.md"
        run["report"] = str(report) if report.exists() else None
        paper = workspace / "paper_draft" / "main.pdf"
        run["paper"] = str(paper) if paper.exists() else None
        scoring = workspace / "scoring" / "results.json"
        if scoring.exists():
            run["scoring"] = load_json(scoring)
        results_dir = workspace / "results" / "safety"
        if results_dir.exists():
            run["results"] = load_results(results_dir)
        for path in sorted((workspace / "findings").glob("*.yaml")):
            data = load_yaml(path)
            if isinstance(data, dict) and data.get("title"):
                data.setdefault("github_url", runtime.get("github_url"))
                run["findings"].append(file_finding(kb, data, run_id=run_id, spec=spec, workspace=workspace,
                                                    source_file=path))
    save_json(kb.runs_dir / f"{run_id}.json", run)
    return run_id


def ingest_job(kb: KB, spec: JobSpec, runtime: Dict[str, Any]) -> str:
    kb.ensure_layout()
    if spec.kind == "suite":
        return ingest_suite(kb, spec, runtime)
    return ingest_neurico(kb, spec, runtime)
