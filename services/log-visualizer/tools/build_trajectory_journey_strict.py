#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_text(path: Path, cap: int = 80000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:cap]
    except Exception:
        return ""


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None



def read_tex_expanded(path: Path, cap: int = 120000) -> str:
    """Read a TeX file and inline simple \\input{...} / \\include{...} references."""
    text = read_text(path, cap)
    if not text:
        return ""

    root = path.parent

    def repl(match):
        name = match.group(1).strip()
        candidates = [
            root / name,
            root / f"{name}.tex",
            path.parent / name,
            path.parent / f"{name}.tex",
        ]
        for c in candidates:
            if c.exists():
                return read_text(c, cap // 4)
        return match.group(0)

    text = re.sub(r"\\(?:input|include)\{([^}]+)\}", repl, text)
    return text[:cap]

def clean(x, n=500):
    text = re.sub(r"\s+", " ", str(x or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def yaml_value(text: str, key: str) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", text)
    return m.group(1).strip().strip("'\"") if m else ""


def section(text: str, names: list[str], n=900) -> str:
    for name in names:
        m = re.search(rf"(?ims)^#+\s*{re.escape(name)}\b(.*?)(?=^#+\s|\Z)", text)
        if m:
            return clean(m.group(1), n)
    return ""


def tex_abstract(text: str, n=900) -> str:
    m = re.search(r"(?is)\\begin\{abstract\}(.*?)\\end\{abstract\}", text)
    return clean(m.group(1), n) if m else ""


def flatten(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        out.append((prefix, f"{len(obj)} items" if len(obj) > 8 else obj))
    else:
        out.append((prefix, obj))
    return out


def get_config(config, keys):
    if not isinstance(config, dict):
        return ""
    for k, v in flatten(config):
        lk = k.lower()
        if any(key in lk for key in keys):
            return str(v)
    return ""


def csv_metrics(path: Path):
    if not path.exists():
        return [], []
    try:
        with path.open(encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        return [], [f"Could not parse metrics CSV: {type(e).__name__}: {e}"]

    if not rows:
        return [], ["Metrics CSV exists but has no rows."]

    facts = [f"{path.name}: {len(rows)} layerwise rows."]
    cols = list(rows[0].keys())
    numeric_cols = []

    for col in cols:
        if col.lower() in {"layer", "layer_idx", "index", "idx"}:
            continue
        vals = []
        for row in rows:
            try:
                vals.append(float(row[col]))
            except Exception:
                pass
        if vals:
            numeric_cols.append((col, vals))

    for col, vals in numeric_cols[:8]:
        best = max(vals)
        best_i = vals.index(best)
        row = rows[best_i]
        layer = row.get("layer") or row.get("layer_idx") or row.get("Layer")
        suffix = f" at layer {layer}" if layer not in (None, "") else ""
        facts.append(f"Best {col}: {best:g}{suffix}.")

    return facts[:8], []


def existing(root: Path, paths: list[str]) -> list[str]:
    return [p for p in paths if (root / p).exists()]


def papers(root: Path):
    d = root / "papers"
    if not d.exists():
        return []
    return [p.stem.replace("_", " ") for p in sorted(d.glob("*.pdf"))[:12]]


def figures(root: Path):
    found = []
    for d in [root / "figures", root / "paper_draft/figures"]:
        if d.exists():
            for p in sorted(d.glob("*")):
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}:
                    found.append(str(p.relative_to(root)))
    return sorted(set(found))


def status(required_values, partial_values=None, errors=None):
    errors = errors or []
    partial_values = partial_values or []
    if errors:
        return "error"
    if all(bool(x) for x in required_values):
        return "completed"
    if any(bool(x) for x in required_values + partial_values):
        return "partial"
    return "missing"


def stage(
    *,
    id,
    title,
    status,
    input,
    generated,
    output,
    user_decision,
    facts,
    source_paths,
    evidence_query,
    error=None,
):
    return {
        "id": id,
        "title": title,
        "status": status,
        "input": input,
        "generated": generated,
        "output": output,
        "userDecision": user_decision,
        "facts": [f for f in facts if f],
        "sourcePaths": source_paths,
        "evidenceQuery": evidence_query,
        "error": error,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-run-dir", required=True)
    ap.add_argument("--vis-run-dir", required=True)
    args = ap.parse_args()

    raw = Path(args.raw_run_dir).expanduser().resolve()
    vis = Path(args.vis_run_dir).expanduser().resolve()

    canonical_path = vis / "canonical_trajectory.json"
    if not canonical_path.exists():
        raise SystemExit(f"Missing {canonical_path}")

    idea_yaml = read_text(raw / ".neurico/idea.yaml")
    research_prompt = read_text(raw / "logs/research_prompt.txt")
    planning = read_text(raw / "planning.md")
    lit_review = read_text(raw / "literature_review.md")
    resources = read_text(raw / "resources.md")
    report_md = read_text(raw / "REPORT.md")
    paper_tex = read_tex_expanded(raw / "paper_draft/main.tex")
    readme = read_text(raw / "README.md")

    config = read_json(raw / "results/config.json") or {}
    summary = read_json(raw / "results/summary.json") or {}
    pipeline_results = read_json(raw / ".neurico/pipeline_results.json") or {}

    title = yaml_value(idea_yaml, "title")
    domain = yaml_value(idea_yaml, "domain")
    hypothesis = yaml_value(idea_yaml, "hypothesis")

    if not title:
        m = re.search(r"(?im)^#+\s*research title\s+(.+?)$", research_prompt)
        title = clean(m.group(1), 160) if m else ""

    if not hypothesis:
        m = re.search(r"(?is)hypothesis[:\s]+['\"]?([^'\"]{40,400})", idea_yaml + "\n" + research_prompt)
        hypothesis = clean(m.group(1), 320) if m else ""

    model = get_config(config, ["model_name", "model"])
    dataset = get_config(config, ["dataset_path", "dataset"])
    batch = get_config(config, ["batch_size"])
    seed = get_config(config, ["seed"])
    bootstrap = get_config(config, ["bootstrap_samples"])
    randomization = get_config(config, ["randomization_samples"])

    config_facts = []
    if model: config_facts.append(f"Model: {model}.")
    if dataset: config_facts.append(f"Dataset: {dataset}.")
    if batch: config_facts.append(f"Batch size: {batch}.")
    if seed: config_facts.append(f"Seed: {seed}.")
    if bootstrap: config_facts.append(f"Bootstrap samples: {bootstrap}.")
    if randomization: config_facts.append(f"Randomization samples: {randomization}.")

    metric_path = raw / "results/metrics_layerwise.csv"
    metric_facts, metric_errors = csv_metrics(metric_path)

    paper_themes = papers(raw)
    fig_paths = figures(raw)

    lit_question = section(lit_review, ["Research Question", "Review Scope", "Summary"], 700)
    plan_summary = section(planning, ["Plan", "Experiment", "Method", "Implementation"], 900)
    report_summary = (
        section(report_md, ["Results", "Findings", "Discussion", "Conclusion", "Summary"], 1000)
        or tex_abstract(paper_tex, 1000)
        or clean(report_md[:1000] or readme[:1000], 1000)
    )

    script_path = "src/run_implicit_token_lens.py" if (raw / "src/run_implicit_token_lens.py").exists() else ""
    output_paths = existing(raw, [
        "results/config.json",
        "results/metrics_layerwise.csv",
        "results/summary.json",
        ".neurico/pipeline_results.json",
        "REPORT.md",
        "paper_draft/main.tex",
        "paper_draft/main.pdf",
    ])

    stages = []

    stages.append(stage(
        id="idea",
        title="Research idea",
        status=status([title, hypothesis]),
        input=clean(research_prompt[:900] or "MISSING: no research prompt extracted."),
        generated=(
            f"Title: {title or 'MISSING'}. "
            f"Domain: {domain or 'MISSING'}. "
            f"Hypothesis: {hypothesis or 'MISSING'}."
        ),
        output=f"Goal: investigate “{title or 'MISSING'}” as the run's research direction.",
        user_decision="Approve only if this goal is clear, novel enough, and experimentally testable.",
        facts=[
            f"Title: {title}" if title else "MISSING title.",
            f"Domain: {domain}" if domain else "MISSING domain.",
            f"Hypothesis: {hypothesis}" if hypothesis else "MISSING hypothesis.",
        ],
        source_paths=existing(raw, [".neurico/idea.yaml", "logs/research_prompt.txt", "paper/OUTLINE.md"]),
        evidence_query="idea title hypothesis research prompt",
    ))

    stages.append(stage(
        id="review",
        title="Literature review",
        status=status([lit_review or paper_themes]),
        input=f"Research goal: {title or 'MISSING research idea'}.",
        generated=(
            f"Review question/scope: {lit_question or 'MISSING explicit review question.'} "
            f"Visible paper themes: {', '.join(paper_themes[:8]) or 'MISSING paper themes'}."
        ),
        output="Prior-work context for judging novelty, baselines, and experiment design.",
        user_decision="Intervene if key baselines, competing methods, or related papers are missing.",
        facts=[f"Paper/theme: {p}." for p in paper_themes[:8]],
        source_paths=existing(raw, ["literature_review.md", "resources.md", "papers/README.md"]),
        evidence_query="literature review papers related work baseline tuned lens",
    ))

    stages.append(stage(
        id="design",
        title="Experiment design",
        status=status([config, script_path], [planning]),
        input=f"Research goal: {title or 'MISSING'}. Literature review: {'available' if lit_review else 'MISSING'}.",
        generated=(
            f"Experiment configuration: {' '.join(config_facts) if config_facts else 'MISSING config facts.'} "
            f"Plan text: {clean(plan_summary, 500) if plan_summary else 'MISSING explicit plan summary.'}"
        ),
        output=(
            f"Runnable design: {script_path or 'MISSING experiment script'} "
            f"with config {('results/config.json' if config else 'MISSING config')}."
        ),
        user_decision="Intervene if the selected model, dataset, metric, or sampling design does not test the hypothesis.",
        facts=config_facts + ([f"Script: {script_path}."] if script_path else ["MISSING experiment script."]),
        source_paths=existing(raw, ["planning.md", "results/config.json", "src/run_implicit_token_lens.py"]),
        evidence_query="planning config model dataset metric experiment design",
    ))

    experiment_facts = []
    experiment_facts.append(f"Script: {script_path}." if script_path else "MISSING script.")
    experiment_facts.extend(config_facts)
    experiment_facts.extend([f"Output: {path}." for path in output_paths[:6]])

    stages.append(stage(
        id="experiment",
        title="Experiment run",
        status=status([script_path, metric_path.exists()], [summary, pipeline_results]),
        input=(
            f"Script: {script_path or 'MISSING'}. "
            f"Config: {'results/config.json' if config else 'MISSING'}. "
            f"{' '.join(config_facts)}"
        ),
        generated=(
            f"Execution used script {script_path or 'MISSING'} with "
            f"{model or 'MISSING model'} on {dataset or 'MISSING dataset'}."
        ),
        output=(
            f"Observed run outputs: {', '.join(output_paths) if output_paths else 'MISSING concrete outputs.'}"
        ),
        user_decision="Intervene if the run is incomplete, not reproducible, or not aligned with the design.",
        facts=experiment_facts,
        source_paths=existing(raw, ["src/run_implicit_token_lens.py", "results/config.json", "results/summary.json", ".neurico/pipeline_results.json"]),
        evidence_query="experiment run script config output results",
    ))

    stages.append(stage(
        id="analysis",
        title="Result analysis",
        status=status([metric_facts or fig_paths], errors=metric_errors),
        input=f"Experiment outputs: {', '.join(output_paths) if output_paths else 'MISSING outputs'}.",
        generated=(
            f"Metric extraction: {' '.join(metric_facts) if metric_facts else 'MISSING parsed metric facts.'} "
            f"Figures: {', '.join(fig_paths[:5]) if fig_paths else 'MISSING figures'}."
        ),
        output="Layerwise quantitative results and visualizations for evaluating the hypothesis.",
        user_decision="Intervene if metrics are weak, cherry-picked, missing baselines, or insufficient for the claim.",
        facts=metric_facts + [f"Figure: {p}." for p in fig_paths[:6]],
        source_paths=[str(metric_path.relative_to(raw))] if metric_path.exists() else [] + fig_paths[:6],
        evidence_query="metrics layerwise figures results analysis",
        error="; ".join(metric_errors) if metric_errors else None,
    ))

    stages.append(stage(
        id="interpretation",
        title="Interpretation",
        status=status([report_summary]),
        input="Research goal, literature context, metrics, and figures.",
        generated=report_summary or "MISSING interpretation text.",
        output="Interpretation of whether the results support the hypothesis.",
        user_decision="Intervene if conclusions overclaim, omit limitations, or are not supported by the metrics.",
        facts=[report_summary] if report_summary else ["MISSING interpretation summary."],
        source_paths=existing(raw, ["REPORT.md", "README.md", "paper_draft/main.tex"]),
        evidence_query="interpretation discussion conclusion limitations results",
    ))

    stages.append(stage(
        id="report",
        title="Report",
        status=status([existing(raw, ["REPORT.md", "paper_draft/main.tex", "paper_draft/main.pdf"])]),
        input="Idea, review, design, results, and interpretation.",
        generated="Final write-up assembled from the run's research materials.",
        output=f"Written outputs: {', '.join(existing(raw, ['REPORT.md', 'paper_draft/main.tex', 'paper_draft/main.pdf', 'paper_draft/neurips_2025.pdf'])) or 'MISSING final write-up.'}",
        user_decision="Intervene if the report hides failures, exaggerates findings, or disagrees with the actual results.",
        facts=[f"Written output: {p}." for p in existing(raw, ["REPORT.md", "paper_draft/main.tex", "paper_draft/main.pdf", "paper_draft/neurips_2025.pdf"])],
        source_paths=existing(raw, ["REPORT.md", "paper_draft/main.tex", "paper_draft/main.pdf", "paper_draft/neurips_2025.pdf"]),
        evidence_query="report paper draft final writeup",
    ))

    completed = sum(s["status"] == "completed" for s in stages)
    partial = sum(s["status"] == "partial" for s in stages)
    missing = sum(s["status"] == "missing" for s in stages)
    errors = sum(s["status"] == "error" for s in stages)

    dashboard_cards = [
        {
            "label": "Goal",
            "value": title or "MISSING research title",
            "note": hypothesis or "MISSING hypothesis",
        },
        {
            "label": "Experiment",
            "value": model or "MISSING model",
            "note": f"Dataset: {dataset or 'MISSING dataset'}",
        },
        {
            "label": "Outputs",
            "value": ", ".join(output_paths[:3]) if output_paths else "MISSING outputs",
            "note": ", ".join(fig_paths[:3]) if fig_paths else "No figures extracted",
        },
        {
            "label": "Coverage",
            "value": f"{completed}/7 completed",
            "note": f"{partial} partial · {missing} missing · {errors} error",
        },
    ]

    journey = {
        "schemaVersion": 2,
        "purpose": "human_trajectory_review",
        "dashboardCards": dashboard_cards,
        "stages": stages,
    }

    out = vis / "trajectory_journey.generated.json"
    out.write_text(json.dumps(journey, indent=2, ensure_ascii=False), encoding="utf-8")

    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["trajectoryJourney"] = journey
    canonical_path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {out}")
    for s in stages:
        print(f"\n{s['title']} [{s['status']}]")
        print("INPUT:", s["input"][:220])
        print("GENERATED:", s["generated"][:220])
        print("OUTPUT:", s["output"][:220])
        print("DECISION:", s["userDecision"][:220])


if __name__ == "__main__":
    main()
