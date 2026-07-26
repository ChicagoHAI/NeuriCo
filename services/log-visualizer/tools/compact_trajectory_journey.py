#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_text(path: Path, cap: int = 120000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:cap]


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def clean(text, n=220):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"=+", "", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


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


def config_value(config, names):
    if not isinstance(config, dict):
        return ""
    for k, v in flatten(config):
        if any(name in k.lower() for name in names):
            return str(v)
    return ""


def tex_expanded(path: Path):
    text = read_text(path)
    if not text:
        return ""
    root = path.parent

    def repl(m):
        name = m.group(1)
        for p in [root / name, root / f"{name}.tex"]:
            if p.exists():
                return read_text(p, 30000)
        return ""

    return re.sub(r"\\(?:input|include)\{([^}]+)\}", repl, text)


def section(text, names, n=320):
    for name in names:
        m = re.search(rf"(?ims)^#+\s*{re.escape(name)}\b(.*?)(?=^#+\s|\Z)", text)
        if m:
            return clean(m.group(1), n)
    return ""


def tex_abstract(text, n=320):
    m = re.search(r"(?is)\\begin\{abstract\}(.*?)\\end\{abstract\}", text)
    if m:
        return clean(m.group(1), n)
    return ""


def metric_summary(path: Path):
    if not path.exists():
        return "", []
    try:
        with path.open(encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        return "", [f"Metric parse error: {type(e).__name__}: {e}"]

    if not rows:
        return "", ["Metric file exists but is empty."]

    facts = [f"{len(rows)} layerwise rows"]
    for col in rows[0].keys():
        if col.lower() in {"layer", "layer_idx", "idx", "index"}:
            continue
        vals = []
        for row in rows:
            try:
                vals.append(float(row[col]))
            except Exception:
                pass
        if not vals:
            continue
        best = max(vals)
        layer = rows[vals.index(best)].get("layer") or rows[vals.index(best)].get("layer_idx") or ""
        suffix = f" at layer {layer}" if layer != "" else ""
        facts.append(f"best {col}={best:g}{suffix}")
        if len(facts) >= 4:
            break
    return "; ".join(facts), []


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

    config = read_json(raw / "results/config.json") or {}
    report = read_text(raw / "REPORT.md")
    paper_tex = tex_expanded(raw / "paper_draft/main.tex")
    metric_text, metric_errors = metric_summary(raw / "results/metrics_layerwise.csv")

    model = config_value(config, ["model_name", "model"])
    dataset = config_value(config, ["dataset_path", "dataset"])
    batch = config_value(config, ["batch_size"])
    seed = config_value(config, ["seed"])

    final_result = (
        section(report, ["Conclusion", "Discussion", "Findings", "Results", "Summary"], 260)
        or tex_abstract(paper_tex, 260)
        or metric_text
        or "Final result not clearly extracted."
    )

    figures = []
    for d in [raw / "figures", raw / "paper_draft/figures"]:
        if d.exists():
            figures.extend([p.name for p in sorted(d.glob("*.png"))])
    figures = sorted(set(figures))

    stages = journey.get("stages", [])
    problems = [
        s["title"] for s in stages
        if s.get("status") in {"partial", "missing", "unclear", "error"}
    ]

    for s in stages:
        title = s.get("title", "")

        if title == "Research idea":
            s["inputBrief"] = "Initial research task."
            s["generatedBrief"] = clean(s.get("generated", ""), 180)
            s["outputBrief"] = clean(s.get("output", ""), 150)
            s["checkBrief"] = "Is this idea clear, novel, and testable?"

        elif title == "Literature review":
            s["inputBrief"] = "Research idea."
            s["generatedBrief"] = clean(s.get("generated", ""), 180)
            s["outputBrief"] = "Prior-work context for novelty and baselines."
            s["checkBrief"] = "Are important papers or baselines missing?"

        elif title == "Experiment design":
            s["inputBrief"] = "Idea + literature review."
            s["generatedBrief"] = clean(f"Model={model or 'MISSING'}; dataset={dataset or 'MISSING'}; batch={batch or 'MISSING'}; seed={seed or 'MISSING'}.", 180)
            s["outputBrief"] = "Runnable experiment design and config."
            s["checkBrief"] = "Does this setup test the hypothesis?"

        elif title == "Experiment run":
            s["inputBrief"] = "Script + config + dataset/model."
            s["generatedBrief"] = clean(s.get("generated", ""), 170)
            s["outputBrief"] = clean(s.get("output", ""), 180)
            s["checkBrief"] = "Was it completed and reproducible?"

        elif title == "Result analysis":
            s["inputBrief"] = "Experiment outputs."
            s["generatedBrief"] = metric_text or "Metric summary not extracted."
            s["outputBrief"] = f"Figures: {', '.join(figures[:4])}" if figures else "Figures not extracted."
            s["checkBrief"] = "Do metrics support the claim?"

        elif title == "Interpretation":
            s["inputBrief"] = "Results + research question."
            s["generatedBrief"] = clean(s.get("generated", ""), 220)
            s["outputBrief"] = "Claim-level interpretation."
            s["checkBrief"] = "Does it overclaim or ignore uncertainty?"

        elif title == "Report":
            s["inputBrief"] = "Full trajectory."
            s["generatedBrief"] = "Final written artifact assembled."
            s["outputBrief"] = clean(s.get("output", ""), 180)
            s["checkBrief"] = "Does report match actual evidence?"

        s["attention"] = (
            s.get("error")
            or ("Needs verification." if s.get("status") != "completed" else "")
        )

    journey["dashboardCards"] = [
        {
            "label": "Final result",
            "value": final_result,
            "tone": "primary",
        },
        {
            "label": "Needs attention",
            "value": ", ".join(problems) if problems else "No missing stage detected; verify correctness.",
            "tone": "warning" if problems else "ok",
        },
        {
            "label": "Experiment setup",
            "value": f"{model or 'MISSING model'} · {dataset or 'MISSING dataset'}",
            "tone": "neutral",
        },
        {
            "label": "Main outputs",
            "value": f"{metric_text or 'MISSING metrics'}; {', '.join(figures[:3]) if figures else 'no figures extracted'}",
            "tone": "neutral",
        },
    ]

    if metric_errors:
        journey["dashboardCards"].insert(1, {
            "label": "Extractor error",
            "value": "; ".join(metric_errors),
            "tone": "error",
        })

    journey["stages"] = stages

    journey_path.write_text(json.dumps(journey, indent=2, ensure_ascii=False), encoding="utf-8")
    canonical["trajectoryJourney"] = journey
    canonical_path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Compacted journey dashboard:")
    for card in journey["dashboardCards"]:
        print(f"- {card['label']}: {card['value'][:180]}")
    print("\nStages:")
    for s in stages:
        print(f"- {s['title']} [{s.get('status')}]: {s.get('generatedBrief')}")


if __name__ == "__main__":
    main()
