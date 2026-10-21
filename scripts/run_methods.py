#!/usr/bin/env python3
"""
Run one or more ideas through NeuriCo and the zero-shot baselines.

Edit METHODS below to choose what runs. There are three slots: NeuriCo,
zero-shot Claude Code and zero-shot Codex. Each slot works through its own
queue (idea by idea, then method by method) and starts its next job as soon as
the previous one finishes, so three jobs run at all times and a slow job never
holds the other slots idle.

Every job runs in the NeuriCo Docker image through ./neurico, in its own
workspace under the configured workspace directory:

    NeuriCo:    {slug}-{hash}-{provider}-{model}
    zero-shot:  {slug}-{hash}-zeroshot-{provider}-{model}

Usage:
    scripts/run_methods.py ideas/my_idea.yaml [more.yaml ...]
    scripts/run_methods.py ideas/my_idea.yaml --dry-run
    scripts/run_methods.py ideas/*.yaml --gpus 0,1,2,3
    scripts/run_methods.py ideas/b.yaml --resume-baseline my-idea-9c1e-zeroshot-claude-opus-5-5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
    """SIGKILL the groups still alive after ``delay`` seconds (non-blocking)."""
    if not pgids:
        return
    timer = threading.Timer(delay, lambda: [killpg_quiet(p, signal.SIGKILL) for p in pgids])
    timer.daemon = True
    timer.start()


# -----------------------------------------------------------------------------
# What to run: (method, provider, model). Comment a row out to skip it.
# -----------------------------------------------------------------------------
METHODS = [
    ("neurico",   "claude", "claude-opus-5-5"),
    ("neurico",   "codex",  "gpt-5.6-sol"),
    ("neurico",   "claude", "claude-fable-5-1"),
    ("neurico",   "codex",  "gpt-6-astra"),
    ("zero-shot", "claude", "claude-opus-5-5"),
    ("zero-shot", "claude", "claude-fable-5-1"),
    ("zero-shot", "codex",  "gpt-5.6-sol"),
    ("zero-shot", "codex",  "gpt-6-astra"),
]

# Wall-clock limits in seconds; 0 means no limit. Completing the research is
# the priority, so nothing is cut off by default.
RESOURCE_FINDER_TIMEOUT = 0
EXPERIMENT_TIMEOUT = 0
PAPER_TIMEOUT = 0
ZERO_SHOT_TIMEOUT = 0


@dataclass(frozen=True)
class Method:
    method: str
    provider: str
    model: str

    def __post_init__(self):
        if self.method not in {"neurico", "zero-shot"}:
            raise ValueError(f"Unknown method: {self.method}")
        if self.provider not in {"claude", "codex"}:
            raise ValueError(f"Unknown provider: {self.provider}")

    @property
    def slot(self) -> str:
        """Jobs in the same slot never run concurrently for one idea."""
        return "neurico" if self.method == "neurico" else f"zero-shot-{self.provider}"

    @property
    def label(self) -> str:
        return f"{self.method}-{self.provider}-{re.sub(r'[^a-z0-9]+', '-', self.model.lower())}"


def plan_slots(ideas: List[Path], methods: List[Method]) -> Dict[str, List[tuple]]:
    """Queue per slot: every idea in order, and within an idea the methods in list order."""
    slots: Dict[str, List[tuple]] = {}
    for method in methods:
        slots.setdefault(method.slot, [])
    for idea in ideas:
        for method in methods:
            slots[method.slot].append((idea, method))
    return slots


def parse_neurico_resumes(specs: List[str], methods: List[Method]) -> Dict[tuple, str]:
    """`IDEA=IDEA_ID` or `IDEA/METHOD-LABEL=IDEA_ID` -> {(idea stem, method label): idea id}.

    An idea ID names one existing workspace, so it must resume exactly one
    NeuriCo method: the bare form is accepted only when a single NeuriCo method
    is selected.
    """
    neurico = [m for m in methods if m.method == "neurico"]
    resumes: Dict[tuple, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"--resume-neurico expects IDEA[/METHOD-LABEL]=IDEA_ID, got {spec!r}")
        target, idea_id = spec.split("=", 1)
        idea, _, label = target.partition("/")
        if label:
            matches = [m for m in neurico if m.label == label]
            if not matches:
                raise SystemExit(f"--resume-neurico {spec!r}: no selected NeuriCo method is labelled "
                                 f"{label!r} (selected: {[m.label for m in neurico]})")
        elif len(neurico) == 1:
            matches = neurico
        else:
            raise SystemExit(f"--resume-neurico {spec!r} would resume one workspace with "
                             f"{len(neurico)} NeuriCo methods; name the method as IDEA/METHOD-LABEL=ID "
                             f"or select one with --only")
        resumes[(idea, matches[0].label)] = idea_id
    return resumes


def parse_resume(spec: str) -> tuple:
    """`<workspace>` -> (workspace, provider, model), read from the workspace name."""
    match = re.fullmatch(r".+-zeroshot-(claude|codex)-(.+)", spec)
    if not match:
        raise SystemExit(f"--resume-baseline expects a zero-shot workspace name, got {spec!r}")
    return spec, match[1], match[2]


@dataclass
class Job:
    idea_file: Path
    method: Method
    log_file: Path
    container: str
    state: str = "pending"
    gpu: Optional[str] = None
    idea_id: Optional[str] = None
    workspace: Optional[str] = None
    github_url: Optional[str] = None
    return_code: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    resume_workspace: Optional[str] = None
    resume_mode: Optional[str] = None
    attempts: int = 0
    commands: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        data = asdict(self)
        data["idea_file"] = str(self.idea_file)
        data["log_file"] = str(self.log_file)
        data["method"] = self.method.label
        return data


class Batch:
    def __init__(self, args: argparse.Namespace, methods: List[Method]):
        self.args = args
        self.methods = methods
        self.batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.batch_dir = PROJECT_ROOT / "logs" / "batch" / self.batch_id
        self.jobs: List[Job] = []
        self.lock = threading.Lock()
        self.processes: Dict[str, subprocess.Popen] = {}
        self.stopping = False
        self.gpus = [g.strip() for g in (args.gpus or "").split(",") if g.strip()]
        self.gpus_in_use: Dict[str, int] = {}

    # -- GPUs -----------------------------------------------------------------
    def acquire_gpu(self) -> Optional[str]:
        """Pick the allowed GPU this batch uses least, then the one with most free memory.

        Checking memory at launch keeps a new job off a GPU that a job outside
        this batch (another user, an earlier run) is still using.
        """
        if not self.gpus:
            return None
        used_memory = {gpu: 0 for gpu in self.gpus}
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=30).stdout
            for line in out.splitlines():
                index, memory = [part.strip() for part in line.split(",")]
                if index in used_memory:
                    used_memory[index] = int(memory)
        except Exception:
            pass
        with self.lock:
            gpu = min(self.gpus, key=lambda g: (self.gpus_in_use.get(g, 0), used_memory[g]))
            self.gpus_in_use[gpu] = self.gpus_in_use.get(gpu, 0) + 1
        return gpu

    def release_gpu(self, gpu: Optional[str]) -> None:
        if gpu is not None:
            with self.lock:
                self.gpus_in_use[gpu] -= 1

    # -- bookkeeping ----------------------------------------------------------
    def save_status(self) -> None:
        with self.lock:
            payload = {"batch_id": self.batch_id, "jobs": [job.to_json() for job in self.jobs]}
            tmp = self.batch_dir / "status.json.tmp"
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self.batch_dir / "status.json")

    def say(self, message: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

    # -- commands -------------------------------------------------------------
    def github_flags(self) -> List[str]:
        flags = []
        if self.args.no_github:
            flags.append("--no-github")
        if self.args.private:
            flags.append("--private")
        return flags

    def neurico_submit_command(self, job: Job) -> List[str]:
        m = job.method
        return [str(NEURICO), "submit", str(job.idea_file),
                "--provider", m.provider, "--model", m.model, *self.github_flags()]

    def neurico_run_command(self, job: Job) -> List[str]:
        m = job.method
        command = [str(NEURICO), "run", job.idea_id or "<idea_id>",
                   "--provider", m.provider, "--model", m.model, "--full-permissions",
                   "--resource-finder-timeout", str(self.args.resource_finder_timeout),
                   "--timeout", str(self.args.experiment_timeout),
                   "--paper-timeout", str(self.args.paper_timeout)]
        if self.args.no_github:
            command.append("--no-github")
        return command

    def baseline_command(self, job: Job) -> List[str]:
        m = job.method
        command = [str(NEURICO), "baseline", str(job.idea_file),
                   "--provider", m.provider, "--model", m.model,
                   "--timeout", str(self.args.zero_shot_timeout), *self.github_flags()]
        if job.resume_workspace:
            command += ["--resume-workspace", job.resume_workspace,
                        "--resume-mode", job.resume_mode or "continue"]
        return command

    # -- execution ------------------------------------------------------------
    def call(self, job: Job, command: List[str], *, named: bool) -> int:
        """Run one ./neurico command, appending its output to the job log."""
        env = os.environ.copy()
        if job.gpu:
            env["NEURICO_GPUS"] = job.gpu
        if self.args.hf_cache and job.method.method == "neurico":
            env["NEURICO_HF_CACHE"] = str(self.args.hf_cache)
        if named:
            env["NEURICO_CONTAINER_NAME"] = job.container
        else:
            env.pop("NEURICO_CONTAINER_NAME", None)
        job.commands.append(" ".join(command))
        with open(job.log_file, "a", encoding="utf-8") as log:
            log.write(f"\n$ {' '.join(command)}\n")
            log.flush()
            # Own session: stop() kills the whole tree (launcher, python, agents)
            # by process group, which is all that exists in host mode.
            process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            with self.lock:
                self.processes[job.container] = process
            try:
                return process.wait()
            finally:
                with self.lock:
                    self.processes.pop(job.container, None)

    def read_log(self, job: Job) -> str:
        return job.log_file.read_text(encoding="utf-8", errors="replace")

    def record_outputs(self, job: Job) -> None:
        text = self.read_log(job)
        for pattern, attribute in (
            (r"^Idea ID:\s*(\S+)", "idea_id"),
            (r"^\s*(?:Location|Local|📁 Working directory):\s*(\S+)", "workspace"),
            (r"^\s*(?:GitHub|URL):\s*(https://github\.com/\S+)", "github_url"),
        ):
            matches = re.findall(pattern, text, flags=re.MULTILINE)
            if matches:
                setattr(job, attribute, matches[-1])

    def wait_before_retry(self, job: Job, reason: str) -> bool:
        """Count one more attempt; False when retries are used up or the batch is stopping."""
        if self.stopping or job.attempts >= self.args.retries:
            return False
        job.attempts += 1
        with open(job.log_file, "a") as log:
            log.write(f"\n[run_methods] {reason}; retry {job.attempts}/{self.args.retries} "
                      f"in {self.args.retry_wait}s\n")
        self.say(f"RETRY  {job.idea_file.stem} | {job.method.label} | {reason}")
        self.save_status()
        deadline = time.time() + self.args.retry_wait
        while time.time() < deadline and not self.stopping:
            time.sleep(5)
        return not self.stopping

    def run_neurico(self, job: Job) -> int:
        code = 0
        if not job.idea_id:  # a preset ID resumes an already submitted idea
            code = self.call(job, self.neurico_submit_command(job), named=False)
            self.record_outputs(job)
        if code == 0 and not job.idea_id:
            with open(job.log_file, "a") as log:
                log.write("\n[run_methods] submit printed no idea ID\n")
            return 1
        while code == 0 and not self.stopping:
            offset = job.log_file.stat().st_size if job.log_file.exists() else 0
            code = self.call(job, self.neurico_run_command(job), named=True)
            with open(job.log_file, "r", encoding="utf-8", errors="replace") as log:
                log.seek(offset)
                # runner.py exits 0 even when a stage fails; trust its verdict line.
                failed = code != 0 or "did not complete successfully" in log.read()
            if not failed:
                return 0
            # Rerunning the same idea resumes its workspace after the last finished stage.
            if not self.wait_before_retry(job, "NeuriCo run did not complete"):
                return code or 1
            code = 0
        return code

    # Exit codes of baseline/zero_shot.py
    BASELINE_NO_PAPER = 3  # the session ended normally but produced no paper

    def run_zero_shot(self, job: Job) -> int:
        while True:
            code = self.call(job, self.baseline_command(job), named=True)
            self.record_outputs(job)
            if code == 0 or not job.workspace:
                return code
            if code == self.BASELINE_NO_PAPER:
                # The agent considered itself finished: a new session only writes up.
                reason, job.resume_mode = "zero-shot run ended without a paper", "writeup"
            else:
                # The session was cut short (crash, auth failure, kill): continue the research.
                reason, job.resume_mode = f"zero-shot session failed (rc={code})", "continue"
            if not self.wait_before_retry(job, reason):
                return code
            job.resume_workspace = Path(job.workspace).name

    def paper_exists(self, job: Job) -> bool:
        """True when the run's workspace holds a compiled paper (unknown workspace: assume yes)."""
        if not job.workspace:
            return True
        return (workspace_dir() / Path(job.workspace).name / "paper_draft" / "main.pdf").is_file()

    def run_job(self, job: Job) -> None:
        if self.stopping:
            job.state = "cancelled"
            return
        job.gpu = self.acquire_gpu()
        job.state = "running"
        job.started_at = datetime.now().isoformat(timespec="seconds")
        self.say(f"START  {job.idea_file.stem} | {job.method.label} | gpu={job.gpu or 'all'}"
                 f"{' | resume ' + job.resume_workspace if job.resume_workspace else ''}"
                 f" | log={job.log_file.relative_to(PROJECT_ROOT)}")
        self.save_status()
        try:
            run = self.run_neurico if job.method.method == "neurico" else self.run_zero_shot
            job.return_code = run(job)
            self.record_outputs(job)
            if self.stopping:
                job.state = "stopped"
            elif job.return_code != 0:
                job.state = "no_paper" if job.return_code == self.BASELINE_NO_PAPER else "failed"
            elif not self.paper_exists(job):
                # NeuriCo reports success when the research pipeline completed even
                # if paper generation failed; keep that distinct from a finished paper.
                job.state = "no_paper"
            else:
                job.state = "done"
        except Exception as e:  # keep the rest of the batch going
            job.state = "failed"
            with open(job.log_file, "a") as log:
                log.write(f"\n[run_methods] {type(e).__name__}: {e}\n")
        finally:
            self.release_gpu(job.gpu)
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            self.say(f"{job.state.upper():6} {job.idea_file.stem} | {job.method.label}"
                     f" | rc={job.return_code} | {job.github_url or job.workspace or ''}")
            self.save_status()

    def run_slot(self, index: int, jobs: List[Job]) -> None:
        time.sleep(index * self.args.stagger)  # avoid racing on credential setup
        for job in jobs:
            self.run_job(job)

    def stop(self, *_: object) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.say("Stopping: killing running jobs...")
        with self.lock:
            running = dict(self.processes)
        groups: List[int] = []
        for container, process in running.items():
            if not host_mode() and shutil.which("docker"):
                subprocess.run(["docker", "kill", container], capture_output=True)
            pgid = host_job_pgid(container)
            if pgid:
                groups.append(pgid)
            groups.append(process.pid)  # start_new_session=True: pid == pgid
        for pgid in groups:
            killpg_quiet(pgid, signal.SIGTERM)
        escalate_sigkill(groups)

    def make_job(self, idea_file: Path, method: Method, resume: Optional[str] = None) -> Job:
        name = f"{idea_file.stem}__{method.label}"
        return Job(
            idea_file=idea_file, method=method, resume_workspace=resume,
            log_file=self.batch_dir / f"{name}.log",
            container=re.sub(r"[^a-zA-Z0-9_.-]", "-", f"neurico-{self.batch_id}-{name}"),
        )

    def run(self) -> int:
        slots: Dict[str, List[Job]] = {
            slot: [self.make_job(idea, method) for idea, method in queue]
            for slot, queue in plan_slots(self.args.ideas, self.methods).items()
        }
        # Unfinished baseline workspaces go to the front of their slot's queue.
        for idea_file, workspace, provider, model in reversed(self.args.resume_jobs):
            method = Method("zero-shot", provider, model)
            slots.setdefault(method.slot, []).insert(0, self.make_job(idea_file, method, workspace))
        self.jobs = [job for jobs in slots.values() for job in jobs]
        for job in self.jobs:
            if job.method.method == "neurico":
                job.idea_id = self.args.neurico_idea_ids.get((job.idea_file.stem, job.method.label))

        print(f"Batch {self.batch_id}: {len(self.jobs)} run(s) in {len(slots)} concurrent slot(s)")
        for slot, jobs in slots.items():
            print(f"  slot {slot}:")
            for job in jobs:
                note = f"  (resume {job.resume_workspace})" if job.resume_workspace else ""
                print(f"    {job.idea_file.stem:32} {job.method.label}{note}")
        if self.args.dry_run:
            print("\nCommands (first job of each slot):")
            for jobs in slots.values():
                job = jobs[0]
                if job.method.method == "neurico":
                    print("  " + " ".join(self.neurico_submit_command(job)))
                    print("  " + " ".join(self.neurico_run_command(job)))
                else:
                    print("  " + " ".join(self.baseline_command(job)))
            return 0

        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.save_status()
        print(f"Logs and status: {self.batch_dir}\n", flush=True)
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        threads = [threading.Thread(target=self.run_slot, args=(index, jobs))
                   for index, jobs in enumerate(slots.values())]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        print("\nSummary")
        for job in self.jobs:
            print(f"  {job.state:9} {job.idea_file.stem:32} {job.method.label:36} "
                  f"{job.github_url or job.workspace or '-'}")
        return 0 if all(job.state == "done" for job in self.jobs) else 1


