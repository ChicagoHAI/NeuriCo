#!/usr/bin/env python3
"""Run catalog evaluations against catalog models and write standard result files.

    $NEURICO_SAFETY_VENV/bin/python run_eval.py --evals xstest-safe strong-reject \
        --models qwen2.5-0.5b-instruct [--limit 100] [--out results/safety]

    # convert an Inspect JSON log from a custom task into the standard schema
    $NEURICO_SAFETY_VENV/bin/python run_eval.py --from-log results/safety/inspect_logs/x.json \
        --eval-id my-custom-eval --model-id qwen2.5-0.5b-instruct

Thin wrapper over NeuriCo's `safety.suites`; results are resumable per (eval, model) pair.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_safety_package, workspace_root  # noqa: E402

SRC = add_safety_package()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evals", nargs="*", default=[])
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out", type=Path, default=None, help="default: <workspace>/results/safety")
    parser.add_argument("--job", default=None, help="label stored in the results (default: workspace name)")
    parser.add_argument("--max-connections", type=int, default=16)
    parser.add_argument("--from-log", type=Path, help="convert an Inspect JSON log instead of running")
    parser.add_argument("--eval-id")
    parser.add_argument("--model-id")
    args = parser.parse_args()

    root = workspace_root()
    out = args.out or (root / "results" / "safety")
    out.mkdir(parents=True, exist_ok=True)
    job = args.job or root.name

    if args.from_log:
        from safety.kb import save_json, utc_now
        from safety.suites import SCHEMA, summarise_log, versions
        if not (args.eval_id and args.model_id):
            parser.error("--from-log needs --eval-id and --model-id")
        summary = summarise_log(args.from_log)
        record = {"schema": SCHEMA, "job": job, "eval_id": args.eval_id, "model_id": args.model_id,
                  "runner": "custom", "inspect_log": str(args.from_log), "versions": versions(),
                  "finished": utc_now(), **{k: v for k, v in summary.items() if k != "status"},
                  "status": "success" if summary["status"] == "success" else "failed"}
        path = out / f"{args.eval_id}__{args.model_id}.json"
        save_json(path, record)
        print(f"wrote {path}")
        return 0

    if not (args.evals and args.models):
        parser.error("--evals and --models are required (or use --from-log)")
    cmd = [sys.executable, str(SRC / "safety" / "suites.py"), "--job", job, "--out", str(out),
           "--evals", *args.evals, "--models", *args.models, "--max-connections", str(args.max_connections)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES")
    if gpu:
        cmd += ["--gpu", gpu.split(",")[0]]
    env_file = Path(os.environ.get("NEURICO_ENV_FILE", "/app/.env"))
    if env_file.exists():
        cmd += ["--env-file", str(env_file)]
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
