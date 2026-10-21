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
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety.kb import KB, save_json, utc_now  # noqa: E402
from safety.serving import Endpoint, export_provider_env, resolve_api_endpoint, serve  # noqa: E402

SCHEMA = "neurico-safety-result/v1"

# Catalog roles a `judges:` policy (engine.yaml) may choose between, unless it names its own.
DEFAULT_JUDGE_ROLES = ("judge", "judge-api")
# Environment that makes an API judge lane usable; Azure also needs a base URL or resource
# and, when AZURE_OPENAI_DEPLOYMENTS is set, the deployment on that list. `local` (vllm:) is
# always usable. Lanes are the access schemes of catalog/models.yaml, nothing model-specific.
JUDGE_LANE_KEYS = {
    "azure": ("AZURE_OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY",),
}


def judge_lane(entry: Mapping[str, Any]) -> str:
    """The policy name of an entry's access scheme: ``local`` for vllm:, else the scheme."""
    scheme = str(entry.get("access") or "").partition(":")[0]
    return "local" if scheme == "vllm" else scheme


def judge_lane_available(lane: str, target: str, env: Mapping[str, str]) -> bool:
    if lane == "local":
        return True
    if not any(env.get(name) for name in JUDGE_LANE_KEYS.get(lane, ())):
        return False
    if lane == "azure":
        if not (env.get("AZURE_OPENAI_BASE_URL") or env.get("AZURE_FOUNDRY_RESOURCE")):
            return False
        allowed = [d.strip() for d in (env.get("AZURE_OPENAI_DEPLOYMENTS") or "").split(",") if d.strip()]
        return not allowed or target in allowed
    return True


def preferred_judge_entry(kb: KB, policy: Mapping[str, Any],
                          env: Optional[Mapping[str, str]] = None) -> Optional[Dict[str, Any]]:
    """The first catalog judge whose lane is usable, in the policy's ``prefer`` order.

    ``policy`` is the ``judges:`` block of ``safety_kb/engine.yaml``::

        judges:
          prefer: [azure, local]        # access schemes; `local` = vllm:
          roles: [judge, judge-api]     # optional: catalog roles that count as judges

    Returns None when the policy names no lane that is both in the catalog and
    usable, so the caller falls back to the plain ``role: judge`` default.
    """
    env = os.environ if env is None else env
    prefer = [str(lane) for lane in (policy.get("prefer") or [])]
    if not prefer:
        return None
    roles = tuple(policy.get("roles") or DEFAULT_JUDGE_ROLES)
    candidates = [m for m in kb.models().values() if m.get("role") in roles and m.get("access")]
    for lane in prefer:
        for entry in candidates:
            if judge_lane(entry) != lane:
                continue
            target = str(entry["access"]).partition(":")[2]
            if judge_lane_available(lane, target, env):
                return entry
    return None


