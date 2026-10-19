#!/usr/bin/env python3
"""Command-line entry point for the NeuriCo safety engine (host side).

    uv run python src/cli/safety.py init
    uv run python src/cli/safety.py enqueue-suite --evals xstest-safe strong-reject --models qwen2.5-0.5b-instruct
    uv run python src/cli/safety.py enqueue-idea ideas/safety/probe.yaml --kind optimise --provider claude
    uv run python src/cli/safety.py start --campaign qwen-small-pipeline-test --gpus 2
    uv run python src/cli/safety.py status
    uv run python src/cli/safety.py stop
    uv run python src/cli/safety.py plan --campaign qwen-small-pipeline-test
    uv run python src/cli/safety.py digest
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety.jobs import JobSpec, Queue  # noqa: E402
from safety.kb import KB, PROJECT_ROOT, load_json, save_yaml  # noqa: E402

ENGINE_TEMPLATE = {
    "daemon": {
        "gpus": [], "gpu_memory_gb": 48, "max_neurico_jobs": 1, "max_suite_jobs": 1,
        "stall_minutes": 45, "retries": 2, "poll_seconds": 30, "min_pending": 2,
        "planner_interval_hours": 6, "planner_provider": "claude", "planner_model": None,
        "eval_python": "/data/hypogenicai/safety_venv/bin/python",
        "hf_cache": "/data/hypogenicai/hf_cache",
    }
}


def cmd_init(args: argparse.Namespace) -> int:
    kb = KB()
    kb.ensure_layout()
    if not kb.engine_config_file.exists():
        save_yaml(kb.engine_config_file, ENGINE_TEMPLATE)
        print(f"wrote {kb.engine_config_file}")
    print(f"knowledge base ready at {kb.root}")
    return 0


def cmd_enqueue_suite(args: argparse.Namespace) -> int:
    kb = KB()
    queue = Queue(kb)
    title = args.title or f"suite {' '.join(args.evals)} on {' '.join(args.models)}"
    models = kb.models()
    gpu_gb = args.gpu_gb
    if gpu_gb is None:
        gpu_gb = max((float(models.get(m, {}).get("gpu_memory_gb", 0)) for m in args.models), default=0.0)
    spec = JobSpec(id=queue.new_id("suite", title), kind="suite", title=title, campaign=args.campaign or "",
                   priority=args.priority, evals=args.evals, models=args.models, limit=args.limit,
                   gpu_memory_gb=gpu_gb, created_by="human")
    path = queue.add(spec)
    print(f"queued {spec.id} -> {path}")
    return 0


def cmd_enqueue_idea(args: argparse.Namespace) -> int:
    kb = KB()
    queue = Queue(kb)
    idea = Path(args.idea_file).resolve()
    if not idea.exists():
        print(f"idea file not found: {idea}", file=sys.stderr)
        return 2
    try:
        rel = str(idea.relative_to(PROJECT_ROOT))
    except ValueError:
        rel = str(idea)
    title = args.title or idea.stem.replace("_", " ")
    spec = JobSpec(id=queue.new_id(args.kind, title), kind=args.kind, title=title, campaign=args.campaign or "",
                   priority=args.priority, idea_file=rel, provider=args.provider, model=args.model,
                   autoresearch_iterations=args.iterations, write_paper=args.write_paper,
                   github=not args.no_github, private=args.private, gpu_memory_gb=args.gpu_gb or 0.0,
                   created_by="human")
    path = queue.add(spec)
    print(f"queued {spec.id} -> {path}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    from safety.daemon import Daemon
    kb = KB()
    kb.ensure_layout()
    overrides = {}
    if args.no_plan:
        overrides["planner_enabled"] = False
    if args.gpus is not None:
        overrides["gpus"] = [g.strip() for g in args.gpus.split(",") if g.strip()]
    for name in ("max_neurico_jobs", "max_suite_jobs", "stall_minutes", "retries", "poll_seconds"):
        value = getattr(args, name, None)
        if value is not None:
            overrides[name] = value
    state = load_json(kb.state_file) or {}
    pid = (state.get("daemon") or {}).get("pid")
    if pid and pid != os.getpid() and _alive(pid) and not args.force:
        print(f"a daemon already appears to be running (pid {pid}); use --force to start anyway")
        return 1
    daemon = Daemon(kb, campaign=args.campaign, config=overrides)
    return daemon.run(once=args.once)


def cmd_status(args: argparse.Namespace) -> int:
    kb = KB()
    status = kb.logs_dir / "status.md"
    if status.exists():
        print(status.read_text(encoding="utf-8"))
    else:
        queue = Queue(kb)
        for state in ("pending", "running", "done", "failed"):
            jobs = queue.list(state)
            print(f"{state}: {len(jobs)}")
            for spec in jobs:
                print(f"  {spec.id} [{spec.kind}, p{spec.priority}] {spec.title}")
    state = load_json(kb.state_file) or {}
    daemon = state.get("daemon") or {}
    if daemon.get("pid"):
        alive = _alive(daemon["pid"])
        print(f"daemon pid {daemon['pid']} ({'alive' if alive else 'not running'}), heartbeat {daemon.get('heartbeat')}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    kb = KB()
    state = load_json(kb.state_file) or {}
    pid = (state.get("daemon") or {}).get("pid")
    if not pid or not _alive(pid):
        print("no running daemon")
        return 0
    os.kill(pid, signal.SIGTERM)
    print(f"sent SIGTERM to daemon pid {pid}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from safety.planner import run_planner
    kb = KB()
    result = run_planner(kb, args.campaign, provider=args.provider, model=args.model, dry_run=args.dry_run)
    print(result)
    return 0 if result.get("ok", True) else 1


def cmd_digest(args: argparse.Namespace) -> int:
    from safety.digest import write_digest
    path = write_digest(KB(), days=args.days)
    print(f"wrote {path}")
    return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p = sub.add_parser("enqueue-suite")
    p.add_argument("--evals", nargs="+", required=True)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--priority", type=int, default=50)
    p.add_argument("--campaign")
    p.add_argument("--title")
    p.add_argument("--gpu-gb", type=float)
    p.set_defaults(func=cmd_enqueue_suite)

    p = sub.add_parser("enqueue-idea")
    p.add_argument("idea_file")
    p.add_argument("--kind", choices=("research", "optimise", "explore", "validate"), default="research")
    p.add_argument("--provider", default="claude")
    p.add_argument("--model")
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--write-paper", action="store_true")
    p.add_argument("--no-github", action="store_true")
    p.add_argument("--private", action="store_true")
    p.add_argument("--priority", type=int, default=50)
    p.add_argument("--campaign")
    p.add_argument("--title")
    p.add_argument("--gpu-gb", type=float)
    p.set_defaults(func=cmd_enqueue_idea)

    p = sub.add_parser("start")
    p.add_argument("--campaign")
    p.add_argument("--gpus", help="comma-separated GPU ids the engine may use")
    p.add_argument("--max-neurico-jobs", type=int)
    p.add_argument("--max-suite-jobs", type=int)
    p.add_argument("--stall-minutes", type=int)
    p.add_argument("--retries", type=int)
    p.add_argument("--poll-seconds", type=int)
    p.add_argument("--once", action="store_true", help="run one scheduling tick and exit")
    p.add_argument("--no-plan", action="store_true", help="never launch the planner agent")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_start)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("stop").set_defaults(func=cmd_stop)

    p = sub.add_parser("plan")
    p.add_argument("--campaign", required=True)
    p.add_argument("--provider", default="claude")
    p.add_argument("--model")
    p.add_argument("--dry-run", action="store_true", help="write the prompt and exit without launching an agent")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("digest")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_digest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
