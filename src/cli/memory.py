"""
CLI for inspecting, seeding, and curating NeuriCo's experience memory.

Usage:
    python -m cli.memory list                              # list live memories
    python -m cli.memory list --drafts                     # list draft memories
    python -m cli.memory list --domain machine_learning    # filter by domain
    python -m cli.memory show <memory-id>                  # print one memory
    python -m cli.memory add path/to/draft.md              # hand-add a memory
    python -m cli.memory promote <draft-id> --run <slug>   # draft -> live
    python -m cli.memory archive <memory-id>               # live -> archived
    python -m cli.memory reindex                           # rebuild index.json
    python -m cli.memory path                              # print storage root

This CLI is Phase 1 plumbing — Phases 2+ will write to the store directly
from the pipeline, so an interactive operator rarely needs to touch this CLI
unless they're hand-seeding memories or debugging.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

# Add parent directory to path so ``core`` resolves when invoked as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_store import (  # noqa: E402
    DEFAULT_MEMORY_ROOT,
    Memory,
    MemoryStore,
)


def _store(args: argparse.Namespace) -> MemoryStore:
    root = Path(args.root) if args.root else DEFAULT_MEMORY_ROOT
    store = MemoryStore(root=root)
    store.ensure_layout()
    return store


def cmd_list(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.drafts:
        memories = store.list_drafts(run_id=args.run, approach=args.approach)
        kind = "drafts"
    else:
        memories = store.filter_live(
            domain=args.domain,
            tags_any=args.tag or None,
        )
        kind = "live"

    if args.json:
        print(json.dumps([m.to_dict() for m in memories], indent=2))
        return 0

    if not memories:
        print(f"(no {kind} memories)")
        return 0

    width = max(len(m.id) for m in memories)
    print(f"{len(memories)} {kind} memor{'y' if len(memories) == 1 else 'ies'}:")
    print()
    for m in memories:
        votes = m.votes
        score = f"u={votes['used']} h={votes['helpful']} x={votes['irrelevant']}"
        print(f"  {m.id:<{width}}  [{m.confidence:<6}]  {score:<14}  {m.problem_class.what}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    m = store.get_live(args.memory_id)
    if m is None:
        # Maybe it's a draft — fall back to a search across drafts/
        for d in store.list_drafts():
            if d.id == args.memory_id:
                m = d
                break
    if m is None:
        print(f"memory {args.memory_id!r} not found", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(m.to_dict(), indent=2))
        if m.body:
            print()
            print(m.body)
    else:
        print(m.to_markdown())
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """
    Add a hand-written memory file to either live/ or drafts/.

    Reads the file at ``args.path`` (which must already be a well-formed
    memory markdown file), validates it, and writes it into the chosen
    location. For drafts you must supply --run; the slug is taken from the
    memory id otherwise.
    """
    store = _store(args)
    text = Path(args.path).read_text(encoding="utf-8")
    try:
        m = Memory.from_markdown(text)
    except ValueError as exc:
        print(f"could not parse {args.path}: {exc}", file=sys.stderr)
        return 2

    if args.kind == "draft":
        if not args.run:
            print("error: --kind draft requires --run", file=sys.stderr)
            return 2
        path = store.write(m, kind="draft", run_id=args.run,
                           approach=args.approach or "manual")
    else:
        path = store.write(m, kind="live")
    print(f"wrote {path}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    store = _store(args)
    drafts = [d for d in store.list_drafts(run_id=args.run) if d.id == args.draft_id]
    if not drafts:
        print(f"draft {args.draft_id!r} not found under run {args.run!r}",
              file=sys.stderr)
        return 1
    promoted = store.promote(drafts[0], run_id=args.run, approach=args.approach)
    print(f"promoted to {promoted}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    store = _store(args)
    new_path = store.archive(args.memory_id)
    if new_path is None:
        print(f"live memory {args.memory_id!r} not found", file=sys.stderr)
        return 1
    print(f"archived to {new_path}")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    store = _store(args)
    index = store.reindex()
    print(f"reindexed: {index['count']} live memor"
          f"{'y' if index['count'] == 1 else 'ies'}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    """Print the storage root. Handy for shell expansion + debugging."""
    store = _store(args)
    print(store.root)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="manage NeuriCo's experience memory store",
    )
    p.add_argument(
        "--root", default=None,
        help=f"override the storage root (default: {DEFAULT_MEMORY_ROOT})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="list memories")
    sp.add_argument("--drafts", action="store_true",
                    help="list drafts instead of live memories")
    sp.add_argument("--run", help="filter drafts by run id")
    sp.add_argument("--approach", choices=["A", "B", "manual"],
                    help="filter drafts by extraction approach")
    sp.add_argument("--domain", help="filter live memories by source domain")
    sp.add_argument("--tag", action="append", default=[],
                    help="filter live memories by any of these tags (repeatable)")
    sp.add_argument("--json", action="store_true",
                    help="emit JSON instead of a table")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="print one memory")
    sp.add_argument("memory_id")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("add", help="add a hand-written memory file")
    sp.add_argument("path", help="path to a memory markdown file")
    sp.add_argument("--kind", choices=["live", "draft"], default="live")
    sp.add_argument("--run", help="run slug (required when --kind draft)")
    sp.add_argument("--approach", default="manual",
                    help="extraction-approach label for drafts")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("promote", help="move a draft into live/")
    sp.add_argument("draft_id")
    sp.add_argument("--run", required=True)
    sp.add_argument("--approach", default="manual",
                    help="extraction-approach label on the promoted memory")
    sp.set_defaults(func=cmd_promote)

    sp = sub.add_parser("archive", help="move a live memory into archived/")
    sp.add_argument("memory_id")
    sp.set_defaults(func=cmd_archive)

    sp = sub.add_parser("reindex", help="rebuild index.json from live/")
    sp.set_defaults(func=cmd_reindex)

    sp = sub.add_parser("path", help="print the storage root")
    sp.set_defaults(func=cmd_path)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