def workspace_dir() -> Path:
    """Workspace parent directory from config/workspace.yaml (same rule as docker/run.sh)."""
    for name in ("workspace.yaml", "workspace.yaml.example"):
        config = PROJECT_ROOT / "config" / name
        if config.is_file():
            match = re.search(r"^\s*parent_dir:\s*[\"']?([^\"'\n#]+)", config.read_text(), re.MULTILINE)
            if match and match[1].strip():
                path = Path(match[1].strip())
                return path if path.is_absolute() else PROJECT_ROOT / path
    return PROJECT_ROOT / "workspaces"


def idea_stem(idea_file: Path) -> str:
    """Short name for a resumed idea, matching an arena candidate file when one has its title."""
    title = re.search(r"^\s*title:\s*(.+)$", idea_file.read_text(encoding="utf-8"), re.MULTILINE)
    title_text = title[1].strip().strip("\"'") if title else ""
    for candidate in sorted((PROJECT_ROOT / "ideas").rglob("*.yaml")):
        if "submitted" in candidate.parts or "completed" in candidate.parts or "in_progress" in candidate.parts:
            continue
        if title_text and title_text in candidate.read_text(encoding="utf-8", errors="replace"):
            return candidate.stem
    return re.sub(r"[^a-z0-9]+", "_", title_text.lower()).strip("_")[:40] or "resumed_idea"


