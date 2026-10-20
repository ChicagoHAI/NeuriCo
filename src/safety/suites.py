"""Run deterministic evaluation suites (no coding agent) and normalise their results.

    python src/safety/suites.py --job <id> --out <dir> --evals xstest-safe strong-reject \
        --models qwen2.5-0.5b-instruct [--limit 50] [--gpu 2]

For every (model, eval) pair the script writes ``<out>/<eval>__<model>.json`` in the
``neurico-safety-result/v1`` schema and skips pairs whose result file already
exists (so an interrupted job resumes). It exits 0 only when every pair succeeded.

Runs with the eval venv's python (inspect_ai, inspect_evals, vllm installed).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety.kb import KB, save_json, utc_now  # noqa: E402
from safety.serving import Endpoint, export_provider_env, resolve_api_endpoint, serve  # noqa: E402

SCHEMA = "neurico-safety-result/v1"


def load_env_file(path: Path) -> Dict[str, str]:
    """Read KEY=value lines from NeuriCo's .env (values are never logged)."""
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def judge_entry(kb: KB, judge: Any) -> Optional[Dict[str, Any]]:
    """The models.yaml entry acting as judge: `default` picks the entry with role: judge."""
    if not judge:
        return None
    models = kb.models()
    if judge == "default":
        default = os.environ.get("NEURICO_SAFETY_JUDGE")
        entry = models.get(default) if default else None
        entry = entry or next((m for m in models.values() if m.get("role") == "judge"), None)
        if entry is None:
            raise ValueError("no model with role: judge in catalog/models.yaml")
        return entry
    entry = models.get(judge)
    if entry is None:
        raise ValueError(f"judge model {judge!r} not in catalog/models.yaml")
    return entry


class JudgePool:
    """Serves local (vllm:) judges once per suite job; API judges need no server.

    A local judge is exposed to inspect as ``openai-api/judge/<id>`` with
    ``JUDGE_BASE_URL`` / ``JUDGE_API_KEY`` so it never collides with the subject
    model's ``OPENAI_BASE_URL``.
    """

    def __init__(self, kb: KB, *, gpu: Optional[str], log_dir: Path, hf_home: str):
        self.kb, self.gpu, self.log_dir, self.hf_home = kb, gpu, log_dir, hf_home
        self.servers: Dict[str, Any] = {}

    def resolve(self, judge: Any) -> tuple[Optional[str], Dict[str, str]]:
        entry = judge_entry(self.kb, judge)
        if entry is None:
            return None, {}
        if not str(entry["access"]).startswith("vllm:"):
            return resolve_api_endpoint(entry).inspect_model, {}
        server = self.servers.get(entry["id"])
        if server is None:
            server = serve(entry, gpu=self.gpu, python=sys.executable, log_dir=self.log_dir, hf_home=self.hf_home)
            self.servers[entry["id"]] = server
        return f"openai-api/judge/{entry['id']}", {"JUDGE_BASE_URL": server.base_url, "JUDGE_API_KEY": "local"}

    def stop(self) -> None:
        for server in self.servers.values():
            server.stop()
        self.servers.clear()


def inspect_command(eval_entry: Dict[str, Any], endpoint: Endpoint, log_dir: Path, limit: Optional[int],
                    judge: Optional[str], max_connections: int) -> List[str]:
    runner = str(eval_entry["runner"])
    kind, _, task = runner.partition(":")
    if kind == "inspect":
        target = f"inspect_evals/{task}"
    elif kind == "inspect-file":
        # <path relative to the NeuriCo project root>@<task name>
        path, _, name = task.partition("@")
        target = f"{Path(__file__).resolve().parents[2] / path}@{name}" if name else str(Path(__file__).resolve().parents[2] / path)
    else:
        raise ValueError(f"unsupported runner {runner!r}")
    cmd = [sys.executable, "-m", "inspect_ai", "eval", target,
           "--model", endpoint.inspect_model, "--log-dir", str(log_dir), "--log-format", "json",
           "--display", "plain", "--max-connections", str(max_connections)]
    if limit:
        cmd += ["--limit", str(limit)]
    for key, value in (eval_entry.get("task_args") or {}).items():
        cmd += ["-T", f"{key}={value}"]
    if judge and eval_entry.get("judge_arg"):
        cmd += ["-T", f"{eval_entry['judge_arg']}={judge}"]
    for key, value in (eval_entry.get("model_args") or {}).items():
        cmd += ["-M", f"{key}={value}"]
    return cmd


def summarise_log(log_path: Path) -> Dict[str, Any]:
    data = json.loads(log_path.read_text(encoding="utf-8"))
    metrics: Dict[str, Any] = {}
    for score in (data.get("results") or {}).get("scores") or []:
        prefix = score.get("name", "score")
        for name, metric in (score.get("metrics") or {}).items():
            key = name if len(data["results"]["scores"]) == 1 else f"{prefix}/{name}"
            metrics[key] = metric.get("value")
    items = []
    for sample in data.get("samples") or []:
        scores = sample.get("scores") or {}
        first = next(iter(scores.values()), {}) if scores else {}
        items.append({"id": sample.get("id"), "epoch": sample.get("epoch"),
                      "value": first.get("value"), "answer": (first.get("answer") or "")[:200]})
    stats = data.get("stats") or {}
    return {
        "status": data.get("status"),
        "metrics": metrics,
        "n": len(items),
        "per_item": items,
        "model_usage": stats.get("model_usage"),
        "started_at": stats.get("started_at"),
        "completed_at": stats.get("completed_at"),
        "error": (data.get("error") or {}).get("message") if data.get("error") else None,
    }