# Concurrency for API-served subjects (local servers report their own KV-cache bound).
DEFAULT_MAX_CONNECTIONS = 16

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

    def __init__(self, kb: KB, *, gpu: Optional[str], log_dir: Path, hf_home: str,
                 env: Optional[Mapping[str, str]] = None, policy: Optional[Mapping[str, Any]] = None):
        self.kb, self.gpu, self.log_dir, self.hf_home = kb, gpu, log_dir, hf_home
        self.env: Mapping[str, str] = os.environ if env is None else env
        # `judges:` in engine.yaml (lane preference); absent = today's role: judge default
        self.policy: Mapping[str, Any] = dict(policy if policy is not None else (kb.engine_config().get("judges") or {}))
        self.servers: Dict[str, Any] = {}
        self.chosen: Dict[str, str] = {}

    def entry_for(self, judge: Any) -> Optional[Dict[str, Any]]:
        """``default`` follows NEURICO_SAFETY_JUDGE, then the ``judges.prefer`` policy, then role: judge."""
        if judge == "default" and not self.env.get("NEURICO_SAFETY_JUDGE"):
            entry = preferred_judge_entry(self.kb, self.policy, self.env)
            if entry is not None:
                return entry
        return judge_entry(self.kb, judge)

    def resolve(self, judge: Any) -> tuple[Optional[str], Dict[str, str]]:
        entry = self.entry_for(judge)
        if entry is None:
            return None, {}
        if self.chosen.get(str(judge)) != entry["id"]:
            self.chosen[str(judge)] = entry["id"]
            print(f"judge {judge!r} -> {entry['id']} ({judge_lane(entry)})", flush=True)
        if not str(entry["access"]).startswith("vllm:"):
            # API judges need no server; an Azure judge also needs AZURE_BASE_URL / AZURE_API_KEY
            # in inspect's environment (its endpoint env; empty for the key-only providers).
            endpoint = resolve_api_endpoint(entry, dict(self.env))
            return endpoint.inspect_model, endpoint.env()
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
    stdout_path = out_dir / "inspect_logs" / f"{eval_entry['id']}__{model_entry['id']}.stdout.txt"
    with stdout_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, env=run_env, stdout=fh, stderr=subprocess.STDOUT, text=True)
        waited = 0
        while True:
            try:
                proc.wait(timeout=60)
                break
            except subprocess.TimeoutExpired:
                waited += 60
                # Heartbeat for the daemon's stall watchdog: long evals print nothing here otherwise.
                print(f"     {eval_entry['id']} x {model_entry['id']} running {waited // 60} min", flush=True)
    proc_stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
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
        record["error"] = f"inspect exited {proc.returncode}: {proc_stdout[-2000:]}"
    elif log_path:
        summary = summarise_log(log_path)
        record.update({k: v for k, v in summary.items() if k != "status"})
        record["status"] = "success" if summary["status"] == "success" and not summary["error"] else "failed"
        if summary["error"]:
            record["error"] = summary["error"]
        if proc.returncode != 0 and record["status"] == "success":
            record["status"] = "failed"
            record["error"] = f"inspect exited {proc.returncode}: {proc_stdout[-2000:]}"
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
    parser.add_argument("--max-connections", type=int, default=None,
                        help="concurrent requests per eval; default: what the served model reports it can hold "
                             f"(KV-cache bound), else {DEFAULT_MAX_CONNECTIONS} for API models")
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
    judges = JudgePool(kb, gpu=args.gpu, log_dir=args.out / "serving", hf_home=env["HF_HOME"], env=env)
    servers: List[Any] = []  # every vLLM server this process started, stopped on SIGTERM/SIGINT

    def _terminate(signum, frame):  # noqa: ARG001
        # The daemon stops a suite with SIGTERM to its process group; the vLLM servers live in
        # their own sessions, so stop them here or they keep the GPU until the allocation ends.
        for server in servers:
            server.stop()
        judges.stop()
        sys.exit(128 + signum)

    import signal
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    for model_id in args.models:
        model_entry = models[model_id]
        server = None
        try:
            if str(model_entry["access"]).startswith("vllm:"):
                server = serve(model_entry, gpu=args.gpu, python=sys.executable, log_dir=args.out / "serving",
                               hf_home=env["HF_HOME"])
                servers.append(server)
                endpoint = server.endpoint()
            else:
                endpoint = resolve_api_endpoint(model_entry)
            max_connections = (args.max_connections or (server.max_concurrency if server else None)
                               or DEFAULT_MAX_CONNECTIONS)
            print(f"max connections for {model_id}: {max_connections}", flush=True)
            for eval_id in args.evals:
                record = run_pair(kb, args.job, args.out, evals[eval_id], model_entry, endpoint, env,
                                  args.limit, max_connections, judges)
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
                servers.remove(server)
    judges.stop()
    summary["finished"] = utc_now()
    summary["failures"] = failures
    save_json(args.out / "summary.json", summary)
    print(f"suite {args.job}: {len(summary['pairs'])} pair(s), {failures} failure(s)", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
