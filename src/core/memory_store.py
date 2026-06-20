"""
Storage layer for NeuriCo's experience memory.

A memory is a small markdown file with YAML frontmatter capturing a piece of
research-experience knowledge that future experiments might benefit from.
See ``docs/memory_schema.md`` for the schema contract.

This module owns the on-disk layout and the read/write/list/filter primitives.
It deliberately knows NOTHING about retrieval, extraction prompts, or any LLM
machinery — those live higher up the stack so this module stays cheap to test
and reuse.

Storage root:
    ~/.neurico/memories/
        live/        promoted memories — retrieval reads these
        drafts/      newly extracted, not yet promoted
        archived/    demoted from live, kept for audit
        index.json   derived cache: id → metadata for fast filter

The index can always be rebuilt from the files on disk; ``MemoryStore.reindex()``
is idempotent and safe to call after a crash.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_MEMORY_ROOT = Path.home() / ".neurico" / "memories"

# Subdirectory names under the memory root. Kept as module-level constants so
# downstream code (Docker mount setup, CLI, retrieval) imports from one place.
LIVE_DIR = "live"
DRAFTS_DIR = "drafts"
ARCHIVED_DIR = "archived"
INDEX_FILE = "index.json"

VALID_APPROACHES = ("runner_self", "manager_observer", "manual")
VALID_CONFIDENCE = ("low", "medium", "high")

# Frontmatter fences expected by the parser. We don't use a full YAML library
# at write time (so memory files round-trip predictably), but we DO use one at
# read time when available — falling back to a small inline parser when not.
_FENCE = "---"


# Schema model

@dataclass
class ProblemClass:
    """
    Abstracted preconditions and recognition signals for the memory.

    All fields are deliberately abstract — concrete details belong in
    ``Origin`` and are stripped before the memory is shown to a future agent.
    """

    what: str
    shape: List[Dict[str, str]] = field(default_factory=list)
    signal_to_recognize: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "what": self.what,
            "shape": list(self.shape),
            "signal_to_recognize": list(self.signal_to_recognize),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProblemClass":
        return cls(
            what=str(d.get("what", "")),
            shape=list(d.get("shape", [])),
            signal_to_recognize=list(d.get("signal_to_recognize", [])),
        )


@dataclass
class Origin:
    """
    Provenance of the memory.

    Recorded for audit + dedup, NEVER injected into a future agent's context.
    """

    source_run: str
    source_domain: str
    source_idea_one_liner: str = ""
    what_first_attempt_was: str = ""
    what_actually_worked: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_run": self.source_run,
            "source_domain": self.source_domain,
            "source_idea_one_liner": self.source_idea_one_liner,
            "what_first_attempt_was": self.what_first_attempt_was,
            "what_actually_worked": self.what_actually_worked,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Origin":
        return cls(
            source_run=str(d.get("source_run", "")),
            source_domain=str(d.get("source_domain", "")),
            source_idea_one_liner=str(d.get("source_idea_one_liner", "")),
            what_first_attempt_was=str(d.get("what_first_attempt_was", "")),
            what_actually_worked=str(d.get("what_actually_worked", "")),
        )


@dataclass
class Memory:
    """
    A single experience memory.

    Constructed from a markdown file with YAML frontmatter, or programmatically
    by an extractor / the CLI. ``Memory.to_markdown()`` round-trips the file
    contents predictably so manual edits to live memories survive reindexing.
    """

    id: str
    created_at: str
    extraction_approach: str
    problem_class: ProblemClass
    insight: str
    origin: Origin
    domain_tags: List[str] = field(default_factory=list)
    phase_tags: List[str] = field(default_factory=list)
    confidence: str = "medium"
    votes: Dict[str, int] = field(default_factory=lambda: {
        "used": 0, "helpful": 0, "irrelevant": 0,
    })
    body: str = ""

    # Schema lifecycle helpers

    def validate(self) -> List[str]:
        """
        Return a list of validation errors. Empty list means the memory is
        well-formed enough to write to disk. Callers decide whether to raise.
        """
        errs: List[str] = []
        if not _is_well_formed_id(self.id):
            errs.append(f"id {self.id!r} must match m_* or d_* with lower-snake slug")
        if self.extraction_approach not in VALID_APPROACHES:
            errs.append(
                f"extraction_approach must be one of {VALID_APPROACHES}; "
                f"got {self.extraction_approach!r}"
            )
        if self.confidence not in VALID_CONFIDENCE:
            errs.append(
                f"confidence must be one of {VALID_CONFIDENCE}; "
                f"got {self.confidence!r}"
            )
        if not self.problem_class.what.strip():
            errs.append("problem_class.what is required")
        if not self.insight.strip():
            errs.append("insight is required")
        if not self.origin.source_run.strip():
            errs.append("origin.source_run is required")
        if not self.origin.source_domain.strip():
            errs.append("origin.source_domain is required")
        if not self.origin.what_first_attempt_was.strip():
            errs.append(
                "origin.what_first_attempt_was is required — if the writer "
                "cannot describe the first (wrong) attempt, the insight isn't "
                "memory-worthy"
            )
        if not self.domain_tags:
            errs.append("domain_tags must include at least the source domain")
        elif self.origin.source_domain not in self.domain_tags:
            errs.append(
                f"domain_tags must include origin.source_domain "
                f"({self.origin.source_domain!r})"
            )
        return errs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "extraction_approach": self.extraction_approach,
            "problem_class": self.problem_class.to_dict(),
            "insight": self.insight,
            "origin": self.origin.to_dict(),
            "domain_tags": list(self.domain_tags),
            "phase_tags": list(self.phase_tags),
            "confidence": self.confidence,
            "votes": dict(self.votes),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], body: str = "") -> "Memory":
        votes_default = {"used": 0, "helpful": 0, "irrelevant": 0}
        votes_default.update(d.get("votes", {}) or {})
        return cls(
            id=str(d.get("id", "")),
            created_at=str(d.get("created_at", "")),
            extraction_approach=str(d.get("extraction_approach", "manual")),
            problem_class=ProblemClass.from_dict(d.get("problem_class", {})),
            insight=str(d.get("insight", "")),
            origin=Origin.from_dict(d.get("origin", {})),
            domain_tags=list(d.get("domain_tags", [])),
            phase_tags=list(d.get("phase_tags", [])),
            confidence=str(d.get("confidence", "medium")),
            votes=votes_default,
            body=body,
        )

    # Round-tripping with disk files

    def to_markdown(self) -> str:
        """
        Render the memory as a Markdown file with YAML frontmatter.

        We use ``json.dumps`` to encode the frontmatter rather than yaml.dump.
        JSON is a strict subset of YAML, so any YAML parser reads it
        unambiguously, and we avoid a runtime dependency.
        """
        payload = self.to_dict()
        fm = json.dumps(payload, indent=2, ensure_ascii=False)
        body = self.body.strip()
        if body:
            return f"{_FENCE}\n{fm}\n{_FENCE}\n\n{body}\n"
        return f"{_FENCE}\n{fm}\n{_FENCE}\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Memory":
        """
        Parse a markdown file with YAML or JSON frontmatter into a Memory.

        Accepts either of:
          - JSON-as-YAML frontmatter (what we write)
          - True YAML frontmatter (what humans write by hand)
        """
        fm_text, body = _split_frontmatter(text)
        data = _parse_frontmatter(fm_text)
        return cls.from_dict(data, body=body.strip())

    def public_view(self) -> Dict[str, Any]:
        """
        Return the memory as it should appear when injected into a future
        agent's context: provenance redacted, votes elided.

        Retrieval calls this when assembling ``MEMORIES_FROM_PAST_RUNS.md``.
        """
        return {
            "id": self.id,
            "problem_class": self.problem_class.to_dict(),
            "insight": self.insight,
            "domain_tags": list(self.domain_tags),
            "phase_tags": list(self.phase_tags),
            "confidence": self.confidence,
            "body": self.body,
        }


# Frontmatter helpers

def _split_frontmatter(text: str) -> tuple[str, str]:
    """
    Pull the YAML/JSON frontmatter out of a markdown file.

    Returns ``(frontmatter_text, body_text)``. Raises ``ValueError`` if the
    file does not start with a fence.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError("memory file must start with a '---' fence")
    closing = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            closing = i
            break
    if closing is None:
        raise ValueError("memory file missing closing '---' fence")
    fm = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1:])
    return fm, body


