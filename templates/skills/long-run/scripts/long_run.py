#!/usr/bin/env python3
"""Registry-backed launcher for long-running experiment commands.

Every long command (training, sweeps, large evals) runs detached under a
named job so it survives tool timeouts and session interruptions. The
registry at .neurico/long_run/jobs.json is the single source of truth for
what is still running; a phase must not end while it lists a live job.

Subcommands:
    start  --name NAME -- CMD...   Launch CMD detached, register the job, return immediately
    wait   --name NAME [--timeout N]  Block until the job finishes (exit 0/1) or N seconds pass (exit 124)
    status [--name NAME]           Show one job or the whole registry
    stop   --name NAME             Kill a running job and record it as killed

Exit codes for `wait`: 0 job succeeded, 1 job failed or was killed,
124 still running when --timeout expired (re-run `wait` to keep waiting).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_DIR = Path(".neurico") / "long_run"
POLL_SECONDS = 5
HEARTBEAT_SECONDS = 60
EXIT_STILL_RUNNING = 124


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registry_path() -> Path:
    return REGISTRY_DIR / "jobs.json"


def job_dir(name: str) -> Path:
    return REGISTRY_DIR / name


def load_registry() -> dict:
    try:
        return json.loads(registry_path().read_text())
    except (OSError, ValueError):
        return {"jobs": {}}


def save_registry(reg: dict) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = registry_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2) + "\n")
    tmp.replace(registry_path())


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def last_log_line(log_file: Path, max_chars: int = 120) -> str:
    try:
        with log_file.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            lines = [ln for ln in fh.read().decode(errors="replace").splitlines() if ln.strip()]
        return lines[-1][:max_chars] if lines else "(no output yet)"
    except OSError:
        return "(log unavailable)"


def sanitize_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    if not cleaned:
        sys.exit("error: --name must contain alphanumeric characters")
    return cleaned


def finalize(reg: dict, name: str) -> dict:
    """Resolve a job's final status from its exit_code file. Idempotent."""
    job = reg["jobs"][name]
    if job["status"] != "running":
        return job
    exit_file = job_dir(name) / "exit_code"
    if exit_file.exists():
        try:
            code = int(exit_file.read_text().strip())
        except ValueError:
            code = -1
        job["exit_code"] = code
        job["status"] = "succeeded" if code == 0 else "failed"
    elif not pid_alive(job["pid"]):
        # Process gone without writing an exit code: killed externally
        # (OOM, docker restart, manual kill)
        job["exit_code"] = None
        job["status"] = "killed"
    if job["status"] != "running":
        job["finished_at"] = now_utc()
        save_registry(reg)
        (job_dir(name) / "job.json").write_text(json.dumps(job, indent=2) + "\n")
    return job


def cmd_start(args: argparse.Namespace) -> int:
    name = sanitize_name(args.name)
    command = " ".join(args.command)
    if not command:
        sys.exit("error: no command given after --")

    reg = load_registry()
    existing = reg["jobs"].get(name)
    if existing and finalize(reg, name)["status"] == "running":
        sys.exit(f"error: job '{name}' is already running (pid {existing['pid']}). "
                 f"Use `wait --name {name}` to attach or pick another name.")

    jdir = job_dir(name)
    jdir.mkdir(parents=True, exist_ok=True)
    log_file = jdir / "run.log"
    exit_file = jdir / "exit_code"
    exit_file.unlink(missing_ok=True)

    # start_new_session detaches the job from this process group, so it
    # survives tool timeouts and the end of the agent session. The command
    # runs in a subshell so an `exit N` inside it cannot skip the exit_code
    # write that `wait` relies on.
    wrapped = f"( {command} ); echo $? > '{exit_file}'"
    with log_file.open("w") as log_fh:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", wrapped],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=os.getcwd(),
        )

    reg["jobs"][name] = {
        "name": name,
        "command": command,
        "pid": proc.pid,
        "status": "running",
        "exit_code": None,
        "log": str(log_file),
        "started_at": now_utc(),
        "finished_at": None,
    }
    save_registry(reg)
    print(f"[long-run] started '{name}' (pid {proc.pid})")
    print(f"[long-run] log: {log_file}")
    print(f"[long-run] next: python {sys.argv[0]} wait --name {name} --timeout 240")
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    name = sanitize_name(args.name)
    reg = load_registry()
    if name not in reg["jobs"]:
        sys.exit(f"error: no job named '{name}' in the registry")

    deadline = time.time() + args.timeout if args.timeout > 0 else None
    last_beat = 0.0
    started = time.time()
    while True:
        job = finalize(reg, name)
        if job["status"] != "running":
            line = last_log_line(Path(job["log"]))
            print(f"[long-run] '{name}' {job['status']} (exit {job['exit_code']}) | last: {line}")
            print(f"[long-run] full log: {job['log']}")
            return 0 if job["status"] == "succeeded" else 1
        if deadline and time.time() >= deadline:
            print(f"[long-run] '{name}' still running after {int(time.time() - started)}s. "
                  f"Re-run `wait --name {name}` to keep waiting. Do NOT end the session.")
            return EXIT_STILL_RUNNING
        if time.time() - last_beat >= HEARTBEAT_SECONDS:
            elapsed = int(time.time() - started)
            print(f"[long-run] '{name}' running {elapsed // 60}m{elapsed % 60:02d}s "
                  f"| last: {last_log_line(Path(job['log']))}", flush=True)
            last_beat = time.time()
        time.sleep(POLL_SECONDS)


def cmd_status(args: argparse.Namespace) -> int:
    reg = load_registry()
    if not reg["jobs"]:
        print("[long-run] registry empty: no jobs recorded")
        return 0
    names = [sanitize_name(args.name)] if args.name else list(reg["jobs"])
    live = 0
    for name in names:
        if name not in reg["jobs"]:
            sys.exit(f"error: no job named '{name}' in the registry")
        job = finalize(reg, name)
        live += job["status"] == "running"
        print(f"{job['status']:>9}  {name}  pid={job['pid']}  started={job['started_at']}"
              f"  exit={job['exit_code']}")
    if live:
        print(f"[long-run] {live} job(s) still running. The phase is NOT done.")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    name = sanitize_name(args.name)
    reg = load_registry()
    if name not in reg["jobs"]:
        sys.exit(f"error: no job named '{name}' in the registry")
    job = finalize(reg, name)
    if job["status"] != "running":
        print(f"[long-run] '{name}' already {job['status']}")
        return 0
    try:
        os.killpg(os.getpgid(job["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    time.sleep(1)
    job = finalize(reg, name)
    if job["status"] == "running":
        job["status"] = "killed"
        job["finished_at"] = now_utc()
        save_registry(reg)
    print(f"[long-run] '{name}' stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_start = sub.add_parser("start", help="launch a command detached and register it")
    p_start.add_argument("--name", required=True, help="short job name, e.g. train_lora")
    p_start.add_argument("command", nargs=argparse.REMAINDER,
                         help="the command to run, after --")

    p_wait = sub.add_parser("wait", help="block until a job finishes or --timeout expires")
    p_wait.add_argument("--name", required=True)
    p_wait.add_argument("--timeout", type=int, default=240,
                        help="seconds to wait before returning 124 (0 = wait forever)")

    p_status = sub.add_parser("status", help="show job status")
    p_status.add_argument("--name", default=None)

    p_stop = sub.add_parser("stop", help="kill a running job")
    p_stop.add_argument("--name", required=True)

    args = parser.parse_args()
    if args.subcommand == "start" and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    handlers = {"start": cmd_start, "wait": cmd_wait, "status": cmd_status, "stop": cmd_stop}
    return handlers[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
