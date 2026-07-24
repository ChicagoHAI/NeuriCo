#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_text(path: Path, cap: int = 40000) -> str:
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


def clean(text: str, n: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def yamlish(text: str, key: str) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", text)
    return m.group(1).strip().strip("\"'") if m else ""


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


def find_config_value(config, names):
    if not isinstance(config, dict):
        return ""
    for k, v in flatten(config):
        lk = k.lower()
        if any(name in lk for name in names):
            return str(v)
    return ""


def summarize_metrics(path: Path):
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return []

    if not rows:
        return []

    facts = [f"Result table contains {len(rows)} layerwise row(s)."]
    numeric_cols = []
    for col in rows[0].keys():
        vals = []
        for row in rows:
            try:
                vals.append(float(row[col]))
            except Exception:
                pass
        if vals:
            numeric_cols.append((col, vals))

    for col, vals in numeric_cols[:6]:
        best = max(vals)
        best_i = vals.index(best)
        layer = rows[best_i].get("layer") or rows[best_i].get("layer_idx") or rows[best_i].get("Layer")
        suffix = f" at layer {layer}" if layer not in (None, "") else ""
        facts.append(f"Best {col}: {best:g}{suffix}.")
    return facts[:5]


def find_paper_themes(root: Path):
    text = read_text(root / "literature_review.md") + "\n" + read_text(root / "resources.md")
    text_l = text.lower()
    themes = []
    candidates = [
        ("tuned lenses", ["tuned lens", "tuned_lens"]),
        ("future lenses", ["future lens", "future_lens"]),
        ("backward lenses", ["backward lens", "backward_lens"]),
        ("prompt tuning", ["prompt tuning", "prompt_tuning"]),
        ("patchscopes", ["patchscopes"]),
        ("logit-lens interpretability", ["logit lens", "logit-lens"]),
    ]
    for label, keys in candidates:
        if any(k in text_l for k in keys):
            themes.append(label)

    if themes:
        return themes

    papers = sorted((root / "papers").glob("*.pdf")) if (root / "papers").exists() else []
    return [p.stem.replace("_", " ") for p in papers[:6]]


def update_stage(stages, title, **kwargs):
    for stage in stages:
        if stage.get("title") == title:
            stage.update(kwargs)
            return stage
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-run-dir", required=True)
    ap.add_argument("--vis-run-dir", required=True)
    args = ap.parse_args()

    raw = Path(args.raw_run_dir).expanduser().resolve()
    vis = Path(args.vis_run_dir).expanduser().resolve()
    journey_path = vis / "trajectory_journey.generated.json"
    canonical_path = vis / "canonical_trajectory.json"

    journey = json.loads(journey_path.read_text(encoding="utf-8"))
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))

    stages = journey.get("stages", [])

    idea_txt = read_text(raw / ".neurico/idea.yaml")
    research_prompt = read_text(raw / "logs/research_prompt.txt")
    config = read_json(raw / "results/config.json") or {}
    summary = read_json(raw / "results/summary.json") or {}
    report = read_text(raw / "REPORT.md")
    paper_main = read_text(raw / "paper_draft/main.tex")

    title = yamlish(idea_txt, "title") or "Logit Lens with Implicit Tokens"
    domain = yamlish(idea_txt, "domain") or "artificial intelligence"
    hypothesis = yamlish(idea_txt, "hypothesis")
    if not hypothesis:
        m = re.search(r"hypothesis[:\s]+['\"]?([^'\"]{40,280})", idea_txt + "\n" + research_prompt, re.I)
        hypothesis = clean(m.group(1), 260) if m else "Large language models may have implicit vocabularies that are not strictly part of the tokenizer vocabulary."

    model = find_config_value(config, ["model_name", "model"])
    dataset = find_config_value(config, ["dataset_path", "dataset"])
    batch_size = find_config_value(config, ["batch_size"])
    bootstrap = find_config_value(config, ["bootstrap_samples"])
    randomization = find_config_value(config, ["randomization_samples"])

    method_facts = []
    if model:
        method_facts.append(f"Model: {model}.")
    if dataset:
        method_facts.append(f"Dataset: {dataset}.")
    if batch_size:
        method_facts.append(f"Batch size: {batch_size}.")
    if bootstrap:
        method_facts.append(f"Bootstrap samples: {bootstrap}.")
    if randomization:
        method_facts.append(f"Randomization samples: {randomization}.")

    metric_path = raw / "results/metrics_layerwise.csv"
    metric_facts = summarize_metrics(metric_path)

    figures = []
    for d in [raw / "figures", raw / "paper_draft/figures"]:
        if d.exists():
            figures.extend([p.stem.replace("_", " ") for p in sorted(d.glob("*.png"))])
    figures = sorted(set(figures))[:6]

    themes = find_paper_themes(raw)

    report_outputs = []
    for p in ["REPORT.md", "paper_draft/main.tex", "paper_draft/main.pdf", "paper_draft/neurips_2025.pdf"]:
        if (raw / p).exists():
            report_outputs.append(p)

    update_stage(
        stages,
        "Research idea",
        oneLine=f"Generated idea: {title}.",
        input="Initial task prompt and research-topic specification.",
        generated=f"NeuriCo generated the research idea “{title}.” The hypothesis was: {hypothesis}",
        output=f"Research direction: test whether “{title}” is a meaningful way to study implicit-token behavior in language models.",
        facts=[
            f"Title: {title}.",
            f"Domain: {domain}.",
            f"Hypothesis: {hypothesis}",
        ],
        decision="Approve this stage only if the idea is specific, novel enough, and experimentally testable.",
    )

    update_stage(
        stages,
        "Literature review",
        oneLine=f"Reviewed prior work around {', '.join(themes[:4])}.",
        generated=f"NeuriCo gathered related work around {', '.join(themes) if themes else 'the research topic'}.",
        output="Prior-work context for judging novelty and selecting experiment baselines.",
        facts=[f"Theme: {t}." for t in themes[:8]],
        decision="Intervene if important related work, baselines, or competing methods are missing.",
    )

    update_stage(
        stages,
        "Experiment design",
        oneLine=f"Designed an implicit-token-lens evaluation using {model or 'the selected model'} on {dataset or 'the selected dataset'}.",
        generated="NeuriCo prepared the experiment setup: model, dataset, sampling settings, and layerwise evaluation metrics.",
        output="A concrete experiment plan that can be run and audited.",
        facts=method_facts + [
            "Main evaluation: layerwise implicit-token-lens analysis.",
            "Expected outputs: metrics table and layerwise figures.",
        ],
        decision="Intervene if the model, dataset, metrics, or baselines do not actually test the hypothesis.",
    )

    update_stage(
        stages,
        "Experiment run",
        status="partial" if not summary else "completed",
        oneLine="Ran or prepared the implicit-token-lens experiment.",
        generated=f"NeuriCo used the implicit-token-lens experiment implementation with configuration: {' '.join(method_facts) if method_facts else 'configuration not fully extracted.'}",
        output="Experiment outputs should include layerwise metrics and generated figures.",
        facts=[
            "Main script: src/run_implicit_token_lens.py.",
            *method_facts,
        ],
        decision="Intervene if the run did not finish, used a wrong config, or cannot be reproduced.",
    )

    update_stage(
        stages,
        "Result analysis",
        oneLine="Analyzed layerwise behavior using metrics and figures.",
        generated="NeuriCo analyzed the experiment outputs with layerwise metrics and visualizations.",
        output=f"Result artifacts include metrics and figures: {', '.join(figures[:4]) if figures else 'figures not clearly extracted.'}",
        facts=metric_facts + [f"Figure: {f}." for f in figures[:4]],
        decision="Intervene if the analysis does not support the claim, lacks baselines, or cherry-picks layers.",
    )

    interpretation_text = ""
    m = re.search(r"(?is)\\begin\{abstract\}(.*?)\\end\{abstract\}", paper_main)
    if m:
        interpretation_text = clean(m.group(1), 420)
    elif report:
        interpretation_text = clean(report[:900], 420)

    update_stage(
        stages,
        "Interpretation",
        oneLine="Interpreted whether the results support the implicit-token-lens hypothesis.",
        generated=interpretation_text or "NeuriCo wrote interpretation material connecting the results to the research question.",
        output="Scientific interpretation of what the metrics imply.",
        facts=[interpretation_text] if interpretation_text else ["Interpretation text exists but needs closer review."],
        decision="Intervene if the conclusion overclaims, ignores uncertainty, or is not supported by metrics.",
    )

    update_stage(
        stages,
        "Report",
        oneLine="Produced a report or paper-style draft.",
        generated="NeuriCo assembled the research into a report / paper-style artifact.",
        output=f"Written outputs: {', '.join(report_outputs) if report_outputs else 'not clearly extracted.'}",
        facts=[f"Written output: {x}." for x in report_outputs],
        decision="Intervene if the report omits failures, exaggerates results, or disagrees with the actual run.",
    )

    journey["dashboardCards"] = [
        {
            "label": "Research goal",
            "value": title,
            "note": clean(hypothesis, 140),
        },
        {
            "label": "Experiment setup",
            "value": model or "Model not extracted",
            "note": f"Dataset: {dataset or 'not extracted'}",
        },
        {
            "label": "Main outputs",
            "value": "Metrics + figures + report",
            "note": ", ".join(figures[:3]) if figures else "Layerwise outputs need review",
        },
        {
            "label": "Needs review",
            "value": "Experiment run",
            "note": "Verify completion, reproducibility, and whether metrics support the claim.",
        },
    ]

    journey["stages"] = stages
    journey_path.write_text(json.dumps(journey, indent=2, ensure_ascii=False), encoding="utf-8")
    canonical["trajectoryJourney"] = journey
    canonical_path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Enriched journey:")
    for s in stages:
        print(f"- {s['title']} [{s.get('status')}]")
        print(f"  {s.get('oneLine')}")
        for fact in s.get("facts", [])[:4]:
            print(f"  • {fact}")


if __name__ == "__main__":
    main()
