#!/usr/bin/env python3
"""
List every run of a scripts/run_methods.py batch with where its outputs are.

Reads the job logs of every batch under logs/batch/ (so it also sees running
jobs, retries and resumed runs), checks each workspace for a paper, and writes
logs/batch/manifest.json.

    scripts/results_manifest.py                 # prints a table
    scripts/results_manifest.py --papers-only   # only runs with a compiled paper
    scripts/results_manifest.py --json          # print the manifest JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from core.config_loader import ConfigLoader  # noqa: E402

LABEL = re.compile(r"^(?P<idea>.+)__(?P<kind>neurico|zero-shot)-(?P<provider>claude|codex)-(?P<model>.+)$")


def build(batch_dirs: list) -> dict:
    """Merge every batch; a later batch's entry for the same idea and method wins."""
    workspaces = ConfigLoader().get_workspace_parent_dir()
    runs: dict = {}
    for batch_dir in batch_dirs:
        status = {}
        status_file = batch_dir / "status.json"
        if status_file.exists():
            for job in json.loads(status_file.read_text())["jobs"]:
                status[Path(job["log_file"]).stem] = job
        for stem in sorted(set(status) | {p.stem for p in batch_dir.glob("*.log") if ".retry" not in p.name}):
            match = LABEL.match(stem)
            if not match:
                continue
            key = (match["idea"], f"{match['kind']}-{match['provider']}-{match['model']}")
            job = status.get(stem, {})
            log = batch_dir / f"{stem}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            retries = sorted(batch_dir.glob(f"{stem}.retry*.log"))
            all_text = text + "".join(r.read_text(encoding="utf-8", errors="replace") for r in retries)
            # "Local:" is /workspaces/<name> in Docker and an absolute host
            # path in host mode; the workspace name is the last component.
            names = re.findall(
                r"(?:Generated repo name: |Resuming workspace: |Local: )(\S+)", text)
            name = Path(names[-1]).name if names else None
            previous = runs.get(key, {})
            if not name and previous.get("workspace"):
                continue  # nothing newer than what an earlier batch recorded
            work_dir = workspaces / name if name else None
            pdf = work_dir / "paper_draft" / "main.pdf" if work_dir else None
            tex = work_dir / "paper_draft" / "main.tex" if work_dir else None
            urls = re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", text)
            state = job.get("state", "unknown")
            has_paper = bool(pdf and pdf.is_file())
            if state == "running":
                outcome = "running"
            elif has_paper:
                outcome = "paper"
            elif state == "pending" or not name:
                outcome = "pending"
            else:
                outcome = "no_paper"
            runs[key] = {
                "idea": match["idea"],
                "method": "neurico" if match["kind"] == "neurico" else "zero-shot",
                "provider": match["provider"],
                "model": match["model"],
                "label": key[1],
                "outcome": outcome,
                "workspace": str(work_dir) if work_dir else None,
                "paper_pdf": str(pdf) if has_paper else None,
                "paper_tex": str(tex) if tex and tex.is_file() else None,
                "github_url": urls[-1] if urls else previous.get("github_url"),
                "batch_log": str(log) if log.is_file() else None,
                "retries": len(retries) + int(job.get("attempts") or 0),
                "resumed": "Resuming workspace:" in text,
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "provider_error": "model is at capacity" in all_text,
            }
    return {
        "batches": [b.name for b in batch_dirs],
        "workspace_root": str(workspaces),
        "runs": sorted(runs.values(), key=lambda r: (r["idea"], r["label"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--papers-only", action="store_true")
    args = parser.parse_args()
    batch_root = PROJECT_ROOT / "logs" / "batch"
    manifest = build(sorted(p for p in batch_root.iterdir() if (p / "status.json").is_file()))
    manifest_file = batch_root / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    runs = [r for r in manifest["runs"] if not args.papers_only or r["outcome"] == "paper"]
    if args.json:
        print(json.dumps({**manifest, "runs": runs}, indent=2))
        return
    for run in runs:
        print(f"{run['outcome']:9} {run['idea']:28} {run['label']:34} {run.get('paper_pdf') or run.get('workspace') or '-'}")
    print(f"\nmanifest: {manifest_file}")


if __name__ == "__main__":
    main()
