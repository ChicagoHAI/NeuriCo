"""
AutoResearch cross-run whiteboard.

Tips written by any comment_handler run linger across rejected attempts so
the proposer for the next attempt can see them. Each tip lives with a
category and a status:

    active   : still relevant. shown to agents.
    cleared  : comment_handler declared it was incorporated. Only clearable
               for non-informative tips. Not shown to agents.
    pruned   : proposer removed it as wrong / unproductive. Not shown.

Only *active* tips appear in view / render. Cleared and pruned tips stay
in the file for audit; a periodic compaction step can be added later.

Categories:
    insight       : specific observation about the code or problem
    design        : proposed design decision, may become code
    pitfall       : something to avoid
    code_pattern  : reusable pattern the next handler might want
    informative   : general experiment wisdom; NOT clearable by handlers,
                    only prunable by the proposer

CLI (subset run inside a NeuriCo workspace):

    python3 -m core.whiteboard view [--json]
    python3 -m core.whiteboard add-tip \\
        --category insight \\
        --content "..." \\
        [--affects solver.py,judge/verify.py] \\
        [--author "comment_handler@a1b2c3d/attempt_2"]
    python3 -m core.whiteboard clear-tip T3 \\
        [--author "comment_handler@a1b2c3d/attempt_2"]
    python3 -m core.whiteboard prune-tip T7 \\
        --reason "..." [--author "autoresearch_proposer"]

Storage: <workspace>/logs/experiment-autoresearch/whiteboard.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_VERSION = 1
WHITEBOARD_FILENAME = "whiteboard.json"

CATEGORIES: tuple[str, ...] = ("insight", "design", "pitfall", "code_pattern", "informative")
INFORMATIVE_CATEGORY = "informative"

STATUS_ACTIVE = "active"
STATUS_CLEARED = "cleared"
STATUS_PRUNED = "pruned"


@dataclass
class Tip:
    id: str
    category: str
    content: str
    status: str = STATUS_ACTIVE
    author: str = ""
    written_at: float = 0.0
    affects: list[str] = field(default_factory=list)
    # Set on clear / prune:
    cleared_by: str = ""     # author string of the handler that claimed it
    cleared_at: float = 0.0
    pruned_reason: str = ""
    pruned_at: float = 0.0

    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def is_informative(self) -> bool:
        return self.category == INFORMATIVE_CATEGORY


class WhiteboardError(RuntimeError):
    pass


def whiteboard_path(work_dir: Path) -> Path:
    return Path(work_dir) / "logs" / "experiment-autoresearch" / WHITEBOARD_FILENAME


# Directories that identify a NeuriCo AutoResearch workspace. Auto-detect
# walks up from cwd looking for any of these markers.
WORKSPACE_MARKERS = (
    Path("logs") / "experiment-autoresearch",
    Path(".neurico"),
)


def find_workspace_root(start: Path | str | None = None) -> Path:
    """
    Locate the NeuriCo workspace by walking up from `start` (default: cwd).

    Returns the first ancestor (including start itself) that contains one of
    the WORKSPACE_MARKERS. Raises FileNotFoundError with a clear message if
    nothing is found before the filesystem root.

    Used when the CLI is invoked without an explicit --workspace so an agent
    can just call `whiteboard view` from anywhere inside the workspace tree.
    """
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    for candidate in (here, *here.parents):
        for marker in WORKSPACE_MARKERS:
            if (candidate / marker).exists():
                return candidate
    raise FileNotFoundError(
        f"Could not locate a NeuriCo workspace from {here!s}. "
        "Expected an ancestor containing `logs/experiment-autoresearch/` or "
        "`.neurico/`. Pass --workspace <PATH> explicitly, or cd into a "
        "workspace before running."
    )


class Whiteboard:
    """
    JSON-on-disk whiteboard. Single-writer expected (the current agent turn
    calling the CLI). Atomic save via temp-file + os.replace.
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.path = whiteboard_path(self.work_dir)
        self.schema_version: int = SCHEMA_VERSION
        self._next_id_num: int = 1
        self.tips: list[Tip] = []

    # ---- persistence ----

    def load(self) -> "Whiteboard":
        if not self.path.exists():
            return self
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.schema_version = int(data.get("schema_version", SCHEMA_VERSION))
        self._next_id_num = int(data.get("next_id_num", 1))
        self.tips = []
        for raw in data.get("tips", []):
            # tolerate unknown extra keys
            allowed = {k.name for k in Tip.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            filtered = {k: v for k, v in raw.items() if k in allowed}
            filtered.setdefault("affects", [])
            self.tips.append(Tip(**filtered))
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "next_id_num": self._next_id_num,
            "saved_at": time.time(),
            "tips": [asdict(t) for t in self.tips],
        }
        serialized = json.dumps(payload, indent=2, sort_keys=False)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".whiteboard.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    # ---- operations ----

    def _new_id(self) -> str:
        tid = f"T{self._next_id_num}"
        self._next_id_num += 1
        return tid

    def find(self, tip_id: str) -> Optional[Tip]:
        for t in self.tips:
            if t.id == tip_id:
                return t
        return None

    def add_tip(
        self,
        content: str,
        category: str,
        *,
        author: str = "",
        affects: Optional[Iterable[str]] = None,
    ) -> Tip:
        content = content.strip()
        if not content:
            raise WhiteboardError("tip content is empty")
        if category not in CATEGORIES:
            raise WhiteboardError(
                f"unknown category {category!r}; must be one of {CATEGORIES}"
            )
        tip = Tip(
            id=self._new_id(),
            category=category,
            content=content,
            author=author,
            written_at=time.time(),
            affects=sorted(set(affects or [])),
        )
        self.tips.append(tip)
        return tip

    def clear_tip(self, tip_id: str, *, author: str = "") -> Tip:
        t = self.find(tip_id)
        if t is None:
            raise WhiteboardError(f"no tip with id {tip_id!r}")
        if t.status != STATUS_ACTIVE:
            raise WhiteboardError(
                f"tip {tip_id} is already {t.status}, cannot clear"
            )
        if t.is_informative():
            raise WhiteboardError(
                f"tip {tip_id} is category=informative; comment_handler cannot "
                "clear it. Only the proposer can prune informative tips."
            )
        t.status = STATUS_CLEARED
        t.cleared_by = author
        t.cleared_at = time.time()
        return t

    def prune_tip(self, tip_id: str, *, reason: str, author: str = "") -> Tip:
        reason = (reason or "").strip()
        if not reason:
            raise WhiteboardError("prune_tip requires a non-empty --reason")
        t = self.find(tip_id)
        if t is None:
            raise WhiteboardError(f"no tip with id {tip_id!r}")
        if t.status != STATUS_ACTIVE:
            raise WhiteboardError(
                f"tip {tip_id} is already {t.status}, cannot prune"
            )
        t.status = STATUS_PRUNED
        t.pruned_reason = reason
        t.pruned_at = time.time()
        # Author is recorded on the pruned tip for audit even though we
        # don't have a dedicated field; embed it in the reason if needed.
        if author:
            t.pruned_reason = f"[{author}] {reason}"
        return t

    # ---- view / render ----

    def active_tips(self) -> list[Tip]:
        return [t for t in self.tips if t.is_active()]

    def render_markdown(self) -> str:
        """Human/agent-readable rendering of active tips only."""
        active = self.active_tips()
        if not active:
            return "_(whiteboard has no active tips)_\n"
        lines: list[str] = []
        lines.append(
            "> Tips below come from prior autoresearch attempts, including "
            "REJECTED ones. Treat them as hints, not ground truth. If a tip "
            "contradicts your reasoning or the current scoring rules, "
            "ignore it (comment_handler) or prune it (proposer)."
        )
        lines.append("")
        for t in active:
            affects = f" [{', '.join(t.affects)}]" if t.affects else ""
            lines.append(f"### {t.id} - {t.category}{affects}")
            if t.author:
                lines.append(f"_by {t.author}_")
            lines.append("")
            lines.append(t.content)
            lines.append("")
        return "\n".join(lines)


