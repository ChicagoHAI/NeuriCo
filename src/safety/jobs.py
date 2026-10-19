"""Job specifications and the on-disk queue.

A job is one YAML file. Its *location* is its queue state::

    safety_kb/queue/pending/<id>.yaml   waiting for a slot (or for approval)
    safety_kb/queue/running/<id>.yaml   launched by the daemon
    safety_kb/queue/done/<id>.yaml      finished successfully and ingested
    safety_kb/queue/failed/<id>.yaml    gave up after retries, or cancelled

Runtime details (container name, attempts, log offsets) live in
``queue/state.json`` so the job file stays a human-editable specification.

Job kinds
- ``suite``:    deterministic evaluations through the safety-evals skill, no coding agent.
- ``research``: a NeuriCo Standard run of the idea file.
- ``optimise``: a NeuriCo AutoResearch run (sealed scoring loop).
- ``explore``:  a NeuriCo Standard run with investigator instructions (novel-behaviour search).
- ``validate``: an independent reproduction of a candidate finding (different provider).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from safety.kb import JOB_KINDS, KB, load_yaml, save_yaml, slugify, unique_id, utc_now

NEURICO_KINDS = ("research", "optimise", "explore", "validate")


@dataclass
class JobSpec:
    id: str
    kind: str
    title: str
    campaign: str = ""
    priority: int = 50
    created: str = field(default_factory=utc_now)
    created_by: str = "human"
    approved: bool = True
    rationale: str = ""
    # suite jobs
    evals: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    limit: Optional[int] = None
    # NeuriCo jobs
    idea_file: Optional[str] = None
    provider: str = "claude"
    model: Optional[str] = None
    autoresearch_iterations: int = 3
    write_paper: bool = False
    github: bool = True
    private: bool = False
    # resources
    gpu_memory_gb: float = 0.0
    api_budget_usd: float = 0.0
    # validation
    finding_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind {self.kind!r}; expected one of {JOB_KINDS}")
        if self.kind == "suite" and not (self.evals and self.models):
            raise ValueError("suite jobs need `evals` and `models`")
        if self.kind in NEURICO_KINDS and not self.idea_file:
            raise ValueError(f"{self.kind} jobs need an `idea_file`")

    @property
    def uses_neurico(self) -> bool:
        return self.kind in NEURICO_KINDS

    @property
    def slot(self) -> str:
        """Which concurrency slot the job consumes."""
        return "gpu" if self.gpu_memory_gb > 0 else "api"

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id, "kind": self.kind, "title": self.title, "campaign": self.campaign,
            "priority": self.priority, "created": self.created, "created_by": self.created_by,
            "approved": self.approved, "rationale": self.rationale,
            "resources": {"gpu_memory_gb": self.gpu_memory_gb, "api_budget_usd": self.api_budget_usd},
        }
        if self.kind == "suite":
            data["suite"] = {"evals": self.evals, "models": self.models, "limit": self.limit}
        else:
            data["neurico"] = {
                "idea_file": self.idea_file, "provider": self.provider, "model": self.model,
                "autoresearch_iterations": self.autoresearch_iterations,
                "write_paper": self.write_paper, "github": self.github, "private": self.private,
            }
        if self.finding_id:
            data["finding_id"] = self.finding_id
        if self.extra:
            data["extra"] = self.extra
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobSpec":
        suite = data.get("suite") or {}
        neurico = data.get("neurico") or {}
        resources = data.get("resources") or {}
        return cls(
            id=str(data["id"]), kind=data["kind"], title=data.get("title", data["id"]),
            campaign=data.get("campaign", ""), priority=int(data.get("priority", 50)),
            created=data.get("created", utc_now()), created_by=data.get("created_by", "human"),
            approved=bool(data.get("approved", True)), rationale=data.get("rationale", ""),
            evals=list(suite.get("evals") or []), models=list(suite.get("models") or []),
            limit=suite.get("limit"),
            idea_file=neurico.get("idea_file"), provider=neurico.get("provider", "claude"),
            model=neurico.get("model"),
            autoresearch_iterations=int(neurico.get("autoresearch_iterations", 3)),
            write_paper=bool(neurico.get("write_paper", False)),
            github=bool(neurico.get("github", True)), private=bool(neurico.get("private", False)),
            gpu_memory_gb=float(resources.get("gpu_memory_gb", 0.0)),
            api_budget_usd=float(resources.get("api_budget_usd", 0.0)),
            finding_id=data.get("finding_id"), extra=dict(data.get("extra") or {}),
        )


class Queue:
    """The four queue directories plus helpers to move jobs between them."""

    def __init__(self, kb: KB):
        self.kb = kb
        kb.ensure_layout()

    def path(self, state: str, job_id: str) -> Path:
        return self.kb.queue_state_dir(state) / f"{job_id}.yaml"

    def find(self, job_id: str) -> Optional[tuple[str, Path]]:
        for state in ("pending", "running", "done", "failed"):
            path = self.path(state, job_id)
            if path.exists():
                return state, path
        return None

    def list(self, state: str) -> List[JobSpec]:
        jobs = []
        for path in sorted(self.kb.queue_state_dir(state).glob("*.yaml")):
            data = load_yaml(path)
            if data:
                jobs.append(JobSpec.from_dict(data))
        return jobs

    def all_ids(self) -> List[str]:
        ids = []
        for state in ("pending", "running", "done", "failed"):
            ids += [path.stem for path in self.kb.queue_state_dir(state).glob("*.yaml")]
        return ids

    def new_id(self, kind: str, title: str) -> str:
        base = unique_id(kind, self.all_ids())
        return f"{base}-{slugify(title, 32)}"

    def add(self, spec: JobSpec) -> Path:
        path = self.path("pending", spec.id)
        if self.find(spec.id):
            raise FileExistsError(f"job {spec.id} already exists")
        save_yaml(path, spec.to_dict())
        return path

    def move(self, job_id: str, to_state: str) -> Path:
        found = self.find(job_id)
        if not found:
            raise FileNotFoundError(f"job {job_id} not in queue")
        _, src = found
        dst = self.path(to_state, job_id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return dst

    def pending_sorted(self) -> List[JobSpec]:
        """Approved pending jobs, highest priority first, oldest first within a priority."""
        jobs = [job for job in self.list("pending") if job.approved]
        return sorted(jobs, key=lambda j: (-j.priority, j.created, j.id))

    def signature(self, spec: JobSpec) -> tuple:
        """What makes two jobs 'the same work' for de-duplication."""
        if spec.kind == "suite":
            return ("suite", tuple(sorted(spec.evals)), tuple(sorted(spec.models)), spec.limit)
        return (spec.kind, spec.idea_file, spec.provider, spec.model)
