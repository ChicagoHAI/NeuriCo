#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_text(path: Path, cap: int = 20000) -> str:
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


def clean(text: str, n: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def yamlish_value(text: str, key: str) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", text)
    if not m:
        return ""
    return m.group(1).strip().strip("\"'")


def md_section(text: str, names: list[str], cap: int = 900) -> str:
    for name in names:
        pat = rf"(?is)^#+\s*{re.escape(name)}\b(.*?)(?=^#+\s|\Z)"
        m = re.search(pat, text, flags=re.MULTILINE)
        if m:
            return clean(m.group(1), cap)
    return ""


def flatten_json(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.extend(flatten_json(v, key))
    elif isinstance(obj, list):
        if len(obj) <= 8:
            out.append((prefix, obj))
        else:
            out.append((prefix, f"{len(obj)} items"))
    else:
        out.append((prefix, obj))
    return out


def summarize_config(config) -> str:
    if not isinstance(config, dict):
        return ""
    pairs = flatten_json(config)
    useful = []
    keys = ["model", "dataset", "metric", "layer", "seed", "batch", "token", "prompt", "baseline", "split", "sample"]
    for k, v in pairs:
        if any(word in k.lower() for word in keys):
            useful.append(f"{k}={v}")
    if not useful:
        useful = [f"{k}={v}" for k, v in pairs[:10]]
    return clean("; ".join(useful[:14]), 520)


def summarize_csv(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with path.open(encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return ""

    if not rows:
        return ""

    cols = rows[0].keys()
    numeric = {}
    for col in cols:
        vals = []
        for row in rows:
            try:
                vals.append(float(row[col]))
            except Exception:
                pass
        if vals:
            numeric[col] = vals

    parts = [f"{path.name} has {len(rows)} row(s)"]
    for col, vals in list(numeric.items())[:8]:
        max_v = max(vals)
        max_i = vals.index(max_v)
        row = rows[max_i]
        layer = row.get("layer") or row.get("Layer") or row.get("layer_idx") or ""
        suffix = f" at layer {layer}" if layer != "" else ""
        parts.append(f"best {col}={max_v:g}{suffix}")

    return clean("; ".join(parts), 650)


def list_existing(root: Path, paths: list[str]) -> list[str]:
    return [p for p in paths if (root / p).exists()]


def first_existing(root: Path, paths: list[str]) -> str:
    for p in paths:
        if (root / p).exists():
            return p
    return ""


def stage(status, title, input_, generated, output, intervene, evidence_query, source_paths):
    return {
        "title": title,
        "status": status,
        "input": clean(input_, 700),
        "generated": clean(generated, 900),
        "output": clean(output, 900),
        "intervention": clean(intervene, 700),
        "evidenceQuery": evidence_query,
        "sourcePaths": source_paths[:8],
    }


def build(root: Path):
    idea_txt = read_text(root / ".neurico/idea.yaml")
    research_prompt = read_text(root / "logs/research_prompt.txt")
    planning = read_text(root / "planning.md")
    lit = read_text(root / "literature_review.md")
    resources = read_text(root / "resources.md")
    report = read_text(root / "REPORT.md")
    readme = read_text(root / "README.md")
    paper_main = read_text(root / "paper_draft/main.tex")

    config = read_json(root / "results/config.json")
    summary = read_json(root / "results/summary.json")
    pipeline_results = read_json(root / ".neurico/pipeline_results.json")

    title = yamlish_value(idea_txt, "title")
    domain = yamlish_value(idea_txt, "domain")
    hypothesis = yamlish_value(idea_txt, "hypothesis")

    if not title:
        m = re.search(r"(?im)^#*\s*research title\s+(.+)$", research_prompt)
        title = clean(m.group(1), 120) if m else "Logit Lens with Implicit Tokens"

    if not hypothesis:
        m = re.search(r"(?is)hypothesis[:\s]+(.{40,500})", idea_txt + "\n" + research_prompt)
        hypothesis = clean(m.group(1), 260) if m else ""

    paper_titles = []
    papers_dir = root / "papers"
    if papers_dir.exists():
        for p in sorted(papers_dir.glob("*.pdf"))[:12]:
            paper_titles.append(p.stem.replace("_", " "))

    config_summary = summarize_config(config)
    metrics_paths = sorted((root / "results").glob("**/*.csv")) + sorted((root / "results").glob("*.csv"))
    metric_summaries = [summarize_csv(p) for p in metrics_paths]
    metric_summaries = [x for x in metric_summaries if x]

    figures = []
    for d in [root / "figures", root / "paper_draft/figures"]:
        if d.exists():
            figures.extend([str(p.relative_to(root)) for p in sorted(d.glob("*")) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}])
    figures = figures[:8]

    report_conclusion = md_section(report, ["Conclusion", "Discussion", "Findings", "Results", "Summary"], 900)
    if not report_conclusion and paper_main:
        m = re.search(r"(?is)\\begin\{abstract\}(.*?)\\end\{abstract\}", paper_main)
        report_conclusion = clean(m.group(1), 900) if m else clean(paper_main[:1000], 900)

    stages = []

    stages.append(stage(
        "completed" if title or hypothesis else "unclear",
        "Research idea",
        "Initial research prompt and task specification.",
        f"Research idea: {title}. Domain: {domain or 'not explicitly stated'}. Hypothesis / claim: {hypothesis or 'not clearly extracted.'}",
        f"Concrete research direction: investigate {title}.",
        "Pause here if the idea is not novel, not testable, too broad, or not worth spending experiment/review effort on.",
        "idea research prompt hypothesis title",
        list_existing(root, [".neurico/idea.yaml", "logs/research_prompt.txt", "paper/OUTLINE.md", "planning.md"]),
    ))

    stages.append(stage(
        "completed" if lit or paper_titles else "unclear",
        "Literature review",
        "Research idea and paper-search goal.",
        f"NeuriCo reviewed related work. Main visible papers/themes: {clean('; '.join(paper_titles[:8]), 500) or clean(lit[:500], 500) or 'not clearly extracted.'}",
        "Prior-work context for deciding whether the idea is grounded and how to design the experiment.",
        "Pause here if important baselines, competing methods, or related interpretability papers are missing.",
        "literature review related work papers tuned lens future lens",
        list_existing(root, ["literature_review.md", "resources.md", "papers/README.md"]) + [f"papers/{p.name}" for p in sorted((root / "papers").glob("*.pdf"))[:5]] if (root / "papers").exists() else [],
    ))

    stages.append(stage(
        "completed" if planning or config_summary else "unclear",
        "Experiment design",
        "Research idea plus literature review.",
        f"NeuriCo designed an experiment setup. Plan/config details: {config_summary or clean(planning[:700], 700) or 'not clearly extracted.'}",
        "A runnable evaluation plan with method/configuration/metrics/code path.",
        "Pause here if the method, metrics, dataset, model, or baselines do not actually test the research claim.",
        "planning config metric dataset model experiment design",
        list_existing(root, ["planning.md", "results/config.json", "src/run_implicit_token_lens.py", "paper/OUTLINE.md"]),
    ))

    stages.append(stage(
        "completed" if first_existing(root, ["src/run_implicit_token_lens.py"]) and (summary or pipeline_results or metric_summaries) else "partial",
        "Experiment run",
        "Experiment design, model/configuration, code, and dataset setup.",
        f"NeuriCo used the experiment implementation {first_existing(root, ['src/run_implicit_token_lens.py', 'code/run_implicit_token_lens.py']) or 'not clearly found'} with configuration: {config_summary or 'config not clearly extracted.'}",
        f"Execution produced downstream result artifacts: {', '.join([str(p.relative_to(root)) for p in metrics_paths[:4]]) or 'result files not clearly extracted.'}",
        "Pause here if the run did not finish, used the wrong config, skipped a planned setting, or cannot be reproduced.",
        "execution run script results config output",
        list_existing(root, ["src/run_implicit_token_lens.py", "results/config.json", "results/summary.json", ".neurico/pipeline_results.json"]),
    ))

    stages.append(stage(
        "completed" if metric_summaries or figures or summary else "unclear",
        "Result analysis",
        "Experiment outputs and saved metrics/figures.",
        f"NeuriCo analyzed the outputs. Metric summary: {' '.join(metric_summaries[:3]) or clean(json.dumps(summary, ensure_ascii=False)[:700], 700) or 'not clearly extracted.'}",
        f"Analysis artifacts include: {', '.join(figures[:5]) if figures else 'no figures clearly extracted.'}",
        "Pause here if the metric is weak, cherry-picked, missing baselines, or insufficient to support the claim.",
        "results metrics figures analysis layer accuracy mrr",
        [str(p.relative_to(root)) for p in metrics_paths[:5]] + figures[:5],
    ))

    stages.append(stage(
        "completed" if report_conclusion or report or readme else "unclear",
        "Interpretation",
        "Results, figures, prior work, and original research question.",
        f"NeuriCo interpreted the results as: {report_conclusion or clean(report[:900], 900) or clean(readme[:900], 900) or 'not clearly extracted.'}",
        "Explanation of what the results mean for the original research claim.",
        "Pause here if the interpretation overclaims, ignores uncertainty, or is not supported by the metrics/results.",
        "interpretation discussion limitations findings conclusion",
        list_existing(root, ["REPORT.md", "README.md", "paper_draft/main.tex"]),
    ))

    stages.append(stage(
        "completed" if (root / "REPORT.md").exists() or (root / "paper_draft/main.tex").exists() or (root / "paper_draft/main.pdf").exists() else "unclear",
        "Report",
        "Idea, literature review, design, results, and interpretation.",
        "NeuriCo assembled the research into a final report or paper-style draft.",
        f"Final written artifacts: {', '.join(list_existing(root, ['REPORT.md', 'paper_draft/main.tex', 'paper_draft/main.pdf', 'paper_draft/neurips_2025.pdf'])) or 'not clearly found.'}",
        "Pause here if the report omits failures, exaggerates findings, or does not match the actual results.",
        "report paper draft final conclusion",
        list_existing(root, ["REPORT.md", "paper_draft/main.tex", "paper_draft/main.pdf", "paper_draft/neurips_2025.pdf"]),
    ))

    completed = sum(1 for s in stages if s["status"] == "completed")
    partial = sum(1 for s in stages if s["status"] == "partial")
    unclear = sum(1 for s in stages if s["status"] == "unclear")

    return {
        "schemaVersion": 1,
        "purpose": "human_trajectory_review",
        "dashboard": {
            "progress": f"{completed}/7 stages completed",
            "weakSpot": ", ".join(s["title"] for s in stages if s["status"] != "completed") or "No obvious missing stage",
            "overallRead": "The run should be reviewed for correctness, not just presence of artifacts." if completed >= 6 else "Some stages need closer review before trusting the run.",
        },
        "stages": stages,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-run-dir", required=True)
    ap.add_argument("--vis-run-dir", required=True)
    args = ap.parse_args()

    raw = Path(args.raw_run_dir).expanduser().resolve()
    vis = Path(args.vis_run_dir).expanduser().resolve()
    canonical = vis / "canonical_trajectory.json"

    if not raw.exists():
        raise SystemExit(f"missing raw run dir: {raw}")
    if not canonical.exists():
        raise SystemExit(f"missing canonical trajectory: {canonical}")

    journey = build(raw)

    out = vis / "trajectory_journey.generated.json"
    out.write_text(json.dumps(journey, indent=2, ensure_ascii=False), encoding="utf-8")

    data = json.loads(canonical.read_text(encoding="utf-8"))
    data["trajectoryJourney"] = journey
    canonical.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {out}")
    print(f"Updated {canonical}")
    for s in journey["stages"]:
        print(f"- {s['title']} [{s['status']}]")
        print(f"  generated: {s['generated'][:180]}")
        print(f"  output:    {s['output'][:180]}")


if __name__ == "__main__":
    main()