def newest_log(log_dir: Path, before: set) -> Optional[Path]:
    logs = [p for p in log_dir.glob("*.json") if p not in before]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def run_pair(kb: KB, job: str, out_dir: Path, eval_entry: Dict[str, Any], model_entry: Dict[str, Any],
             endpoint: Endpoint, env: Dict[str, str], limit: Optional[int], max_connections: int,
             judges: "JudgePool") -> Dict[str, Any]:
    result_path = out_dir / f"{eval_entry['id']}__{model_entry['id']}.json"
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") == "success":
            print(f"skip {result_path.name}: already done", flush=True)
            return existing
    log_dir = out_dir / "inspect_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    judge, judge_env = judges.resolve(eval_entry.get("judge"))
    cmd = inspect_command(eval_entry, endpoint, log_dir, limit, judge, max_connections)
    before = set(log_dir.glob("*.json"))
    started = utc_now()
    t0 = time.time()
    run_env = dict(env)
    run_env.update(endpoint.env())
    run_env.update(judge_env)
    print(f"run  {eval_entry['id']} x {model_entry['id']}: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out_dir / "inspect_logs" / f"{eval_entry['id']}__{model_entry['id']}.stdout.txt").write_text(proc.stdout)
    log_path = newest_log(log_dir, before)
    record: Dict[str, Any] = {
        "schema": SCHEMA, "job": job, "eval_id": eval_entry["id"], "category": eval_entry.get("category"),
        "model_id": model_entry["id"], "model_access": model_entry.get("access"),
        "runner": eval_entry["runner"], "task_args": eval_entry.get("task_args") or {},
        "judge": judge, "limit": limit, "command": cmd, "started": started, "finished": utc_now(),
        "duration_s": round(time.time() - t0, 1), "inspect_log": str(log_path) if log_path else None,
        "versions": versions(), "status": "failed", "metrics": {}, "n": 0, "per_item": [],
        "error": None,
    }
    if proc.returncode != 0 and not log_path:
        record["error"] = f"inspect exited {proc.returncode}: {proc.stdout[-2000:]}"
    elif log_path:
        summary = summarise_log(log_path)
        record.update({k: v for k, v in summary.items() if k != "status"})
        record["status"] = "success" if summary["status"] == "success" and not summary["error"] else "failed"
        if summary["error"]:
            record["error"] = summary["error"]
        if proc.returncode != 0 and record["status"] == "success":
            record["status"] = "failed"
            record["error"] = f"inspect exited {proc.returncode}: {proc.stdout[-2000:]}"
    save_json(result_path, record)
    print(f"{record['status']:7} {result_path.name} metrics={record['metrics']}", flush=True)
    return record


def versions() -> Dict[str, str]:
    out = {}
    for name in ("inspect_ai", "inspect_evals", "vllm", "torch", "transformers"):
        try:
            out[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001
            out[name] = "n/a"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--evals", nargs="+", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--gpu", default=os.environ.get("CUDA_VISIBLE_DEVICES") or None)
    parser.add_argument("--max-connections", type=int, default=16)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[2] / ".env")
    args = parser.parse_args()

    kb = KB()
    evals, models = kb.evals(), kb.models()
    missing = [e for e in args.evals if e not in evals] + [m for m in args.models if m not in models]
    if missing:
        print(f"unknown catalog ids: {missing}", file=sys.stderr)
        return 2
    env = os.environ.copy()
    for key, value in load_env_file(args.env_file).items():
        env.setdefault(key, value)
    export_provider_env(env)
    env.setdefault("HF_HOME", os.environ.get("HF_HOME", "/data/hypogenicai/hf_cache"))
    args.out.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {"job": args.job, "started": utc_now(), "pairs": []}
    failures = 0
    judges = JudgePool(kb, gpu=args.gpu, log_dir=args.out / "serving", hf_home=env["HF_HOME"])
    for model_id in args.models:
        model_entry = models[model_id]
        server = None
        try:
            if str(model_entry["access"]).startswith("vllm:"):
                server = serve(model_entry, gpu=args.gpu, python=sys.executable, log_dir=args.out / "serving",
                               hf_home=env["HF_HOME"])
                endpoint = server.endpoint()
            else:
                endpoint = resolve_api_endpoint(model_entry)
            for eval_id in args.evals:
                record = run_pair(kb, args.job, args.out, evals[eval_id], model_entry, endpoint, env,
                                  args.limit, args.max_connections, judges)
                summary["pairs"].append({"eval": eval_id, "model": model_id, "status": record["status"],
                                         "metrics": record["metrics"], "duration_s": record["duration_s"]})
                failures += record["status"] != "success"
        except Exception as e:  # noqa: BLE001
            failures += 1
            summary["pairs"].append({"model": model_id, "status": "failed", "error": f"{type(e).__name__}: {e}"})
            print(f"failed  model {model_id}: {type(e).__name__}: {e}", flush=True)
        finally:
            if server:
                server.stop()
    judges.stop()
    summary["finished"] = utc_now()
    summary["failures"] = failures
    save_json(args.out / "summary.json", summary)
    print(f"suite {args.job}: {len(summary['pairs'])} pair(s), {failures} failure(s)", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
