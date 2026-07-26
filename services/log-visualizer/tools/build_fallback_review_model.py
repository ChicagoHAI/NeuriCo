#!/usr/bin/env python3
"""Build a deterministic review model when LLM reconstruction fails."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEXT_FILES = [
    "README.md",
    "REPORT.md",
    "planning.md",
    "literature_review.md",
    "resources.md",
    "paper_draft/references.bib",
]
TEXT_GLOBS = [
    "paper_draft/sections/*.tex",
    "results/*.json",
    "src/*.py",
]
FIGURE_GLOBS = ["figures/*"]
SKIP_PARTS = {".gemini", ".claude", ".codex", ".git", "__pycache__", ".venv", "node_modules"}

ISSUE_TEMPLATES = [
    ("hypothesis_validity", "Hypothesis validity", "Check whether the hypothesis is operationalized tightly enough for the reported evidence.", "Method"),
    ("experiment_design", "Experiment design", "Check controls, baselines, sampling, seeds, and whether the design isolates the claimed effect.", "Method"),
    ("statistical_inference", "Statistical inference", "Check significance tests, confidence intervals, multiple comparisons, and effect sizes.", "Results"),
    ("gp_metamodel_assumptions", "GP/metamodel assumptions", "Check surrogate model assumptions, kernel choices, calibration, and extrapolation limits.", "Method"),
    ("sensitivity_sobol", "Sensitivity/Sobol analysis", "Check whether sensitivity analysis supports the causal or robustness interpretation.", "Results"),
    ("uncertainty_estimation", "Uncertainty estimation", "Check whether uncertainty is quantified and propagated into the main conclusions.", "Results"),
    ("result_interpretation", "Result interpretation", "Check whether the stated interpretation follows from the measured outputs.", "Main claim"),
    ("reproducibility", "Reproducibility", "Check scripts, data availability, environment details, random seeds, and rerun instructions.", "Reproducibility"),
    ("main_claim_support", "Main claim support", "Check whether the main claim is directly supported by artifacts and results.", "Main claim"),
    ("abstract_result_consistency", "Abstract/result consistency", "Check whether abstract claims match the reported results and limitations.", "Abstract"),
]
MUST_ANNOTATE_REGIONS = {"Results", "Abstract", "Main claim", "Method", "Reproducibility"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path, limit: int = 120_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[:limit]


def clean(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: limit - 1] + "..." if len(text) > limit else text


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def collect_artifacts(run_dir: Path, data_run_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[Path] = set()

    def add(path: Path, kind: str) -> None:
        if not path.exists() or path.is_dir() or should_skip(path) or path in seen:
            return
        seen.add(path)
        text = "" if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".gif"} else read_text(path, 60_000)
        artifacts.append({
            "path": rel(path, run_dir),
            "kind": kind,
            "size": path.stat().st_size,
            "summary": clean(text, 360) if text else f"{kind} artifact present.",
        })

    for name in TEXT_FILES:
        add(run_dir / name, "document")
    for pattern in TEXT_GLOBS:
        for path in sorted(run_dir.glob(pattern)):
            add(path, "code" if path.suffix == ".py" else "result" if "results" in path.parts else "paper")
    for pattern in FIGURE_GLOBS:
        for path in sorted(run_dir.glob(pattern)):
            add(path, "figure")
    for name in ["canonical_trajectory.json", "evidence_inventory.json", "literature-sources.json"]:
        add(data_run_dir / name, "visualizer_data")
    return artifacts


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def infer_title(run_dir: Path, repo: str) -> str:
    for candidate in ["paper_draft/main.tex", "README.md", "REPORT.md"]:
        text = read_text(run_dir / candidate, 40_000)
        if not text:
            continue
        title = re.search(r"\\title\{([^{}]+)\}", text)
        if title:
            return clean(title.group(1).replace("\\\\", " "), 160)
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if heading:
            return clean(heading.group(1), 160)
    return repo


def evidence_for(artifacts: list[dict[str, Any]], preferred: list[str]) -> list[dict[str, str]]:
    out = []
    for artifact in artifacts:
        path = artifact["path"]
        if any(path == item or path.startswith(item.rstrip("*")) for item in preferred):
            out.append({"path": path, "note": artifact["summary"][:180]})
    if not out and artifacts:
        out.append({"path": artifacts[0]["path"], "note": artifacts[0]["summary"][:180]})
    return out[:4]


def build(repo: str, run_dir: Path, data_run_dir: Path) -> None:
    data_run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = collect_artifacts(run_dir, data_run_dir)
    title = infer_title(run_dir, repo)
    canonical = load_json(data_run_dir / "canonical_trajectory.json", {})
    literature = load_json(data_run_dir / "literature-sources.json", {})
    source_count = int(literature.get("sourceCount") or len(literature.get("sources") or []))

    findings = [
        {
            "id": "F1",
            "kind": "note",
            "text": f"Fallback review model was generated because automated reconstruction failed for {repo}.",
            "insight": "The run is reviewable, but the generated model is conservative and issue-oriented.",
            "evidence": evidence_for(artifacts, ["canonical_trajectory.json", "REPORT.md", "README.md"]),
            "links": [],
        },
        {
            "id": "F2",
            "kind": "note",
            "text": f"Literature extraction found {source_count} run-specific source(s).",
            "insight": "Literature coverage should be reviewed against the main claims.",
            "evidence": evidence_for(artifacts, ["literature-sources.json", "literature_review.md", "resources.md", "paper_draft/references.bib"]),
            "links": [],
        },
    ]

    decisions = []
    review_decisions = []
    for index, (code, title_text, rationale, region) in enumerate(ISSUE_TEMPLATES, start=1):
        did = f"D{index}"
        must_annotate = region in MUST_ANNOTATE_REGIONS
        decisions.append({
            "id": did,
            "phase": "fallback_review",
            "finding": "F1" if index != 2 else "F2",
            "layer": region.lower().replace(" ", "_"),
            "by": "system",
            "question": title_text,
            "chosen": f"Flag {title_text.lower()} for human review.",
            "options": [
                {"text": f"Flag {title_text.lower()} for human review.", "status": "chosen", "source": "fallback"},
                {"text": "Treat as routine.", "status": "alternative", "source": "fallback"},
            ],
            "statedRationale": rationale,
            "shouldEngage": True,
            "mustAnnotate": must_annotate,
            "paperRef": {"region": region},
            "evidence": evidence_for(artifacts, [
                "REPORT.md",
                "paper_draft/sections/",
                "results/",
                "src/",
                "canonical_trajectory.json",
            ]),
        })
        review_decisions.append({
            "decisionId": did,
            "importance": "critical" if must_annotate else "high",
            "importanceRationale": rationale,
            "issueType": code,
            "mustAnnotate": must_annotate,
        })

    world_model = {
        "version": "fallback_world_model_v1",
        "runId": repo,
        "headline": title,
        "abstract": "Deterministic fallback review generated after world-model reconstruction failed.",
        "narrative": f"{title}. This model preserves canonical, literature, and artifact evidence for review without inventing reconstructed causal structure.",
        "current_best": "Human review should focus on the flagged claim, method, inference, and reproducibility issues.",
        "crux": "Whether the reported evidence supports the main claim under the run's design and statistical assumptions.",
        "hypotheses": [{
            "id": "H1",
            "statement": "The run's main claim is supported by its artifacts and results.",
            "status": "unknown",
            "evidence": evidence_for(artifacts, ["REPORT.md", "paper_draft/sections/", "results/"]),
            "links": [],
        }],
        "experiments": [{
            "id": "E1",
            "mode": "artifact_review",
            "name": "Fallback artifact and source review",
            "design": "Deterministic scan of reports, paper sections, references, result JSON, figures, source code, canonical trajectory, evidence inventory, and literature sources.",
            "status": "done",
            "result": f"{len(artifacts)} artifact(s) indexed; {source_count} literature source(s) available.",
            "evidence": evidence_for(artifacts, ["REPORT.md", "results/", "literature-sources.json"]),
            "links": [],
        }],
        "findings": findings,
        "decisions": decisions,
        "assessments": [],
        "incidents": [{
            "id": "I1",
            "kind": "unresolved",
            "detail": "Automated world-model reconstruction failed; fallback review model was generated.",
            "evidence": evidence_for(artifacts, ["canonical_trajectory.json"]),
            "links": [],
        }],
        "open_questions": [item[1] for item in ISSUE_TEMPLATES],
        "fallback": True,
        "artifactSummary": {
            "artifactCount": len(artifacts),
            "canonicalEventCount": canonical.get("summary", {}).get("eventCount", 0),
            "literatureSourceCount": source_count,
        },
    }

    decision_review = {
        "version": "fallback_decision_review_v1",
        "runId": repo,
        "runQuality": {
            "verdict": "mixed",
            "rationale": "Automated reconstruction failed, so this conservative fallback flags load-bearing scientific review issues instead of asserting a full causal reconstruction.",
        },
        "decisions": review_decisions,
    }
    finding_review = {
        "version": "fallback_finding_review_v1",
        "runId": repo,
        "findings": [
            {"id": "F1", "show_by_default": True, "reason": "Fallback status affects review readiness."},
            {"id": "F2", "show_by_default": True, "reason": "Literature coverage affects claim support."},
        ],
    }
    status = {
        "repo": repo,
        "commit": "",
        "status": "fallback_review_ready",
        "updatedAt": now_iso(),
        "files": {
            "canonical_trajectory": (data_run_dir / "canonical_trajectory.json").exists(),
            "literature_sources": (data_run_dir / "literature-sources.json").exists(),
            "world_model": True,
            "decision_review": True,
            "finding_review": True,
        },
        "errorSummary": "World model reconstruction failed; deterministic fallback review was generated.",
    }

    for name, payload in [
        ("world_model.json", world_model),
        ("decision-review.json", decision_review),
        ("finding-review.json", finding_review),
        ("processing-status.json", status),
    ]:
        (data_run_dir / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote fallback review model for {repo} to {data_run_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic fallback visualizer review files.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--data-run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    data_run_dir = Path(args.data_run_dir).resolve()
    build(run_dir.name, run_dir, data_run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
