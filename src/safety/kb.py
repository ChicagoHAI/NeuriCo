"""Knowledge-base layout and small, safe file helpers.

The knowledge base lives in ``safety_kb/`` at the project root (override with
``NEURICO_SAFETY_KB``). Everything the engine reads or writes is a plain YAML or
JSON file so humans and agents can edit it with any tool.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

JOB_KINDS = ("suite", "research", "optimise", "explore", "validate")
JOB_STATES = ("pending", "running", "done", "failed", "stalled", "stopped", "cancelled")
FINDING_STATES = ("candidate", "reproduced", "confirmed", "refuted", "withdrawn")


def kb_root() -> Path:
    return Path(os.environ.get("NEURICO_SAFETY_KB", PROJECT_ROOT / "safety_kb")).resolve()


class KB:
    """Paths inside the knowledge base. Directories are created on demand."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root).resolve() if root else kb_root()

    # -- layout ---------------------------------------------------------------
    @property
    def catalog_dir(self) -> Path:
        return self.root / "catalog"

    @property
    def campaigns_dir(self) -> Path:
        return self.root / "campaigns"

    @property
    def queue_dir(self) -> Path:
        return self.root / "queue"

    def queue_state_dir(self, state: str) -> Path:
        if state not in ("pending", "running", "done", "failed"):
            raise ValueError(f"unknown queue state: {state}")
        return self.queue_dir / state

    @property
    def ideas_dir(self) -> Path:
        return self.queue_dir / "ideas"

    @property
    def findings_dir(self) -> Path:
        return self.root / "findings"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs" / "safety"

    @property
    def state_file(self) -> Path:
        return self.queue_dir / "state.json"

    @property
    def engine_config_file(self) -> Path:
        return self.root / "engine.yaml"

    def ensure_layout(self) -> None:
        for path in (self.catalog_dir, self.campaigns_dir, self.ideas_dir, self.findings_dir,
                     self.runs_dir, self.results_dir, self.inbox_dir, self.reports_dir,
                     self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        for state in ("pending", "running", "done", "failed"):
            self.queue_state_dir(state).mkdir(parents=True, exist_ok=True)

    # -- catalogs -------------------------------------------------------------
    def load_catalog(self, name: str) -> Dict[str, Any]:
        """Return the entries of ``catalog/<name>.yaml`` keyed by id."""
        data = load_yaml(self.catalog_dir / f"{name}.yaml") or {}
        entries = data.get(name) or data.get("entries") or []
        if isinstance(entries, dict):
            return entries
        return {entry["id"]: entry for entry in entries if isinstance(entry, dict) and "id" in entry}

    def models(self) -> Dict[str, Any]:
        return self.load_catalog("models")

    def evals(self) -> Dict[str, Any]:
        return self.load_catalog("evals")

    def campaign(self, name: str) -> Dict[str, Any]:
        path = self.campaigns_dir / f"{name}.yaml"
        data = load_yaml(path)
        if not data:
            raise FileNotFoundError(f"campaign not found: {path}")
        data.setdefault("name", name)
        return data

    def engine_config(self) -> Dict[str, Any]:
        return load_yaml(self.engine_config_file) or {}

    # -- findings and runs ----------------------------------------------------
    def list_findings(self) -> List[Dict[str, Any]]:
        return [load_yaml(path) for path in sorted(self.findings_dir.glob("*.yaml"))]

    def list_runs(self) -> List[Dict[str, Any]]:
        return [load_json(path) for path in sorted(self.runs_dir.glob("*.json"))]


# -- file helpers -------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "item"


def load_yaml(path: Path) -> Any:
    path = Path(path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path) -> Any:
    path = Path(path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory so readers never see a torn file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_yaml(path: Path, data: Any) -> None:
    atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))


def save_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def append_line(path: Path, line: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")


def unique_id(prefix: str, existing: Iterable[str]) -> str:
    """``<prefix>-<date>-<n>`` that does not collide with ``existing``."""
    taken = set(existing)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    n = 1
    while f"{prefix}-{date}-{n:03d}" in taken:
        n += 1
    return f"{prefix}-{date}-{n:03d}"
