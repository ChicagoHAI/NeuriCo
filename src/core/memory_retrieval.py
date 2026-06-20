"""
Pre-run memory retrieval and post-run feedback.

This module is the bridge between the on-disk memory store and a NeuriCo
experiment run. Two responsibilities:

  1. ``retrieve_for_idea`` runs BEFORE ``experiment_runner``. It picks live
     memories that might apply to the current idea (Phase 2: domain pre-filter
     only — no LLM selector), bumps each chosen memory's ``used`` counter,
     and writes ``MEMORIES_FROM_PAST_RUNS.md`` into the workspace with all
     provenance fields stripped. The runner reads this file as part of its
     PHASE 0 step (see ``templates/agents/session_instructions.txt``).

  2. ``apply_feedback`` runs AFTER ``experiment_runner``. It parses the
     ``MEMORY_FEEDBACK.md`` the runner produced — one acknowledgment per
     injected memory: ``applied`` or ``not_applicable``. ``applied`` bumps
     ``helpful``; ``not_applicable`` bumps ``irrelevant``. Missing or
     malformed feedback is logged but never blocks the pipeline.

The two halves close the loop: future retrieval can rank memories by
hit-rate (``helpful / used``) once enough data accumulates.

This module knows NOTHING about LLM providers or agent runners — it owns
filesystem I/O only. The orchestrator wires it into the pipeline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.memory_store import Memory, MemoryStore


MEMORIES_FILENAME = "MEMORIES_FROM_PAST_RUNS.md"
FEEDBACK_FILENAME = "MEMORY_FEEDBACK.md"

# Sidecar recording which memory ids the retrieval step actually surfaced
# in this workspace. apply_feedback() consults it so votes can only be bumped
# for memories the runner was given a chance to see — feedback referring to
# ids outside this set is dropped with a warning. Without this guard, a runner
# that hallucinates ids (or two runs sharing a workspace) would pollute the
# vote counts that the comparison harness later relies on.
INJECTED_SIDECAR_REL = Path(".neurico") / "memories_injected.json"

# Maximum number of memories ever injected into a single run. Caps the
# runner's PHASE 0 reading cost so a thousand-memory store doesn't drown
# a new experiment. With Phase 2's no-LLM filter, this is a hard ceiling;
# Phase 5 can raise it once the selector ranks candidates first.
DEFAULT_MAX_MEMORIES = 10


# Retrieval (pre-runner)

def retrieve_for_idea(
    idea: Dict[str, Any],
    store: MemoryStore,
    work_dir: Path,
    *,
    max_memories: int = DEFAULT_MAX_MEMORIES,
) -> Dict[str, Any]:
    """
    Select memories applicable to ``idea`` and write them into the workspace.

    Returns a summary dict:

        {
          "injected": <int>,             # count of memories surfaced
          "memory_ids": [<str>, ...],    # ids of the surfaced memories
          "out_path": "<workspace>/MEMORIES_FROM_PAST_RUNS.md",
          "skipped_reason": <str|None>,  # set when injected == 0 with reason
        }

    Behavior:
      * Empty store or no domain match -> no file written, ``skipped_reason``
        explains why.
      * Domain match -> filter, cap to ``max_memories``, bump ``used``, write.

    The orchestrator passes the surrounding ``idea`` dict; we read only its
    ``domain`` field. Anything richer (an LLM-based selector) goes in Phase 5.
    """
    domain = (idea.get("domain") or "").strip()
    candidates = store.filter_live(domain=domain if domain else None)

    if not candidates:
        return {
            "injected": 0,
            "memory_ids": [],
            "out_path": None,
            "skipped_reason": (
                f"no live memories for domain {domain!r}"
                if domain else "no live memories"
            ),
        }

    chosen = candidates[:max_memories]
    for m in chosen:
        store.bump_vote(m.id, "used")

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / MEMORIES_FILENAME
    out_path.write_text(_render_memories_md(chosen), encoding="utf-8")

    # Record which ids were actually surfaced so post-run feedback can guard
    # against bumps for ids the runner never saw. Stored under .neurico/ so
    # it travels with the workspace's pipeline state, not with artifacts.
    sidecar = work_dir / INJECTED_SIDECAR_REL
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"injected_ids": [m.id for m in chosen]}, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "injected": len(chosen),
        "memory_ids": [m.id for m in chosen],
        "out_path": str(out_path),
        "skipped_reason": None,
    }


def _render_memories_md(memories: List[Memory]) -> str:
    """
    Render selected memories into the workspace-local Markdown file the
    runner reads. All ``origin.*`` and ``votes.*`` fields are stripped — only
    the abstract problem class + insight + optional body survive.

    The header explains the acknowledgment contract so the runner does not
    have to consult ``session_instructions.txt`` to know what to do.
    """
    parts: List[str] = []
    parts.append("# Memories from past runs\n")
    parts.append(
        "These are insights surfaced by past experiment runs that **might** "
        "apply to this one. Most will not. Treat each memory as a hypothesis "
        "to evaluate against the current idea, not a directive to follow.\n"
    )
    parts.append("## What you must do BEFORE planning\n")
    parts.append(
        "Read each memory below. For each one, write an acknowledgment to "
        f"`{FEEDBACK_FILENAME}` in this exact format:\n"
    )
    parts.append(
        "```yaml\n"
        "- memory_id: <id from below>\n"
        "  decision: applied            # or: not_applicable\n"
        "  reason: <one sentence — why it does or doesn't fit this idea>\n"
        "```\n"
    )
    parts.append(
        "If a memory clearly applies, prefer to **apply** it and adapt your "
        "plan accordingly. If it does not, write `not_applicable` with a "
        "specific reason — \"didn't seem relevant\" is not enough.\n"
    )
    parts.append("---\n")

    for i, m in enumerate(memories, start=1):
        pc = m.problem_class
        parts.append(f"## Memory {i} — `{m.id}`\n")
        parts.append(f"**Problem class.** {pc.what}\n")

        if pc.shape:
            parts.append("**Abstract preconditions:**\n")
            for entry in pc.shape:
                if isinstance(entry, dict):
                    for k, v in entry.items():
                        parts.append(f"- *{k}*: {v}\n")
                else:
                    parts.append(f"- {entry}\n")
            parts.append("\n")

        if pc.signal_to_recognize:
            parts.append("**Signal to recognize:**\n")
            for sig in pc.signal_to_recognize:
                parts.append(f"- {sig}\n")
            parts.append("\n")

        parts.append(f"**Insight.** {m.insight.strip()}\n")
        if m.body.strip():
            parts.append(f"\n{m.body.strip()}\n")
        parts.append("\n---\n")

    return "".join(parts)


# Feedback (post-runner)

def apply_feedback(
    work_dir: Path,
    store: MemoryStore,
) -> Dict[str, Any]:
    """
    Parse the runner's ``MEMORY_FEEDBACK.md`` and bump vote counters.

    Returns a summary dict:

        {
          "processed": <int>,         # entries we found
          "helpful": <int>,           # bumps applied to helpful
          "irrelevant": <int>,        # bumps applied to irrelevant
          "skipped": <int>,           # entries we couldn't act on
          "errors": [<str>, ...],     # warnings (e.g. unknown id)
          "feedback_path": <str|None>,
        }

    A missing feedback file is NOT an error — it just means the runner had
    nothing injected, or skipped the acknowledgment phase. Either way the
    pipeline continues.
    """
    fb_path = Path(work_dir) / FEEDBACK_FILENAME
    summary: Dict[str, Any] = {
        "processed": 0, "helpful": 0, "irrelevant": 0, "skipped": 0,
        "errors": [], "feedback_path": str(fb_path) if fb_path.exists() else None,
    }
    if not fb_path.exists():
        return summary

    # Load the injected-ids sidecar. If it's absent (e.g. retrieval didn't run
    # this workspace) we skip the guard and accept feedback for any id, since
    # there's no way to know what was actually shown.
    injected_ids = _load_injected_ids(Path(work_dir))

    try:
        entries = _parse_feedback_yaml(fb_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        summary["errors"].append(f"could not parse {fb_path.name}: {exc}")
        return summary

    for entry in entries:
        summary["processed"] += 1
        mid = entry.get("memory_id", "").strip()
        decision = entry.get("decision", "").strip().lower()
        if not mid:
            summary["skipped"] += 1
            summary["errors"].append("entry missing memory_id")
            continue

        # Guard: feedback about an id we never injected is dropped. Without
        # this, hallucinated ids would pollute the vote stats the comparison
        # harness relies on. If the sidecar is missing (None), permit all.
        if injected_ids is not None and mid not in injected_ids:
            summary["skipped"] += 1
            summary["errors"].append(
                f"{mid}: feedback for id not injected into this workspace"
            )
            continue

        if decision == "applied":
            kind = "helpful"
        elif decision in ("not_applicable", "not-applicable", "n/a"):
            kind = "irrelevant"
        else:
            summary["skipped"] += 1
            summary["errors"].append(
                f"{mid}: unknown decision {decision!r} "
                "(expected 'applied' or 'not_applicable')"
            )
            continue

        if store.bump_vote(mid, kind):
            summary[kind] += 1
        else:
            summary["skipped"] += 1
            summary["errors"].append(f"{mid}: not found in live store")

    return summary


def _load_injected_ids(work_dir: Path) -> Optional[set]:
    """
    Return the set of memory ids that retrieval recorded for this workspace,
    or None if no sidecar exists (e.g. an older workspace, or retrieval was
    skipped). Returning None disables the guard so callers can opt out.
    """
    sidecar = work_dir / INJECTED_SIDECAR_REL
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return set(data.get("injected_ids", []))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_feedback_yaml(text: str) -> List[Dict[str, str]]:
    """
    Parse the runner's feedback file.

    The expected format is a YAML list of mappings with three keys each
    (``memory_id``, ``decision``, ``reason``). We prefer PyYAML when
    available; otherwise we fall back to a tiny line-based parser that
    handles the canonical form.

    Returns a list of dicts. Raises ``ValueError`` on truly unparseable input.
    """
    text = _strip_yaml_codefence(text)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or []
        if not isinstance(data, list):
            raise ValueError("feedback root must be a YAML list")
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append({
                "memory_id": str(item.get("memory_id", "")),
                "decision": str(item.get("decision", "")),
                "reason": str(item.get("reason", "")),
            })
        return out
    except ImportError:
        return _parse_feedback_fallback(text)


def _strip_yaml_codefence(text: str) -> str:
    """
    Remove leading/trailing ```yaml ... ``` fences. The runner often pastes
    the feedback inside a fence because that's how the prompt example shows
    it. We accept either form.
    """
    text = text.strip()
    fence = re.compile(r"^```(?:yaml)?\s*\n", re.MULTILINE)
    text = fence.sub("", text, count=1)
    text = re.sub(r"\n```\s*$", "", text)
    return text


def _parse_feedback_fallback(text: str) -> List[Dict[str, str]]:
    """
    Minimal line-based parser for the canonical feedback form when PyYAML is
    unavailable. Recognizes only the three keys we care about.
    """
    entries: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None

    item_re = re.compile(r"^-\s*memory_id\s*:\s*(.+?)\s*$")
    key_re = re.compile(r"^\s+(memory_id|decision|reason)\s*:\s*(.+?)\s*$")

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = item_re.match(line)
        if m:
            if current:
                entries.append(current)
            current = {"memory_id": m.group(1).strip(),
                       "decision": "", "reason": ""}
            continue
        m = key_re.match(line)
        if m and current is not None:
            current[m.group(1)] = m.group(2).strip()
    if current:
        entries.append(current)
    return entries


# Draft collection (post-runner)

def collect_drafts(
    work_dir: Path,
    store: MemoryStore,
    *,
    approach: str = "A",
) -> Dict[str, Any]:
    """
    Find and validate memory drafts the runner wrote during reflection.

    The runner writes drafts under
    ``~/.neurico/memories/drafts/run_<EXP_ID>/<approach>/d_*.md`` per the
    PHASE 5.5 contract in ``templates/agents/session_instructions.txt``. We
    parse each, run the schema validator, and report counts + per-file
    errors. Validation errors are LOGGED but never raised — a malformed
    draft is dropped from the count, not from the disk (the operator can
    inspect it later).

    ``approach`` selects which sub-bucket to walk:
        "A"  — runner self-reflection drafts (Phase 3)
        "B"  — manager-observer drafts (Phase 4, not yet implemented)

    Returns a summary dict suitable for ``results["stages"]["memory_drafts"]``:

        {
          "approach": "A",
          "run_id": "<workspace-slug or None>",
          "scanned": <int>,                 # total .md files found
          "valid": <int>,                   # passed validation
          "invalid": [<{"path": str, "errors": [str]}>],  # validation failures
          "draft_ids": [<str>, ...],        # ids of valid drafts
        }
    """
    work_dir = Path(work_dir)
    run_id = work_dir.name
    run_root = store.drafts_dir / f"run_{run_id}" / approach
    summary: Dict[str, Any] = {
        "approach": approach,
        "run_id": run_id,
        "scanned": 0,
        "valid": 0,
        "invalid": [],
        "draft_ids": [],
    }
    if not run_root.exists():
        return summary

    for p in sorted(run_root.glob("d_*.md")):
        summary["scanned"] += 1
        try:
            m = store.read(p)
        except (ValueError, OSError) as exc:
            summary["invalid"].append({
                "path": str(p.relative_to(store.root)),
                "errors": [f"unparseable: {exc}"],
            })
            continue

        errs = m.validate()
        if errs:
            summary["invalid"].append({
                "path": str(p.relative_to(store.root)),
                "errors": errs,
            })
            continue

        # An extra approach-specific gate: the contract requires the runner's
        # drafts to declare extraction_approach="runner_self" (not "manual"
        # or "manager_observer"). Drafts that get the approach wrong are
        # almost always a copy-paste bug; flag them.
        expected = "runner_self" if approach == "A" else "manager_observer"
        if m.extraction_approach != expected:
            summary["invalid"].append({
                "path": str(p.relative_to(store.root)),
                "errors": [
                    f"extraction_approach must be {expected!r} for an "
                    f"approach-{approach} draft, got {m.extraction_approach!r}"
                ],
            })
            continue

        summary["valid"] += 1
        summary["draft_ids"].append(m.id)

    return summary


# Summaries for orchestrator logging

def render_retrieval_summary(result: Dict[str, Any]) -> str:
    """One-line human summary of ``retrieve_for_idea`` for orchestrator logs."""
    if result["injected"] == 0:
        return f"   (none — {result['skipped_reason']})"
    return (
        f"   Injected {result['injected']} memor"
        f"{'y' if result['injected'] == 1 else 'ies'}: "
        f"{', '.join(result['memory_ids'])}"
    )


def render_feedback_summary(result: Dict[str, Any]) -> str:
    """One-line human summary of ``apply_feedback`` for orchestrator logs."""
    if result["feedback_path"] is None:
        return "   (no feedback file produced)"
    msg = (
        f"   helpful={result['helpful']}, "
        f"irrelevant={result['irrelevant']}, "
        f"skipped={result['skipped']}"
    )
    if result["errors"]:
        msg += f"  ({len(result['errors'])} warning"
        msg += "s)" if len(result["errors"]) != 1 else ")"
    return msg


def render_drafts_summary(result: Dict[str, Any]) -> str:
    """One-line human summary of ``collect_drafts`` for orchestrator logs."""
    if result["scanned"] == 0:
        return "   (no drafts written — expected for most runs)"
    base = (
        f"   {result['valid']} valid / {result['scanned']} scanned "
        f"(approach {result['approach']})"
    )
    if result["invalid"]:
        base += f"  — {len(result['invalid'])} invalid (see logs)"
    return base
