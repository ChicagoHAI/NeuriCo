"""
Offline-eval annotations — human 👍/👎 on the manager's decision points.

A researcher reviewing a session can thumbs-up / thumbs-down three kinds of
subject on the web UI:
  - assessment  — a manager `assess` entry (situation / crux / engage_user)
  - decision    — a logged `decision` (question / chosen / rationale)
  - message     — a manager chat bubble

This is *purely an offline-eval artifact*: nothing here feeds back into the live
run. The records are the ground-truth substrate for evaluating the manager's
judgement later (per-decision verdicts, failure taxonomy, prompt/model A/B).

Stored append-only as JSONL at ``<workspace>/.neurico/annotations.jsonl`` — one
line per click, last write wins per ``key``. Each record also snapshots the
subject's text so it is self-contained. Keys are durable across resumed sessions:
assessment/decision keys (``assess:A3`` / ``dec:D2``) join back to
research_state.json by id, and chat-bubble keys (``msg:<hash>``) are a content
hash of the message text rather than a per-process sequence number.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict

VALID_KINDS = ("assessment", "decision", "message")
# "none" clears a prior verdict (the user un-toggled the thumb).
VALID_VERDICTS = ("up", "down", "none")

# The web server is threaded, so two near-simultaneous thumb clicks could
# interleave appends and corrupt a line (silently losing a verdict). Serialize
# writes through a process-wide lock.
_write_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def annotations_file(work_dir: Path) -> Path:
    return Path(work_dir) / ".neurico" / "annotations.jsonl"


def append_annotation(work_dir: Path, *, key: str, kind: str, verdict: str,
                      snapshot: str = "") -> Dict[str, str]:
    """Append one annotation record. Raises ValueError on bad input."""
    key = (key or "").strip()
    if not key:
        raise ValueError("annotation key required")
    if kind not in VALID_KINDS:
        raise ValueError(f"bad kind {kind!r}")
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"bad verdict {verdict!r}")

    record = {
        "ts": _now(),
        "key": key,
        "kind": kind,
        "verdict": verdict,
        "snapshot": (snapshot or "")[:500],
    }
    path = annotations_file(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _write_lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    return record


def load_latest(work_dir: Path) -> Dict[str, str]:
    """Fold the JSONL into a {key: verdict} map (last write wins). Cleared
    ('none') keys are dropped, so the result is only the live up/down verdicts —
    exactly what the UI needs to re-paint thumb state on load."""
    path = annotations_file(work_dir)
    latest: Dict[str, str] = {}
    if not path.exists():
        return latest
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = rec.get("key")
                verdict = rec.get("verdict")
                if not key:
                    continue
                if verdict in ("up", "down"):
                    latest[key] = verdict
                else:  # "none" or unknown → clear
                    latest.pop(key, None)
    except OSError:
        pass
    return latest
