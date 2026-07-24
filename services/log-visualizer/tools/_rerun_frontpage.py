#!/usr/bin/env python3
"""One-off: re-run ONLY the abstract-only front-page selection for already-built
world models, after the FRONTPAGE_INSTRUCTIONS prompt change. Cheap — one LLM call
per run. Updates world_model.json['frontPageDecisions'] in place; touches nothing else.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reconstruct_world_model as R

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_PARENT = os.path.dirname(REPO)  # raw run folders sit next to the visualizer
MODEL = os.environ.get("MODEL", "sonnet")
TIMEOUT = 1200
MAX_REPAIRS = 2

runs = sys.argv[1:] or [
    "fix-lazy-llms-claude",
    "grounded-novelty-ai-69c6-claude",
    "llm-forecasting-3be2-codex",
]

for run_id in runs:
    wm_path = os.path.join(REPO, "data", "runs", run_id, "world_model.json")
    raw_dir = os.path.join(RUNS_PARENT, run_id)
    if not os.path.exists(wm_path):
        print(f"[skip] {run_id}: no world_model.json", flush=True)
        continue

    wm = json.load(open(wm_path))
    decisions = [d for d in (wm.get("decisions") or []) if isinstance(d, dict) and d.get("id")]
    abstract = R.read_capped(os.path.join(raw_dir, "paper_draft", "sections", "abstract.tex"), 8000) or ""
    if not abstract:
        print(f"[skip] {run_id}: no abstract.tex (front-page call needs it)", flush=True)
        continue
    if not decisions:
        print(f"[skip] {run_id}: no decisions", flush=True)
        continue

    before = wm.get("frontPageDecisions")
    prompt = R._frontpage_prompt(run_id, abstract, decisions)
    obj, cost = R._invoke_section(f"frontpage:{run_id}", prompt, MODEL, TIMEOUT, MAX_REPAIRS)
    picks = R.select_front_page(obj, {d["id"] for d in decisions})

    if not picks:
        print(f"[warn] {run_id}: model returned no valid picks — leaving {before} unchanged", flush=True)
        continue

    wm["frontPageDecisions"] = picks
    wm["updated_at"] = R.now_iso()
    json.dump(wm, open(wm_path, "w"), indent=2)
    print(f"[ok]   {run_id}: {before} -> {picks}  (${cost or 0:.4f})", flush=True)
