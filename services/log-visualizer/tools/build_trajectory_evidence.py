#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path


TEXT_EXTS = {
    ".md", ".txt", ".tex", ".json", ".jsonl", ".yaml", ".yml",
    ".py", ".csv", ".tsv", ".r", ".sql"
}

SKIP_PARTS = {
    ".git", "__pycache__", ".venv", "node_modules",
    ".claude", ".codex", ".gemini",
}

SKIP_CONTAINS = [
    "artifacts/hf_cache/",
    "papers/pages/",
    ".DS_Store",
]

MAX_SNIPPET_CHARS = 900


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace(os.sep, "/")


def should_skip(path: Path, root: Path) -> bool:
    r = rel(path, root)
    parts = set(Path(r).parts)

    if parts & SKIP_PARTS:
        return True

    return any(x in r for x in SKIP_CONTAINS)


def read_snippet(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTS:
        return ""

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_SNIPPET_CHARS]


def classify_artifact(r: str, suffix: str) -> tuple[str, list[str]]:
    low = r.lower()

    # Research idea / task
    if low in {".neurico/idea.yaml", "idea.yaml"} or "idea" in low or "prompt" in low or "task" in low:
        return "task_prompt", ["idea"]

    # Planning / design
    if low.endswith("planning.md") or "plan" in low or low.endswith("paper/outline.md"):
        return "plan", ["idea", "design"]

    # Literature review / external evidence
    if low.endswith("resources.md") or "literature" in low or low.startswith("papers/"):
        if "pages/" in low:
            return "paper_page_chunk", []
        return "literature_evidence", ["review"]

    # Experiment config / design
    if "config" in low or "settings" in low or "baseline" in low or "metric" in low:
        return "experiment_config", ["design"]

    # Source code / implementation
    if suffix in {".py", ".r", ".sql"}:
        # Prefer actual project code dirs. Top-level scripts are okay.
        if low.startswith(("src/", "code/", "scripts/")) or "/" not in low:
            return "source_code", ["design", "experiment"]
        return "support_code", []

    # Results and analysis
    if "result" in low or "summary" in low or "analysis" in low or suffix in {".csv", ".tsv", ".npz", ".png"}:
        return "result_artifact", ["analysis"]

    # Paper/report/final writeup
    if "report" in low or "paper_draft" in low or low.startswith("paper/") or "conclusion" in low or "discussion" in low:
        return "report_artifact", ["interpretation", "report"]

    if suffix == ".pdf":
        return "pdf_artifact", ["review"]

    if suffix in {".md", ".tex"}:
        return "text_artifact", ["interpretation"]

    return "other", []


def build_inventory(raw_run_dir: Path) -> dict:
    artifacts = []
    ignored = defaultdict(int)
    lifecycle = {
        "idea": [],
        "review": [],
        "design": [],
        "experiment": [],
        "analysis": [],
        "interpretation": [],
        "report": [],
    }

    files = sorted([p for p in raw_run_dir.rglob("*") if p.is_file()])

    for path in files:
        r = rel(path, raw_run_dir)
        suffix = path.suffix.lower()

        if should_skip(path, raw_run_dir):
            ignored["skipped_noise"] += 1
            continue

        kind, stages = classify_artifact(r, suffix)

        # Keep only meaningful run artifacts.
        if not stages and kind in {"support_code", "paper_page_chunk", "other"}:
            ignored[kind] += 1
            continue

        item = {
            "artifactId": f"A{len(artifacts) + 1:04d}",
            "path": r,
            "suffix": suffix or "[no_ext]",
            "kind": kind,
            "lifecycleStages": stages,
            "sizeBytes": path.stat().st_size,
            "snippet": read_snippet(path),
        }
        artifacts.append(item)

        for stage in stages:
            lifecycle[stage].append(item)

    lifecycle_summary = {}
    for stage, items in lifecycle.items():
        lifecycle_summary[stage] = {
            "detected": bool(items),
            "artifactCount": len(items),
            "evidence": [
                {
                    "path": x["path"],
                    "kind": x["kind"],
                    "snippet": x["snippet"][:350],
                }
                for x in items[:8]
            ],
        }

    return {
        "schemaVersion": 1,
        "rawRunDir": str(raw_run_dir),
        "artifactCount": len(artifacts),
        "ignoredCounts": dict(ignored),
        "artifactInventory": artifacts,
        "lifecycleEvidence": lifecycle_summary,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-run-dir", required=True)
    ap.add_argument("--vis-run-dir", required=True)
    args = ap.parse_args()

    raw_run_dir = Path(args.raw_run_dir).expanduser().resolve()
    vis_run_dir = Path(args.vis_run_dir).expanduser().resolve()
    canonical_path = vis_run_dir / "canonical_trajectory.json"

    if not raw_run_dir.exists():
        raise SystemExit(f"Raw run dir not found: {raw_run_dir}")
    if not canonical_path.exists():
        raise SystemExit(f"Missing canonical trajectory: {canonical_path}")

    evidence = build_inventory(raw_run_dir)

    out_path = vis_run_dir / "trajectory_evidence.generated.json"
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    data = json.loads(canonical_path.read_text(encoding="utf-8"))
    data["trajectoryEvidence"] = evidence

    backup = canonical_path.with_suffix(".json.bak.before_trajectory_evidence")
    if not backup.exists():
        backup.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    canonical_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"Updated {canonical_path}")
    print()
    print("Lifecycle evidence:")
    for stage, info in evidence["lifecycleEvidence"].items():
        print(f"- {stage}: {info['artifactCount']} artifact(s)")
        for ev in info["evidence"][:3]:
            print(f"    {ev['path']} [{ev['kind']}]")
    print()
    print("Ignored counts:", evidence["ignoredCounts"])


if __name__ == "__main__":
    main()