def _parse_frontmatter(fm_text: str) -> Dict[str, Any]:
    """
    Parse the frontmatter into a dict.

    Prefers PyYAML when available — handles every well-formed YAML the user
    might hand-write. Falls back to ``json.loads`` for our own machine-written
    JSON files when PyYAML isn't installed.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(fm_text)
        if not isinstance(data, dict):
            raise ValueError("frontmatter must be a mapping")
        return data
    except ImportError:
        return json.loads(fm_text)


# ID generation

def _is_well_formed_id(s: str) -> bool:
    """Allow either live ids ``m_<slug>`` or draft ids ``d_<slug>``."""
    return bool(re.fullmatch(r"[md]_[a-z0-9][a-z0-9_]{0,127}", s))


def _slugify(text: str, max_len: int = 60) -> str:
    """Reduce arbitrary text to a lower-snake slug suitable for filenames."""
    text = re.sub(r"[^a-z0-9]+", "_", text.lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "memory"


def quarter_tag(when: Optional[datetime] = None) -> str:
    """Return a ``YYYYqN`` quarter tag for memory ids (e.g. ``2026q2``)."""
    when = when or datetime.now(timezone.utc)
    return f"{when.year}q{(when.month - 1) // 3 + 1}"


def now_iso() -> str:
    """Current UTC time as a second-precision ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mint_live_id(insight: str, when: Optional[datetime] = None) -> str:
    """Generate a fresh ``m_<quarter>_<slug>`` id from an insight string."""
    return f"m_{quarter_tag(when)}_{_slugify(insight)}"