# ---- CLI ----

def _resolve_workspace(args: argparse.Namespace) -> Path:
    """Turn --workspace (or its absence) into a concrete path, with auto-detect."""
    if args.workspace:
        p = Path(args.workspace).resolve()
        if not p.exists():
            raise FileNotFoundError(f"--workspace {p} does not exist")
        return p
    return find_workspace_root()


def _load(work_dir: Path) -> Whiteboard:
    wb = Whiteboard(work_dir)
    wb.load()
    return wb


def _cmd_view(args: argparse.Namespace) -> int:
    try:
        ws = _resolve_workspace(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb = _load(ws)
    if args.json:
        active = [asdict(t) for t in wb.active_tips()]
        print(json.dumps(active, indent=2))
    else:
        print(wb.render_markdown(), end="")
    return 0


def _cmd_add_tip(args: argparse.Namespace) -> int:
    try:
        ws = _resolve_workspace(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb = _load(ws)
    affects = [s.strip() for s in (args.affects or "").split(",") if s.strip()]
    try:
        tip = wb.add_tip(
            content=args.content,
            category=args.category,
            author=args.author or "",
            affects=affects,
        )
    except WhiteboardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb.save()
    print(f"added {tip.id}")
    return 0


def _cmd_clear_tip(args: argparse.Namespace) -> int:
    try:
        ws = _resolve_workspace(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb = _load(ws)
    try:
        tip = wb.clear_tip(args.tip_id, author=args.author or "")
    except WhiteboardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb.save()
    print(f"cleared {tip.id}")
    return 0


def _cmd_prune_tip(args: argparse.Namespace) -> int:
    try:
        ws = _resolve_workspace(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb = _load(ws)
    try:
        tip = wb.prune_tip(args.tip_id, reason=args.reason, author=args.author or "")
    except WhiteboardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    wb.save()
    print(f"pruned {tip.id}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whiteboard",
        description="AutoResearch cross-run whiteboard CLI.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root. If omitted, auto-detected by walking up from "
             "cwd looking for `logs/experiment-autoresearch/` or `.neurico/`. "
             "The whiteboard file is at "
             "<workspace>/logs/experiment-autoresearch/whiteboard.json.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("view", help="Print active tips.")
    v.add_argument("--json", action="store_true", help="Emit JSON, not markdown.")
    v.set_defaults(func=_cmd_view)

    a = sub.add_parser(
        "add-tip",
        help="Record a new tip. Called by comment_handler. Categories: "
             + ", ".join(CATEGORIES),
    )
    a.add_argument("--category", required=True, choices=CATEGORIES)
    a.add_argument("--content", required=True, help="The tip text.")
    a.add_argument(
        "--affects",
        default="",
        help="Comma-separated list of files this tip pertains to.",
    )
    a.add_argument(
        "--author",
        default="",
        help="Optional attribution string (e.g. 'comment_handler@sha/attempt_2').",
    )
    a.set_defaults(func=_cmd_add_tip)

    c = sub.add_parser(
        "clear-tip",
        help="Mark a tip as incorporated. Called by comment_handler. "
             "Refuses on category=informative.",
    )
    c.add_argument("tip_id", help="Tip id, e.g. T3.")
    c.add_argument("--author", default="", help="Optional attribution.")
    c.set_defaults(func=_cmd_clear_tip)

    p = sub.add_parser(
        "prune-tip",
        help="Remove a tip as wrong/unproductive. Called by proposer only.",
    )
    p.add_argument("tip_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--author", default="autoresearch_proposer")
    p.set_defaults(func=_cmd_prune_tip)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