def select_methods(only: Optional[str]) -> List[Method]:
    methods = [Method(*row) for row in METHODS]
    if not only:
        return methods
    wanted = [token.strip().lower() for token in only.split(",") if token.strip()]
    selected = [m for m in methods if any(token in m.label for token in wanted)]
    if not selected:
        raise SystemExit(f"--only {only!r} matched none of: {[m.label for m in methods]}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ideas through NeuriCo and the zero-shot baselines "
                    "(timeouts are in seconds; 0 = no limit)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("ideas", nargs="*", type=Path, help="Idea YAML file(s)")
    parser.add_argument("--only", help="Comma-separated substrings of method labels to keep, "
                        "e.g. 'zero-shot' or 'neurico-claude,gpt-6-astra'")
    parser.add_argument("--gpus", help="Host GPU indices to use, one per run, picking the "
                        "least-used at launch (e.g. 0,1,2,3). Default: every run sees all GPUs")
    parser.add_argument("--stagger", type=float, default=20.0,
                        help="Seconds between the first launches of the slots")
    parser.add_argument("--retries", type=int, default=2,
                        help="Automatic retries per run: a failed NeuriCo run is resumed, and a "
                        "zero-shot run that ended without a paper gets a new session in its workspace")
    parser.add_argument("--retry-wait", type=int, default=300, help="Seconds to wait before a retry")
    parser.add_argument("--resume-neurico", action="append", default=[],
                        metavar="IDEA[/METHOD-LABEL]=IDEA_ID",
                        help="Skip submission for this idea file name (without .yaml) and resume the "
                        "NeuriCo run with this existing idea ID in its workspace; name the method "
                        "label unless only one NeuriCo method is selected (repeatable)")
    parser.add_argument("--resume-baseline", action="append", default=[], metavar="WORKSPACE",
                        help="Finish an earlier zero-shot run in its existing workspace before "
                        "the slot's other jobs (repeatable). Its idea is read from the workspace")
    parser.add_argument("--hf-cache", type=Path, default=None,
                        help="Host directory to use as the Hugging Face cache of NeuriCo runs. "
                        "Without it they download into the container, i.e. onto the root disk")
    parser.add_argument("--no-github", action="store_true", help="Keep all runs local")
    parser.add_argument("--private", action="store_true", help="Create private repositories")
    parser.add_argument("--resource-finder-timeout", type=int, default=RESOURCE_FINDER_TIMEOUT)
    parser.add_argument("--experiment-timeout", type=int, default=EXPERIMENT_TIMEOUT)
    parser.add_argument("--paper-timeout", type=int, default=PAPER_TIMEOUT)
    parser.add_argument("--zero-shot-timeout", type=int, default=ZERO_SHOT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and commands only")
    args = parser.parse_args()

    args.ideas = [path.resolve() for path in args.ideas]
    missing = [str(path) for path in args.ideas if not path.is_file()]
    if missing:
        raise SystemExit(f"Idea file(s) not found: {', '.join(missing)}")
    stems = [path.stem for path in args.ideas]
    if len(set(stems)) != len(stems):
        raise SystemExit("Idea files must have distinct names (they name the logs).")
    args.neurico_idea_ids = parse_neurico_resumes(args.resume_neurico, select_methods(args.only))
    args.resume_jobs = []
    for spec in args.resume_baseline:
        workspace, provider, model_slug = parse_resume(spec)
        models = {re.sub(r"[^a-z0-9]+", "-", row[2].lower()).removeprefix(f"{row[1]}-"): row[2]
                  for row in METHODS if row[0] == "zero-shot" and row[1] == provider}
        if model_slug not in models:
            raise SystemExit(f"No zero-shot {provider} model in METHODS matches {spec!r}")
        idea_file = workspace_dir() / workspace / ".baseline" / "idea.yaml"
        if not idea_file.is_file():
            raise SystemExit(f"Not a baseline workspace: {idea_file.parent.parent}")
        # Logs are named after the idea file; keep the original idea's name.
        staged = PROJECT_ROOT / "logs" / "resume_ideas" / f"{idea_stem(idea_file)}.yaml"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(idea_file.read_text(encoding="utf-8"), encoding="utf-8")
        args.resume_jobs.append((staged, workspace, provider, models[model_slug]))
    if not args.ideas and not args.resume_jobs:
        raise SystemExit("Nothing to run: give idea file(s) and/or --resume-baseline.")
    return Batch(args, select_methods(args.only)).run()


if __name__ == "__main__":
    sys.exit(main())