def mint_draft_id(insight: str) -> str:
    """Generate a fresh ``d_<slug>`` id for a draft (no quarter prefix)."""
    return f"d_{_slugify(insight)}"


# The store

class MemoryStore:
    """
    On-disk store for live, draft, and archived memories.

    Construction does NOT touch the filesystem aside from resolving the root
    path. Call ``ensure_layout()`` to create the directory tree if it doesn't
    exist yet (the CLI does this once at startup; agents shouldn't need to).
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else DEFAULT_MEMORY_ROOT

    # Filesystem layout

    def ensure_layout(self) -> None:
        """Create live/, drafts/, archived/, and an empty index if missing."""
        for sub in (LIVE_DIR, DRAFTS_DIR, ARCHIVED_DIR):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        idx = self.root / INDEX_FILE
        if not idx.exists():
            idx.write_text(json.dumps({"memories": []}, indent=2) + "\n",
                           encoding="utf-8")

    @property
    def live_dir(self) -> Path:
        return self.root / LIVE_DIR

    @property
    def drafts_dir(self) -> Path:
        return self.root / DRAFTS_DIR

    @property
    def archived_dir(self) -> Path:
        return self.root / ARCHIVED_DIR

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_FILE

    # Single-memory CRUD

    def write(self, memory: Memory, kind: str = "live",
              run_id: Optional[str] = None,
              approach: Optional[str] = None) -> Path:
        """
        Persist ``memory`` to disk.

        ``kind`` is one of ``"live"``, ``"draft"``, or ``"archived"``. For
        drafts, ``run_id`` is the workspace slug the draft came from, and
        ``approach`` selects the ``A``/``B`` subdir. Raises ``ValueError`` if
        the memory fails validation.
        """
        errs = memory.validate()
        if errs:
            raise ValueError(
                f"memory {memory.id} is not well-formed:\n  - "
                + "\n  - ".join(errs)
            )

        path = self._path_for(memory.id, kind, run_id, approach)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(memory.to_markdown(), encoding="utf-8")
        if kind == "live":
            self.reindex()
        return path

    def read(self, path: Path) -> Memory:
        """Load a memory from a specific file path."""
        return Memory.from_markdown(Path(path).read_text(encoding="utf-8"))

    def get_live(self, memory_id: str) -> Optional[Memory]:
        """Look up a live memory by id, or None if not present."""
        for p in self.live_dir.glob(f"{memory_id}*.md"):
            return self.read(p)
        return None

    # Bulk listing + filtering

    def list_live(self) -> List[Memory]:
        """Return every promoted memory."""
        return [self.read(p) for p in sorted(self.live_dir.glob("m_*.md"))]

    def list_drafts(self, run_id: Optional[str] = None,
                    approach: Optional[str] = None) -> List[Memory]:
        """
        Return drafts, optionally scoped to a single run and/or approach.
        """
        root = self.drafts_dir
        if run_id:
            root = root / f"run_{run_id}"
        if approach:
            if not run_id:
                raise ValueError("approach filter requires a run_id")
            root = root / approach
        if not root.exists():
            return []
        return [self.read(p) for p in sorted(root.rglob("d_*.md"))]

    def filter_live(self, domain: Optional[str] = None,
                    tags_any: Optional[Iterable[str]] = None) -> List[Memory]:
        """
        Return promoted memories whose ``domain_tags`` match the filter.

        ``domain`` matches a memory whose ``origin.source_domain`` equals it.
        ``tags_any`` matches memories that share at least one tag.
        """
        out = []
        tags_any_set = set(tags_any or [])
        for m in self.list_live():
            if domain and m.origin.source_domain != domain:
                continue
            if tags_any_set and not (tags_any_set & set(m.domain_tags)):
                continue
            out.append(m)
        return out

    # State transitions

    def promote(self, draft: Memory, run_id: str,
                approach: str = "manual") -> Path:
        """
        Promote a draft into ``live/`` with a freshly minted ``m_*`` id.

        The draft file on disk is deleted to avoid double-counting. The
        promoted memory inherits the draft's content but gets a new id +
        ``extraction_approach`` (defaults to ``manual`` for hand-promotion).
        """
        new_id = mint_live_id(draft.insight)
        promoted = Memory(
            id=new_id,
            created_at=now_iso(),
            extraction_approach=approach,
            problem_class=draft.problem_class,
            insight=draft.insight,
            origin=draft.origin,
            domain_tags=draft.domain_tags,
            phase_tags=draft.phase_tags,
            confidence=draft.confidence,
            votes={"used": 0, "helpful": 0, "irrelevant": 0},
            body=draft.body,
        )
        path = self.write(promoted, kind="live")

        # Remove the source draft file if we can locate it
        for p in (self.drafts_dir / f"run_{run_id}").rglob(f"{draft.id}*.md"):
            try:
                p.unlink()
            except OSError:
                pass

        return path

    def archive(self, memory_id: str) -> Optional[Path]:
        """Move a live memory into ``archived/``. Returns the new path."""
        match = next(self.live_dir.glob(f"{memory_id}*.md"), None)
        if match is None:
            return None
        target = self.archived_dir / match.name
        self.archived_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(match), str(target))
        self.reindex()
        return target

    # Vote tracking

    def bump_vote(self, memory_id: str, kind: str) -> bool:
        """
        Increment one of ``used`` / ``helpful`` / ``irrelevant`` on a live
        memory. Returns True if the memory was found.
        """
        if kind not in ("used", "helpful", "irrelevant"):
            raise ValueError(f"unknown vote kind: {kind!r}")
        match = next(self.live_dir.glob(f"{memory_id}*.md"), None)
        if match is None:
            return False
        m = self.read(match)
        m.votes[kind] = int(m.votes.get(kind, 0)) + 1
        match.write_text(m.to_markdown(), encoding="utf-8")
        self.reindex()
        return True

    # Index management

    def reindex(self) -> Dict[str, Any]:
        """
        Rebuild ``index.json`` from the files in ``live/``.

        Returns the new index dict. Always safe to call.
        """
        memories = []
        for p in sorted(self.live_dir.glob("m_*.md")):
            try:
                m = self.read(p)
            except (ValueError, json.JSONDecodeError, OSError):
                continue
            memories.append({
                "id": m.id,
                "path": str(p.relative_to(self.root)),
                "created_at": m.created_at,
                "extraction_approach": m.extraction_approach,
                "domain": m.origin.source_domain,
                "domain_tags": m.domain_tags,
                "phase_tags": m.phase_tags,
                "confidence": m.confidence,
                "votes": m.votes,
                "what": m.problem_class.what,
            })
        index = {
            "memories": memories,
            "rebuilt_at": now_iso(),
            "count": len(memories),
        }
        self.index_path.write_text(
            json.dumps(index, indent=2) + "\n", encoding="utf-8",
        )
        return index

    def load_index(self) -> Dict[str, Any]:
        """Read the index from disk, rebuilding it if absent."""
        if not self.index_path.exists():
            return self.reindex()
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self.reindex()

    # Internal: path resolution

    def _path_for(self, memory_id: str, kind: str,
                  run_id: Optional[str], approach: Optional[str]) -> Path:
        if kind == "live":
            return self.live_dir / f"{memory_id}.md"
        if kind == "archived":
            return self.archived_dir / f"{memory_id}.md"
        if kind == "draft":
            if not run_id:
                raise ValueError("draft kind requires run_id")
            if not approach:
                raise ValueError("draft kind requires approach")
            return self.drafts_dir / f"run_{run_id}" / approach / f"{memory_id}.md"
        raise ValueError(f"unknown kind {kind!r}")
