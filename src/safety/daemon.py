"""Scheduler daemon for the safety engine.

Runs on the host (it launches ``./neurico`` containers and host-side suite
scripts). One loop iteration:

1. reconcile ``queue/state.json`` with reality (process alive? log growing?);
2. watchdog: kill and requeue jobs whose log has stalled or whose process died;
3. fill free slots with the highest-priority approved pending jobs that fit;
4. ingest finished jobs into the knowledge base (runs/, findings/, results/);
5. write ``logs/safety/status.md`` + ``status.json`` and append ``events.log``;
6. when the pending queue is short, schedule a planner run.

All durable state is on disk, so the daemon can be restarted at any time: it
re-adopts running jobs by process id and container name.

Usage (host):
    uv run python src/cli/safety.py start [--campaign NAME] [--once]
    uv run python src/cli/safety.py status
    uv run python src/cli/safety.py stop
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.jobs import JobSpec, Queue
from safety.kb import KB, PROJECT_ROOT, append_line, load_json, load_yaml, save_json, utc_now

NEURICO = PROJECT_ROOT / "neurico"
SIGKILL_GRACE_SECONDS = 15.0


def host_mode() -> bool:
    """True when ./neurico runs natively (docker/host.sh) instead of in Docker."""
    return os.environ.get("NEURICO_MODE", "").lower() == "host"


def host_job_pgid(name: str) -> Optional[int]:
    """Process group of a host-mode job, from the launcher's logs/host-jobs/<name>.pid."""
    jobs_dir = Path(os.environ.get("NEURICO_HOST_JOBS_DIR") or PROJECT_ROOT / "logs" / "host-jobs")
    try:
        return int((jobs_dir / f"{name}.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def killpg_quiet(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def escalate_sigkill(pgids: List[int], delay: float = SIGKILL_GRACE_SECONDS) -> None:
    """SIGKILL the groups that are still alive after ``delay`` seconds (non-blocking)."""
    if not pgids:
        return

    def _kill() -> None:
        for pgid in pgids:
            killpg_quiet(pgid, signal.SIGKILL)

    timer = threading.Timer(delay, _kill)
    timer.daemon = True
    timer.start()


DEFAULT_CONFIG: Dict[str, Any] = {
    "gpus": [],                    # e.g. ["2"]; empty = CPU/API only for suites, all GPUs for containers
    "gpu_memory_gb": 48,           # memory per listed GPU
    "max_neurico_jobs": 1,         # concurrent NeuriCo containers
    "max_suite_jobs": 1,           # concurrent suite jobs
    "stall_minutes": 45,           # no log growth for this long -> job is stalled
    "retries": 2,                  # per job
    "retry_wait_seconds": 120,
    "poll_seconds": 30,
    "min_pending": 2,              # schedule the planner when fewer approved jobs are pending
    "planner_interval_hours": 6,   # never run the planner more often than this
    "planner_enabled": True,
    "crawler_enabled": True,       # sweep catalog/sources.yaml into inbox/ (needs that file to exist)
    "crawl_interval_hours": 24,
    "planner_provider": "claude",
    "planner_model": None,
    "eval_python": "/data/hypogenicai/safety_venv/bin/python",
    "hf_cache": "/data/hypogenicai/hf_cache",
    "workspace_dir": None,         # defaults to config/workspace.yaml
    "resource_finder_timeout": 0,
    "experiment_timeout": 0,
    "paper_timeout": 0,
    "openrouter_daily_cap_usd": None,
}


@dataclass
class JobRuntime:
    """Mutable runtime record kept in state.json, keyed by job id."""
    id: str
    kind: str
    state: str = "pending"
    attempts: int = 0
    gpu: Optional[str] = None
    gpu_memory_gb: float = 0.0
    pid: Optional[int] = None
    container: Optional[str] = None
    log_file: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_progress_at: Optional[str] = None
    last_log_size: int = 0
    return_code: Optional[int] = None
    idea_id: Optional[str] = None
    workspace: Optional[str] = None
    github_url: Optional[str] = None
    run_id: Optional[str] = None
    note: str = ""
    commands: List[str] = field(default_factory=list)


class Daemon:
    def __init__(self, kb: KB, campaign: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        self.kb = kb
        self.queue = Queue(kb)
        self.campaign = campaign
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(kb.engine_config().get("daemon") or {})
        if config:
            self.config.update(config)
        self.state: Dict[str, Any] = load_json(kb.state_file) or {"jobs": {}, "daemon": {}, "planner": {}}
        self.lock = threading.Lock()
        self.processes: Dict[str, subprocess.Popen] = {}
        self.adopted: set = set()
        self.stopping = False
        self.kb.logs_dir.mkdir(parents=True, exist_ok=True)

    # -- state ----------------------------------------------------------------
    def runtime(self, job_id: str, kind: str = "") -> JobRuntime:
        data = self.state["jobs"].get(job_id)
        if data is None:
            data = asdict(JobRuntime(id=job_id, kind=kind))
            self.state["jobs"][job_id] = data
        known = {f for f in JobRuntime.__dataclass_fields__}
        return JobRuntime(**{k: v for k, v in data.items() if k in known})

    def put(self, rt: JobRuntime) -> None:
        self.state["jobs"][rt.id] = asdict(rt)

    def save(self) -> None:
        self.state["daemon"].update({"pid": os.getpid(), "heartbeat": utc_now(), "campaign": self.campaign})
        save_json(self.kb.state_file, self.state)

    def event(self, text: str) -> None:
        line = f"{utc_now()} {text}"
        append_line(self.kb.logs_dir / "events.log", line)
        print(line, flush=True)

    # -- resources ------------------------------------------------------------
    def running(self, kind_filter=None) -> List[JobRuntime]:
        out = []
        for job_id in list(self.state["jobs"]):
            rt = self.runtime(job_id)
            if rt.state == "running" and (kind_filter is None or kind_filter(rt)):
                out.append(rt)
        return out

    def free_gpu(self, needed_gb: float) -> Optional[str]:
        """Least-loaded configured GPU with enough free memory for `needed_gb`."""
        if needed_gb <= 0:
            return None
        used: Dict[str, float] = {g: 0.0 for g in self.config["gpus"]}
        for data in self.state["jobs"].values():
            if data.get("state") == "running" and data.get("gpu") in used:
                used[data["gpu"]] += float(data.get("gpu_memory_gb") or 0)
        for gpu, load in sorted(used.items(), key=lambda kv: kv[1]):
            if load + needed_gb <= float(self.config["gpu_memory_gb"]):
                return gpu
        return None

    def slot_available(self, spec: JobSpec) -> bool:
        if spec.uses_neurico:
            return len(self.running(lambda r: r.kind != "suite")) < int(self.config["max_neurico_jobs"])
        return len(self.running(lambda r: r.kind == "suite")) < int(self.config["max_suite_jobs"])

    # -- launching ------------------------------------------------------------
    def job_log(self, spec: JobSpec) -> Path:
        return self.kb.logs_dir / "jobs" / f"{spec.id}.log"

    def neurico_submit_command(self, spec: JobSpec) -> List[str]:
        cmd = [str(NEURICO), "submit", str(PROJECT_ROOT / spec.idea_file), "--provider", spec.provider]
        if spec.model:
            cmd += ["--model", spec.model]
        if not spec.github:
            cmd.append("--no-github")
        if spec.private:
            cmd.append("--private")
        return cmd

    def neurico_run_command(self, spec: JobSpec, rt: JobRuntime) -> List[str]:
        cmd = [str(NEURICO), "run", rt.idea_id or "<idea_id>", "--provider", spec.provider,
               "--full-permissions",
               "--resource-finder-timeout", str(self.config["resource_finder_timeout"]),
               "--timeout", str(self.config["experiment_timeout"]),
               "--paper-timeout", str(self.config["paper_timeout"])]
        if spec.model:
            cmd += ["--model", spec.model]
        if spec.agent_auth:
            cmd += ["--agent-auth", spec.agent_auth]
        if not spec.github:
            cmd.append("--no-github")
        if spec.write_paper:
            cmd.append("--write-paper")
        if spec.kind == "optimise":
            cmd += ["--autoresearch", "--autoresearch-iterations", str(spec.autoresearch_iterations)]
        return cmd

    def suite_command(self, spec: JobSpec) -> List[str]:
        cmd = [self.config["eval_python"], str(PROJECT_ROOT / "src" / "safety" / "suites.py"),
               "--job", spec.id, "--out", str(self.kb.results_dir / spec.id),
               "--evals", *spec.evals, "--models", *spec.models]
        if spec.limit:
            cmd += ["--limit", str(spec.limit)]
        return cmd

    def spawn(self, spec: JobSpec, rt: JobRuntime, command: List[str], *, named: bool) -> subprocess.Popen:
        env = os.environ.copy()
        env["NEURICO_SAFETY_KB"] = str(self.kb.root)
        env["HF_HOME"] = str(self.config["hf_cache"])
        if self.config.get("models_dir"):
            env["NEURICO_MODELS_DIR"] = str(self.config["models_dir"])
        if rt.gpu is not None:
            env["NEURICO_GPUS"] = rt.gpu
            env["CUDA_VISIBLE_DEVICES"] = rt.gpu
        if self.config.get("hf_cache") and spec.uses_neurico:
            env["NEURICO_HF_CACHE"] = str(self.config["hf_cache"])
        if spec.uses_neurico:
            # parents[1] of <venv>/bin/python; do not resolve() the symlink or we get the interpreter's home
            env["NEURICO_SAFETY_VENV"] = str(Path(self.config["eval_python"]).parents[1])
        if named:
            env["NEURICO_CONTAINER_NAME"] = rt.container or ""
        else:
            env.pop("NEURICO_CONTAINER_NAME", None)
        log_path = Path(rt.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rt.commands.append(" ".join(shlex.quote(c) for c in command))
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n$ {' '.join(command)}\n")
        log = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        with self.lock:
            self.processes[spec.id] = process
        rt.pid = process.pid
        return process

    def launch(self, spec: JobSpec) -> None:
        rt = self.runtime(spec.id, spec.kind)
        if rt.state not in ("pending", "running"):
            # Requeued from failed/done/stopped by hand (YAML moved back to pending): fresh attempts.
            rt.attempts = 0
            rt.started_at = None
            rt.note = f"requeued from {rt.state} at {utc_now()}"
        rt.state = "running"
        rt.started_at = rt.started_at or utc_now()
        rt.last_progress_at = utc_now()
        rt.log_file = str(self.job_log(spec))
        rt.gpu = self.free_gpu(spec.gpu_memory_gb)
        rt.container = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"neurico-safety-{spec.id}")[:60]
        rt.gpu_memory_gb = spec.gpu_memory_gb
        self.put(rt)
        self.queue.move(spec.id, "running")
        self.event(f"START  {spec.id} kind={spec.kind} gpu={rt.gpu or '-'} attempt={rt.attempts + 1}")
        thread = threading.Thread(target=self.run_job, args=(spec,), daemon=True)
        thread.start()

    def run_job(self, spec: JobSpec) -> None:
        """Run one job to completion in its own thread (NeuriCo submit+run, or a suite)."""
        rt = self.runtime(spec.id, spec.kind)
        try:
            if spec.uses_neurico:
                code = self.run_neurico(spec, rt)
            else:
                code = self.run_suite(spec, rt)
        except Exception as e:  # noqa: BLE001 - keep the daemon alive
            append_line(Path(rt.log_file), f"[safety] {type(e).__name__}: {e}")
            code = 1
        with self.lock:
            self.processes.pop(spec.id, None)
        rt = self.runtime(spec.id, spec.kind)
        rt.return_code = code
        rt.finished_at = utc_now()
        rt.pid = None
        if self.stopping and code != 0:
            rt.state = "stopped"
        elif code == 0:
            rt.state = "done"
        else:
            rt.state = "failed"
        self.put(rt)
        self.save()
        self.event(f"{rt.state.upper():6} {spec.id} rc={code} {rt.github_url or rt.workspace or ''}")

    def wait(self, spec: JobSpec, rt: JobRuntime, process: subprocess.Popen) -> int:
        """Wait on a child, updating progress from log growth; return its exit code."""
        log_path = Path(rt.log_file)
        while True:
            try:
                return process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                size = log_path.stat().st_size if log_path.exists() else 0
                current = self.runtime(spec.id, spec.kind)
                if size > current.last_log_size:
                    current.last_log_size = size
                    current.last_progress_at = utc_now()
                    self.put(current)

    def record_outputs(self, rt: JobRuntime) -> None:
        text = Path(rt.log_file).read_text(encoding="utf-8", errors="replace")
        for pattern, attribute in (
            (r"^Idea ID:\s*(\S+)", "idea_id"),
            (r"^\s*(?:Location|Local|📁 Working directory):\s*(\S+)", "workspace"),
            (r"^\s*(?:GitHub|URL):\s*(https://github\.com/\S+)", "github_url"),
        ):
            matches = re.findall(pattern, text, flags=re.MULTILINE)
            if matches:
                setattr(rt, attribute, matches[-1])

    def run_neurico(self, spec: JobSpec, rt: JobRuntime) -> int:
        if not rt.idea_id:
            _make_readable(PROJECT_ROOT / spec.idea_file)  # the container user (uid 1000) must read it
            process = self.spawn(spec, rt, self.neurico_submit_command(spec), named=False)
            self.put(rt)
            code = self.wait(spec, rt, process)
            rt = self.runtime(spec.id, spec.kind)
            self.record_outputs(rt)
            self.put(rt)
            if code != 0 or not rt.idea_id:
                append_line(Path(rt.log_file), "[safety] submit failed or printed no idea ID")
                return code or 1
        offset = Path(rt.log_file).stat().st_size
        process = self.spawn(spec, rt, self.neurico_run_command(spec, rt), named=True)
        self.put(rt)
        code = self.wait(spec, rt, process)
        rt = self.runtime(spec.id, spec.kind)
        self.record_outputs(rt)
        self.put(rt)
        with Path(rt.log_file).open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            tail = fh.read()
        # runner.py exits 0 even when a stage fails; trust its verdict line.
        if code == 0 and "did not complete successfully" in tail:
            return 1
        return code

    def run_suite(self, spec: JobSpec, rt: JobRuntime) -> int:
        process = self.spawn(spec, rt, self.suite_command(spec), named=False)
        self.put(rt)
        return self.wait(spec, rt, process)

    # -- watchdog -------------------------------------------------------------
    def kill_job(self, job_id: str, reason: str) -> None:
        """Stop a job's whole process tree.

        Docker route: ``docker kill <container>`` plus the launcher's group.
        Host mode (``NEURICO_MODE=host`` or no docker binary): the launcher
        recorded the job's process group in ``logs/host-jobs/<name>.pid``;
        that group and the launcher's own group get SIGTERM, then SIGKILL
        after a grace period for agents that ignore SIGTERM.
        """
        rt = self.runtime(job_id)
        groups: List[int] = []
        if rt.container:
            if not host_mode() and shutil.which("docker"):
                subprocess.run(["docker", "kill", rt.container], capture_output=True)
            pgid = host_job_pgid(rt.container)
            if pgid:
                groups.append(pgid)
        process = self.processes.get(job_id)
        if process and process.poll() is None:
            groups.append(process.pid)
        elif rt.pid:
            groups.append(rt.pid)
        for pgid in groups:
            killpg_quiet(pgid, signal.SIGTERM)
        escalate_sigkill(groups)
        append_line(Path(rt.log_file or self.kb.logs_dir / "orphans.log"), f"[safety] killed: {reason}")

    def watchdog(self) -> None:
        stall = float(self.config["stall_minutes"]) * 60
        now = datetime.now(timezone.utc)
        for rt in self.running():
            last = datetime.fromisoformat(rt.last_progress_at or rt.started_at or utc_now())
            alive = rt.id in self.processes or rt.id in self.adopted or bool(rt.pid and _pid_alive(rt.pid))
            if alive and (now - last).total_seconds() > stall:
                self.event(f"STALL  {rt.id}: no log growth for {int((now - last).total_seconds() // 60)} min")
                self.kill_job(rt.id, "stalled")
            elif not alive and rt.id not in self.processes:
                # Adopted from a previous daemon process and gone: treat as failed attempt.
                self.event(f"LOST   {rt.id}: process {rt.pid} is gone")
                rt.state = "failed"
                rt.finished_at = utc_now()
                rt.return_code = rt.return_code if rt.return_code is not None else -1
                self.put(rt)

    def retry_or_fail(self, spec: JobSpec, rt: JobRuntime) -> None:
        if rt.attempts < int(self.config["retries"]) and not self.stopping:
            rt.attempts += 1
            rt.state = "pending"
            rt.pid = None
            rt.note = f"retry {rt.attempts}/{self.config['retries']} at {utc_now()}"
            self.put(rt)
            self.queue.move(spec.id, "pending")
            self.event(f"RETRY  {spec.id} {rt.note}")
            time.sleep(min(float(self.config["retry_wait_seconds"]), 5))
        else:
            self.queue.move(spec.id, "failed")
            self.event(f"GAVEUP {spec.id} after {rt.attempts + 1} attempt(s)")

    # -- ingest ---------------------------------------------------------------
    def ingest_finished(self) -> None:
        from safety.ingest import ingest_job  # local import: keeps daemon importable without extras
        for job_id in list(self.state["jobs"]):
            rt = self.runtime(job_id)
            found = self.queue.find(rt.id)
            if not found or found[0] != "running" or rt.state == "running":
                continue
            spec = JobSpec.from_dict(load_yaml(found[1]))
            if rt.state == "done":
                try:
                    run_id = ingest_job(self.kb, spec, asdict(rt))
                    rt.run_id = run_id
                    self.put(rt)
                    self.refresh_index()
                except Exception as e:  # noqa: BLE001
                    self.event(f"INGEST {spec.id} failed: {type(e).__name__}: {e}")
                self.queue.move(spec.id, "done")
                self.event(f"DONE   {spec.id} run={rt.run_id or '-'}")
            elif rt.state in ("failed", "stopped"):
                if rt.state == "stopped":
                    self.queue.move(spec.id, "pending")
                    rt.state = "pending"
                    self.put(rt)
                else:
                    self.retry_or_fail(spec, rt)

    def refresh_index(self) -> None:
        """Rebuild the SQLite index, the timelines and the anomaly inbox after an ingest."""
        from safety import kbdb
        try:
            kbdb.timeline(self.kb)
            path = kbdb.scan_anomalies(self.kb)
            if path:
                self.event(f"ANOMALY result drift written to {path.name}")
        except Exception as e:  # noqa: BLE001
            self.event(f"INDEX  rebuild failed: {type(e).__name__}: {e}")

    # -- crawler --------------------------------------------------------------
    def maybe_crawl(self) -> None:
        """Run the crawler (no LLM; arXiv, Hugging Face, feeds -> inbox/) once per ``crawl_interval_hours``."""
        if not self.config.get("crawler_enabled", True) or not (self.kb.catalog_dir / "sources.yaml").exists():
            return
        state = self.state.setdefault("crawler", {})
        last = state.get("last_run_at")
        if last:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h < float(self.config.get("crawl_interval_hours", 24)):
                return
        if state.get("running"):
            return
        state.update({"running": True, "last_run_at": utc_now()})
        self.save()

        def _run():
            try:
                from safety.crawler import crawl
                result = crawl(self.kb)
                self.event(f"CRAWL  {result.get('new', 0)} new inbox item(s), {result.get('skipped', 0)} seen, "
                           f"{len(result.get('errors') or [])} source error(s)")
            except Exception as e:  # noqa: BLE001
                self.event(f"CRAWL  failed: {type(e).__name__}: {e}")
            finally:
                self.state.setdefault("crawler", {})["running"] = False
                self.save()

        threading.Thread(target=_run, daemon=True).start()

    # -- planner --------------------------------------------------------------
    def maybe_plan(self) -> None:
        if not self.campaign or not self.config.get("planner_enabled", True):
            return
        pending = len(self.queue.pending_sorted())
        if pending >= int(self.config["min_pending"]):
            return
        last = self.state["planner"].get("last_run_at")
        if last:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h < float(self.config["planner_interval_hours"]):
                return
        if self.state["planner"].get("running"):
            return
        self.state["planner"].update({"running": True, "last_run_at": utc_now()})
        self.save()
        self.event(f"PLAN   queue has {pending} pending job(s); launching planner for campaign {self.campaign}")

        def _run():
            from safety.planner import run_planner
            try:
                result = run_planner(self.kb, self.campaign, provider=self.config["planner_provider"],
                                     model=self.config["planner_model"])
                self.event(f"PLAN   planner proposed {result.get('proposed', 0)} job(s)")
            except Exception as e:  # noqa: BLE001
                self.event(f"PLAN   planner failed: {type(e).__name__}: {e}")
            finally:
                self.state["planner"]["running"] = False
                self.save()

        threading.Thread(target=_run, daemon=True).start()

    # -- status ---------------------------------------------------------------
    def write_status(self) -> None:
        lines = [f"# Safety engine status ({utc_now()})", "",
                 f"campaign: {self.campaign or '-'}  daemon pid: {os.getpid()}", ""]
        for state in ("running", "pending", "done", "failed"):
            jobs = self.queue.list(state)
            lines.append(f"## {state} ({len(jobs)})")
            for spec in jobs[:50]:
                rt = self.runtime(spec.id, spec.kind)
                extra = ""
                if state == "running":
                    extra = f" gpu={rt.gpu or '-'} since {rt.started_at} progress {rt.last_progress_at}"
                elif state in ("done", "failed"):
                    extra = f" rc={rt.return_code} {rt.github_url or rt.workspace or ''}"
                lines.append(f"- {spec.id} [{spec.kind}, p{spec.priority}] {spec.title}{extra}")
            lines.append("")
        text = "\n".join(lines)
        (self.kb.logs_dir / "status.md").write_text(text, encoding="utf-8")
        save_json(self.kb.logs_dir / "status.json", {
            "generated": utc_now(), "campaign": self.campaign,
            "counts": {s: len(self.queue.list(s)) for s in ("pending", "running", "done", "failed")},
            "jobs": self.state["jobs"],
        })

    # -- main loop ------------------------------------------------------------
    def adopt(self) -> None:
        """After a restart, re-attach to running jobs whose process is still alive; fail the rest."""
        for rt in self.running():
            if rt.pid and _pid_alive(rt.pid):
                self.event(f"ADOPT  {rt.id} pid={rt.pid} still running")
                threading.Thread(target=self.wait_adopted, args=(rt.id,), daemon=True).start()
            else:
                self.event(f"LOST   {rt.id}: not running after daemon restart")
                rt.state = "failed"
                rt.return_code = -1
                rt.finished_at = utc_now()
                self.put(rt)

    def wait_adopted(self, job_id: str) -> None:
        """Poll an adopted process; infer its outcome from its outputs once it exits."""
        self.adopted.add(job_id)
        try:
            rt = self.runtime(job_id)
            log_path = Path(rt.log_file) if rt.log_file else None
            while rt.pid and _pid_alive(rt.pid) and not self.stopping:
                time.sleep(10)
                if log_path and log_path.exists():
                    size = log_path.stat().st_size
                    current = self.runtime(job_id)
                    if size > current.last_log_size:
                        current.last_log_size = size
                        current.last_progress_at = utc_now()
                        self.put(current)
            rt = self.runtime(job_id)
            if self.stopping:
                return
            ok = False
            if rt.kind == "suite":
                summary = load_json(self.kb.results_dir / job_id / "summary.json") or {}
                ok = summary.get("failures") == 0
            elif log_path and log_path.exists():
                self.record_outputs(rt)
                ok = "did not complete successfully" not in log_path.read_text(encoding="utf-8", errors="replace")[-20000:]
            rt.state = "done" if ok else "failed"
            rt.return_code = 0 if ok else -1
            rt.finished_at = utc_now()
            rt.pid = None
            self.put(rt)
            self.save()
            self.event(f"{rt.state.upper():6} {job_id} (adopted) {rt.github_url or rt.workspace or ''}")
        finally:
            self.adopted.discard(job_id)

    def tick(self) -> None:
        self.watchdog()
        self.ingest_finished()
        for spec in self.queue.pending_sorted():
            if self.stopping:
                break
            if not self.slot_available(spec):
                continue
            if spec.gpu_memory_gb > 0 and self.free_gpu(spec.gpu_memory_gb) is None:
                continue
            self.launch(spec)
        self.maybe_crawl()
        self.maybe_plan()
        self.write_status()
        self.save()

    def stop(self, *_: object) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.event("STOP   terminating running jobs")
        for job_id in list(self.processes):
            self.kill_job(job_id, "daemon stopping")

    def run(self, once: bool = False) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        self.adopt()
        self.event(f"UP     daemon started (campaign={self.campaign or '-'}, gpus={self.config['gpus']})")
        while not self.stopping:
            self.tick()
            if once:
                break
            deadline = time.time() + float(self.config["poll_seconds"])
            while time.time() < deadline and not self.stopping:
                time.sleep(1)
        # Let job threads record the stop.
        for _ in range(30):
            if not self.processes:
                break
            time.sleep(1)
        self.ingest_finished()
        self.write_status()
        self.save()
        self.event("DOWN   daemon exited")
        return 0


def _make_readable(path: Path) -> None:
    """chmod a file and its parents under the project so another uid can read it."""
    try:
        path.chmod(path.stat().st_mode | 0o444)
        for parent in path.parents:
            if PROJECT_ROOT not in parent.parents and parent != PROJECT_ROOT:
                break
            parent.chmod(parent.stat().st_mode | 0o555)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
