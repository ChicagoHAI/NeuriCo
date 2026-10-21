"""Append-only audit log for one ideation run (``events.jsonl`` in the run directory).

One JSON object per line: who (``actor``), what (``action``), on which ``target``, when, plus
the hashes that tie the event to the exact bytes involved. Actors are
``<provider>:<model>@<auth>`` for agent stages and ``system:ideation`` for code steps.

Ported from sai-review ``src/sai_digest/events.py`` (see ``NOTICE.md``); the action
vocabulary is trimmed to what an ideation run does.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ACTIONS = (
    "run.started", "run.finished", "run.failed",
    "step.started", "step.finished", "step.failed", "step.skipped",
    "artifact.written", "idea.proposed", "job.proposed", "warning",
)

_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths: Iterable[Path]) -> str:
    """One hash over several files, order-independent (sorted by name)."""
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        h.update(p.name.encode())
        h.update(b"\0")
        h.update(sha256_file(p).encode())
        h.update(b"\n")
    return h.hexdigest()


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, *, run_id: str, actor: str, action: str, target: str,
               step: Optional[str] = None, inputs_sha256: Optional[str] = None,
               outputs_sha256: Optional[Dict[str, str]] = None,
               detail: Optional[Dict[str, Any]] = None,
               session_id: Optional[str] = None) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError(f"unknown audit action {action!r}")
        event = {
            "ts": utc_now(), "run_id": run_id, "step": step, "actor": actor,
            "action": action, "target": target,
            "inputs_sha256": inputs_sha256, "outputs_sha256": outputs_sha256 or None,
            "detail": detail or None, "session_id": session_id,
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return event

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
