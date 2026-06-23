"""
Shared Research State — the world model.

This is the load-bearing primitive for treating the research as a structured,
inspectable object rather than a transcript. Originally the *manager's* private
view (a PI / co-author that reasons over the whole investigation), it is evolving
into **shared memory for multi-agent cooperation**: a single world model that the
manager and the research sub-agents read for context and write their findings,
decisions, experiments, and incidents into.

The data model follows the log-visualizer's **v3** design:

  * **findings are the spine.** A finding is the unit of insight the run produced
    (or failed to produce) — and is itself gradeable.
  * **everything is a decision.** Every consequential choice is a decision tagged
    with the ``finding`` it serves (an ``F-id``, or ``"global"`` for a project-wide
    fork tied to no single finding) and the ``layer`` of that finding's lifecycle
    it sits in (hypothesis / method / experiment_design / interpretation).

Several v3 fields are *review-time* or *interaction-time* and are intentionally
left empty by the live write path — they are filled later by separate agents:

  * ``importance`` / ``sequence`` — a review subagent (needs the full decision set;
    unreliable to self-assign live).
  * ``should_engage`` / ``should_engage_reason`` — a human-interactor subagent.
  * ``author`` — set by whichever agent wrote the node (wiring is owned elsewhere);
    the field exists now so provenance is available once multiple agents write.

Persisted to ``<workspace>/.neurico/research_state.json``. The web server polls
that file to render the live "Research" pane, so writes are atomic (temp file +
os.replace) to avoid torn reads. ``_save`` MERGES under an advisory lock rather
than last-writer-wins, so concurrent multi-agent writes fold into each other
instead of clobbering; see the merge/locking section below.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # POSIX advisory file locks; absent on some platforms (e.g. Windows).
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None

SCHEMA_VERSION = 3

# v3 adds `refuted` (a hypothesis the evidence argues against) as distinct from
# `dead` (abandoned / no longer pursued).
HYP_STATUSES = ("alive", "uncertain", "supported", "refuted", "dead")

# Where in a finding's lifecycle a decision's fork sits.
DECISION_LAYERS = ("hypothesis", "method", "experiment_design", "interpretation")

FINDING_KINDS = ("result", "dead_end", "note")

# How an investigation gathered evidence — the domain discriminator for an
# experiment node (kept domain-general, not tied to a NeuriCo pipeline stage).
EXPERIMENT_MODES = ("empirical_experiment", "computational_analysis",
                    "formal_derivation", "literature_synthesis",
                    "qualitative_analysis", "simulation", "observation", "other")

# Reasons a good PI would pause to involve the human at a decision. Left unset by
# the live writer; a future human-interactor subagent assigns it.
SHOULD_ENGAGE_REASONS = ("scope_choice", "validity_risk", "cost_risk",
                         "human_preference", "irreversible_action", "routine_no")

# Level 2 "PI designs the panel": the manager may declare custom whiteboard
# sections per run, each rendered from a small, safe block vocabulary. Keeping
# the vocabulary fixed (the manager picks *which* blocks and supplies data, not
# raw markup) preserves the client-side escaping that makes the board XSS-safe.
BLOCK_KINDS = ("text", "bullet_list", "key_value", "table", "status_list")

# Reserved ids for the built-in sections. A panel_layout entry that matches one
# of these renders the corresponding core section; any other id is looked up in
# the custom `sections` map.
BUILTIN_SECTIONS = ("crux", "current_best", "narrative",
                    "hypotheses", "open_questions", "decisions", "experiments",
                    "findings")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_defaults(d: Dict[str, Any], defaults: Dict[str, Any]) -> bool:
    """setdefault every key in `defaults`; return True if any was added."""
    changed = False
    for k, v in defaults.items():
        if k not in d:
            d[k] = v
            changed = True
    return changed


# ----------------------------------------------------------- merge / locking
#
# The world model is shared memory: the manager and (in future) research
# sub-agents all read and write it. A naive read-modify-write `_save` is
# last-writer-wins and would clobber a concurrent writer's record. Instead we
# MERGE on save (CRDT-lite): id-keyed entity lists union by id (newest wins),
# and manager-owned scalars are re-asserted only for the fields THIS instance
# touched since it last saved. An advisory flock serializes the read-merge-write
# so the merge sees the latest on-disk state.
#
# Ids are globally unique by construction: every instance mints under its own
# random writer token (`F-<writer>-<n>`, n monotonic per writer), so two writers
# racing from a freshly-empty store mint *different* ids — the union keeps both
# instead of collapsing N records onto a single `F1`. No cross-writer id
# coordination is needed; uniqueness comes from the per-instance token, and the
# numeric suffix is only a per-writer counter (order is carried by `ts`/`sequence`,
# not by the id). The on-disk ids are still folded in when minting so a single
# writer's sequence stays gap-free across reloads.

# id-keyed lists and the timestamp field that breaks ties (newest wins).
_ID_LISTS = {"hypotheses": "updated_at", "experiments": "ts",
             "findings": "ts", "decisions": "ts"}

# Manager-owned fields re-asserted on save only when this instance changed them
# (else the latest on-disk value is kept, so we never clobber another writer).
_DIRTY_SCALARS = ("narrative", "current_best", "crux", "open_questions",
                  "panel_layout")


@contextmanager
def _file_lock(path: Path):
    """Best-effort exclusive advisory lock around a critical section. No-ops if
    fcntl is unavailable (the merge still helps; only the race window widens)."""
    if fcntl is None:
        yield
        return
    lock_path = str(path) + ".lock"
    f = open(lock_path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _ts_of(item: Dict[str, Any], tskey: str) -> str:
    return item.get(tskey) or item.get("updated_at") or item.get("ts") or ""


def _union_by_id(base: Optional[List[Dict[str, Any]]],
                 ours: Optional[List[Dict[str, Any]]],
                 tskey: str) -> List[Dict[str, Any]]:
    """Union two id-keyed lists. Same id: newest by `tskey` wins (tie → ours, the
    freshest intent). New ids from `ours` are appended after the base order."""
    out: List[Dict[str, Any]] = []
    index: Dict[Any, int] = {}
    for it in (base or []):
        iid = it.get("id")
        if iid is not None:
            index[iid] = len(out)
        out.append(dict(it))
    for it in (ours or []):
        iid = it.get("id")
        if iid is not None and iid in index:
            j = index[iid]
            if _ts_of(it, tskey) >= _ts_of(out[j], tskey):
                out[j] = dict(it)
        else:
            if iid is not None:
                index[iid] = len(out)
            out.append(dict(it))
    return out


def _union_incidents(base: Optional[List[Dict[str, Any]]],
                     ours: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Incidents have no id; union by (kind, detail), preserving order, bounded."""
    out = [dict(x) for x in (base or [])]
    seen = {(x.get("kind"), x.get("detail")) for x in out}
    for x in (ours or []):
        key = (x.get("kind"), x.get("detail"))
        if key not in seen:
            seen.add(key)
            out.append(dict(x))
    return out[-50:]


def _merge_sections(base: Optional[Dict[str, Any]],
                    ours: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Custom panel sections keyed by id; newest by updated_at wins per id."""
    out = dict(base or {})
    for sid, sec in (ours or {}).items():
        b = out.get(sid)
        if b is None or _ts_of(sec, "updated_at") >= _ts_of(b, "updated_at"):
            out[sid] = sec
    return out


class ResearchState:
    """Structured, persistent model of the research-in-progress (v3)."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.neurico_dir / "research_state.json"
        # Per-instance writer token that namespaces minted ids (`F-<writer>-<n>`)
        # so concurrent writers never collide on an id — even racing from an empty
        # store. Random (uniqueness, not identity, is what we need); provenance is
        # carried separately by each record's `author` field.
        self._writer = uuid.uuid4().hex[:8]
        # Manager-owned scalar fields this instance has changed since its last
        # save; only these are re-asserted on merge (see _DIRTY_SCALARS / _save).
        self._dirty: set = set()

        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    self.state = json.load(f)
            except (OSError, json.JSONDecodeError):
                self.state = self._blank()
            # Forward-migrate states written before a key existed (e.g. the
            # Level 2 panel fields) so callers can assume every key is present.
            for k, v in self._blank().items():
                self.state.setdefault(k, v)
            # Backfill v3 per-item shape on pre-v3 nodes (flat findings, decisions
            # with no finding/layer, [str] options, etc.).
            self._migrate()
        else:
            self.state = self._blank()
            self._save()

    @staticmethod
    def _blank() -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _now(),
            "narrative": "",        # short rolling summary of where things stand
            "current_best": "",     # champion / best result so far
            "crux": "",             # the single most decision-relevant open issue
            "hypotheses": [],       # {id, statement, status, evidence, links, author, updated_at}
            "experiments": [],      # {id, name, mode, design, agent, ranBy, run_id, rationale, hypothesis, status, result, ts}
            "findings": [],         # {id, text, insight, kind, evidence, links, author, ts}  — the SPINE
            "open_questions": [],   # [str]
            # Every decision belongs to a finding (an F-id) or to "global"; `layer`
            # is one of DECISION_LAYERS. Review/interaction fields (importance,
            # should_engage*) are left empty for later agents.
            "decisions": [],        # {id, finding, layer, question, options[{text,status}], chosen, rationale, by, author, evidence, links, importance, should_engage, should_engage_reason, sequence, ts}
            "incidents": [],        # {ts, kind, detail, author} — auto-logged tool errors + self-reported struggle
            # Level 2 — the PI-designed panel. `panel_layout` is an ordered list
            # of section ids (built-in or custom); empty → default order. Each
            # custom section in `sections` is {title, kind, data, updated_at}.
            "panel_layout": [],     # [section_id, ...]
            "sections": {},         # {id: {title, kind, data, updated_at}}
        }

    # ----------------------------------------------------------- migration
    def _migrate(self) -> None:
        """Backfill the v3 per-item shape on nodes written by an older version so
        every caller can assume the keys are present. Idempotent."""
        changed = False
        for f in self.state.get("findings", []):
            if not str(f.get("id", "")).startswith("F"):
                f["id"] = self._next_id("findings", "F")
                changed = True
            changed |= _set_defaults(
                f, {"insight": "", "kind": "result", "evidence": [],
                    "links": [], "author": "", "ts": _now()})
        for d in self.state.get("decisions", []):
            if not d.get("finding"):
                d["finding"] = "global"
                changed = True
            opts = d.get("options")
            if isinstance(opts, list) and opts and isinstance(opts[0], str):
                d["options"] = self._normalize_options(opts, d.get("chosen", ""))
                changed = True
            changed |= _set_defaults(
                d, {"layer": None, "options": [], "evidence": [], "links": [],
                    "author": "", "importance": "", "should_engage": None,
                    "should_engage_reason": "", "sequence": None})
        for e in self.state.get("experiments", []):
            changed |= _set_defaults(
                e, {"name": "", "mode": "", "design": "",
                    "ranBy": e.get("agent", "")})
        for inc in self.state.get("incidents", []):
            changed |= _set_defaults(inc, {"author": ""})
        for h in self.state.get("hypotheses", []):
            changed |= _set_defaults(h, {"links": [], "author": ""})
        if changed:
            # Plain overwrite: we just loaded and migrated this very file, so the
            # on-disk copy is our own pre-migration source — merging against it
            # would re-introduce the un-migrated records (e.g. an id-less finding)
            # as duplicates. Merge-on-save is for concurrent *external* writers.
            self._save(merge=False)

    # ------------------------------------------------------------------ io
    def _read_disk(self) -> Optional[Dict[str, Any]]:
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _merge_onto(self, disk: Dict[str, Any]) -> Dict[str, Any]:
        """Fold this instance's state onto the latest on-disk state: union the
        id-keyed lists, merge incidents/sections, and re-assert only the
        manager-owned scalars we changed this session. Keeps another writer's
        concurrent records instead of clobbering them."""
        merged = dict(disk)
        for k, v in self._blank().items():
            merged.setdefault(k, v)
        for key, tskey in _ID_LISTS.items():
            merged[key] = _union_by_id(disk.get(key), self.state.get(key), tskey)
        merged["incidents"] = _union_incidents(disk.get("incidents"),
                                               self.state.get("incidents"))
        merged["sections"] = _merge_sections(disk.get("sections"),
                                             self.state.get("sections"))
        for k in self._dirty:
            merged[k] = self.state.get(k)
        merged["schema_version"] = max(int(disk.get("schema_version", 0) or 0),
                                       SCHEMA_VERSION)
        return merged

    def _save(self, merge: bool = True) -> None:
        # Read-merge-write under an advisory lock so concurrent writers fold into
        # each other rather than overwrite. Single-writer behaviour is unchanged
        # (the merge against our own last write is a no-op). merge=False is a plain
        # overwrite, used only when self.state already subsumes the on-disk copy.
        with _file_lock(self.state_file):
            disk = self._read_disk() if merge else None
            merged = self._merge_onto(disk) if disk else self.state
            merged["updated_at"] = _now()
            merged.setdefault("schema_version", SCHEMA_VERSION)
            tmp = self.state_file.with_suffix(".json.tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(merged, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self.state_file)
            except OSError:
                pass
        self.state = merged
        self._dirty = set()

    # -------------------------------------------------------------- mutate
    def _next_id(self, key: str, prefix: str) -> str:
        # Ids are `<prefix>-<writer>-<n>`: the writer token namespaces this
        # instance so two writers minting concurrently from a stale (or empty)
        # view produce different ids — the union keeps both rather than collapsing
        # them. `n` is a per-writer counter derived from the max of OUR existing
        # ids (across our in-memory state and the on-disk copy, so a reload keeps
        # the sequence gap-free), not list length — robust to future deletes.
        mine = f"{prefix}-{self._writer}-"
        items = list(self.state.get(key, []))
        disk = self._read_disk()
        if disk:
            items += list(disk.get(key, []))
        nums = [int(str(x["id"])[len(mine):]) for x in items
                if str(x.get("id", "")).startswith(mine)
                and str(x["id"])[len(mine):].isdigit()]
        return f"{mine}{(max(nums) + 1) if nums else 1}"

    @staticmethod
    def _normalize_options(options: Optional[List[Any]],
                           chosen: str = "") -> List[Dict[str, str]]:
        """Coerce options to the v3 shape ``[{text, status}]``. Accepts a list of
        bare strings (legacy / convenience) or a list of dicts. Each option's
        ``status`` is ``chosen`` or ``alternative``; the one matching ``chosen``
        (case-insensitive) is marked chosen when none is explicitly flagged."""
        norm: List[Dict[str, str]] = []
        for o in options or []:
            if isinstance(o, dict):
                text = str(o.get("text", "")).strip()
                status = o.get("status")
                status = status if status in ("chosen", "alternative") else None
            else:
                text = str(o).strip()
                status = None
            if not text:
                continue
            norm.append({"text": text, "status": status})

        ch = (chosen or "").strip().lower()
        saw_chosen = any(o["status"] == "chosen" for o in norm)
        for o in norm:
            if o["status"] is None:
                if ch and o["text"].lower() == ch and not saw_chosen:
                    o["status"] = "chosen"
                    saw_chosen = True
                else:
                    o["status"] = "alternative"
        # If the chosen path wasn't among the listed options, add it so the
        # decision is self-contained (you can always see what was picked).
        if ch and not saw_chosen and (chosen or "").strip():
            norm.append({"text": (chosen or "").strip(), "status": "chosen"})
        return norm

    def upsert_hypothesis(self, statement: str, status: str = "alive",
                          evidence: str = "", hid: Optional[str] = None,
                          links: Optional[List[Dict[str, Any]]] = None) -> str:
        statement = (statement or "").strip()
        if not statement:
            return ""
        status = status if status in HYP_STATUSES else "alive"
        # Match by id, else by (case-insensitive) statement.
        for h in self.state["hypotheses"]:
            if (hid and h["id"] == hid) or h["statement"].lower() == statement.lower():
                h["status"] = status
                if evidence:
                    h["evidence"] = evidence
                if links:
                    h["links"] = links
                h["updated_at"] = _now()
                self._save()
                return h["id"]
        new_id = hid or self._next_id("hypotheses", "H")
        self.state["hypotheses"].append({
            "id": new_id, "statement": statement, "status": status,
            "evidence": evidence, "links": links or [], "author": "",
            "updated_at": _now(),
        })
        self._save()
        return new_id

    def add_finding(self, text: str, kind: str = "result",
                    insight: str = "", evidence: Optional[List[Any]] = None,
                    links: Optional[List[Dict[str, Any]]] = None,
                    author: str = "") -> str:
        """Add (or dedup) a finding — the spine node decisions hang off. Returns
        the finding's ``F-id`` (existing id when it dedups by text), so the caller
        can tag decisions with ``finding=<that id>``."""
        text = (text or "").strip()
        if not text:
            return ""
        if kind not in FINDING_KINDS:
            kind = "note"
        for f in self.state["findings"]:
            if f["text"].lower() == text.lower():
                # Enrich an existing finding rather than duplicating it.
                if insight and not f.get("insight"):
                    f["insight"] = insight.strip()
                if evidence:
                    f["evidence"] = evidence
                if links:
                    f["links"] = links
                self._save()
                return f["id"]
        new_id = self._next_id("findings", "F")
        self.state["findings"].append({
            "id": new_id, "text": text, "insight": (insight or "").strip(),
            "kind": kind, "evidence": evidence or [], "links": links or [],
            "author": author, "ts": _now(),
        })
        self._save()
        return new_id

    def set_fields(self, narrative: Optional[str] = None,
                   current_best: Optional[str] = None,
                   crux: Optional[str] = None) -> None:
        if narrative is not None and narrative.strip():
            self.state["narrative"] = narrative.strip()
            self._dirty.add("narrative")
        if current_best is not None and current_best.strip():
            self.state["current_best"] = current_best.strip()
            self._dirty.add("current_best")
        if crux is not None and crux.strip():
            self.state["crux"] = crux.strip()
            self._dirty.add("crux")
        self._save()

    def set_open_questions(self, questions: List[str]) -> None:
        self.state["open_questions"] = [q.strip() for q in questions if q and q.strip()]
        self._dirty.add("open_questions")
        self._save()

    def resolve_questions(self, texts: List[str]) -> int:
        """Drop open questions that match any of `texts` (case-insensitive, either
        direction substring). Lets the manager prune answered questions precisely
        without re-listing the whole set — a common source of stale state."""
        targets = [t.strip().lower() for t in (texts or []) if t and t.strip()]
        if not targets:
            return 0
        before = len(self.state["open_questions"])
        kept = []
        for q in self.state["open_questions"]:
            ql = q.lower()
            if any(t in ql or ql in t for t in targets):
                continue
            kept.append(q)
        self.state["open_questions"] = kept
        removed = before - len(kept)
        if removed:
            self._dirty.add("open_questions")
            self._save()
        return removed

    def add_incident(self, kind: str, detail: str, author: str = "") -> None:
        """Record something that went wrong — an auto-detected tool error/unknown-
        tool call, or a self-reported struggle. This is what keeps the world model
        honest: failures leave a trace instead of being silently smoothed over. As
        shared multi-agent memory it doubles as coordination state (a peer can see
        what already failed and not blindly retry it)."""
        detail = (detail or "").strip()
        if not detail:
            return
        inc = self.state.setdefault("incidents", [])
        # Skip consecutive duplicates (a confused loop shouldn't spam the board).
        if inc and inc[-1].get("kind") == kind and inc[-1].get("detail") == detail:
            return
        inc.append({"ts": _now(), "kind": kind, "detail": detail, "author": author})
        # Bound growth — keep the most recent 50.
        if len(inc) > 50:
            self.state["incidents"] = inc[-50:]
        self._save()

    def add_decision(self, question: str, chosen: str = "", rationale: str = "",
                     options: Optional[List[Any]] = None, by: str = "manager",
                     finding: str = "global", layer: Optional[str] = None,
                     evidence: Optional[List[Any]] = None,
                     links: Optional[List[Dict[str, Any]]] = None,
                     author: str = "") -> str:
        """Record a decision (a fork the run faced). ``finding`` is the F-id it
        serves, or ``"global"`` for a project-wide fork (e.g. orchestration: which
        agent to dispatch, when to stop) tied to no single finding. ``layer`` is
        one of DECISION_LAYERS. Review/interaction fields are left empty for later
        agents. Returns the new ``D-id``."""
        question = (question or "").strip()
        if not question:
            return ""
        layer = layer if layer in DECISION_LAYERS else None
        finding = (finding or "global").strip() or "global"
        new_id = self._next_id("decisions", "D")
        self.state["decisions"].append({
            "id": new_id, "finding": finding, "layer": layer,
            "question": question,
            "options": self._normalize_options(options, chosen),
            "chosen": (chosen or "").strip(),
            "rationale": (rationale or "").strip(), "by": by, "author": author,
            "evidence": evidence or [], "links": links or [],
            # Review-time / interaction-time — filled by later agents, not live.
            "importance": "", "should_engage": None, "should_engage_reason": "",
            "sequence": None, "ts": _now(),
        })
        self._save()
        return new_id

    def reparent_decision(self, decision_id: str, finding: str) -> bool:
        """Move a decision from ``global`` (or any finding) onto ``finding`` — used
        when a decision was recorded before the finding it serves existed. Returns
        True if a decision was updated."""
        finding = (finding or "").strip()
        if not finding:
            return False
        for d in self.state["decisions"]:
            if d["id"] == decision_id:
                d["finding"] = finding
                self._save()
                return True
        return False

    def add_experiment(self, agent: str, run_id: str, rationale: str = "",
                       hypothesis: str = "", name: str = "", mode: str = "",
                       design: str = "") -> str:
        """Record an investigation. ``name``/``mode``/``design`` describe what it IS
        (domain-general); ``agent`` is the NeuriCo pipeline stage that ran it, kept
        as provenance under ``ranBy`` (``agent`` retained for back-compat)."""
        mode = mode if mode in EXPERIMENT_MODES else ""
        new_id = self._next_id("experiments", "E")
        self.state["experiments"].append({
            "id": new_id, "name": (name or "").strip(), "mode": mode,
            "design": (design or "").strip(), "agent": agent, "ranBy": agent,
            "run_id": run_id, "rationale": (rationale or "").strip(),
            "hypothesis": (hypothesis or "").strip(), "status": "running",
            "result": "", "ts": _now(),
        })
        self._save()
        return new_id

    def update_experiment(self, run_id: str, status: Optional[str] = None,
                          result: Optional[str] = None) -> None:
        changed = False
        for e in self.state["experiments"]:
            if e["run_id"] == run_id:
                if status:
                    e["status"] = status
                    # Stamp when the run reaches a terminal state so the drift
                    # check can compare against completion, not creation (`ts`).
                    if status in ("done", "failed") and not e.get("completed_at"):
                        e["completed_at"] = _now()
                    changed = True
                if result:
                    e["result"] = result.strip()
                    changed = True
                break
        if changed:
            self._save()

    # --------------------------------------------------------- panel (L2)
    def set_panel_layout(self, layout: List[str]) -> None:
        """Set the ordered list of section ids the whiteboard renders. Entries
        may be built-in ids (see BUILTIN_SECTIONS) or custom section ids. Empty
        list restores the default order."""
        self.state["panel_layout"] = [str(s).strip() for s in (layout or [])
                                      if str(s).strip()]
        self._dirty.add("panel_layout")
        self._save()

    def upsert_section(self, sid: str, title: Optional[str] = None,
                       kind: Optional[str] = None, data: Any = None) -> str:
        """Create or update a custom whiteboard section. `kind` is one of
        BLOCK_KINDS; `data` shape depends on kind (str for text; list for
        bullet_list/status_list; {columns,rows} for table; list of {key,value}
        or a dict for key_value). Only the provided fields are changed."""
        sid = (sid or "").strip()
        if not sid:
            return ""
        sec = self.state["sections"].get(sid, {})
        if title is not None:
            sec["title"] = str(title).strip()
        if kind is not None:
            sec["kind"] = kind if kind in BLOCK_KINDS else "text"
        if data is not None:
            sec["data"] = data
        sec.setdefault("kind", "text")
        sec.setdefault("title", sid)
        sec.setdefault("data", "")
        sec["updated_at"] = _now()
        self.state["sections"][sid] = sec
        self._save()
        return sid

    # ------------------------------------------------------- read / render
    def decisions_for(self, finding_id: str) -> List[Dict[str, Any]]:
        """All decisions tagged with `finding_id` (use 'global' for project-wide),
        in layer order so a reader sees a finding's forks hypothesis→interpretation."""
        order = {l: i for i, l in enumerate(DECISION_LAYERS)}
        ds = [d for d in self.state["decisions"] if d.get("finding") == finding_id]
        return sorted(ds, key=lambda d: order.get(d.get("layer"), len(order)))

    def consistency_warnings(self) -> List[str]:
        """Detect drift between the world model and reality — the failures we saw
        in real runs (a hypothesis left 'alive' after its experiment finished;
        resolved open questions never pruned). Surfaced to the manager (in the
        digest) and to the human (on the whiteboard) so the model stays honest
        rather than silently diverging."""
        warns: List[str] = []
        hyp_by_id = {h["id"]: h for h in self.state["hypotheses"]}
        for e in self.state["experiments"]:
            if e.get("status") not in ("done", "failed"):
                continue
            # Which hypothesis did this run test? Match by id or statement.
            ref = (e.get("hypothesis") or "").strip()
            h = hyp_by_id.get(ref)
            if h is None and ref:
                h = next((x for x in self.state["hypotheses"]
                          if x["statement"].lower() == ref.lower()), None)
            if h is None:
                continue
            # Drift: tested by a finished run, but status never moved off
            # alive/uncertain and the hypothesis hasn't been touched since the run.
            done_ts = e.get("completed_at") or e.get("ts", "")
            if h["status"] in ("alive", "uncertain") and \
                    h.get("updated_at", "") <= done_ts:
                warns.append(
                    f"Hypothesis {h['id']} was tested by {e['run_id']} "
                    f"({e['status']}) but is still '{h['status']}' — set it to "
                    f"supported/refuted/dead (with evidence) based on the result.")
        # Resolved-but-stale open questions: if work has clearly progressed
        # (a result/decision exists) yet questions are still listed, nudge a prune.
        if self.state["open_questions"] and (self.state["current_best"]
                                             or self.state["decisions"]):
            warns.append(
                f"{len(self.state['open_questions'])} open question(s) still "
                f"listed — prune any the work has answered via "
                f"update_research_state(resolved_questions=[...]).")
        return warns

    def snapshot(self) -> Dict[str, Any]:
        """Full state plus a couple of derived counts, for the dashboard."""
        s = self.state
        alive = sum(1 for h in s["hypotheses"] if h["status"] in ("alive", "uncertain"))
        return {
            "event": "research",
            "schema_version": s.get("schema_version", SCHEMA_VERSION),
            "updated_at": s["updated_at"],
            "narrative": s["narrative"],
            "current_best": s["current_best"],
            "crux": s["crux"],
            "hypotheses": s["hypotheses"],
            "experiments": s["experiments"][-12:],
            "findings": s["findings"][-12:],
            "open_questions": s["open_questions"],
            "decisions": s["decisions"][-12:],
            "incidents": s.get("incidents", [])[-10:],
            "warnings": self.consistency_warnings(),
            "panel_layout": s.get("panel_layout", []),
            "sections": s.get("sections", {}),
            "counts": {
                "hypotheses_alive": alive,
                "hypotheses_total": len(s["hypotheses"]),
                "findings": len(s["findings"]),
                "experiments": len(s["experiments"]),
                "decisions": len(s["decisions"]),
            },
        }

    def digest_section(self, max_items: int = 8) -> str:
        """Compact text the manager sees each turn as part of its system prompt.

        Kept bounded so it never crowds out the conversation. This is the
        manager's 'memory of the research' — it reads this instead of having to
        re-derive the state from the raw transcript every cycle.
        """
        s = self.state
        if not any([s["narrative"], s["current_best"], s["crux"], s["hypotheses"],
                    s["open_questions"], s["decisions"], s["experiments"],
                    s["findings"], s.get("sections")]):
            return ("\n\n## Current Research State\n"
                    "(empty — you have not recorded any state yet. As you learn "
                    "things, call update_research_state to populate this.)")

        lines = ["\n\n## Current Research State",
                 "(your own running model of the investigation — keep it current)"]
        if s["narrative"]:
            lines.append(f"Narrative: {s['narrative']}")
        if s["current_best"]:
            lines.append(f"Current best: {s['current_best']}")
        if s["crux"]:
            lines.append(f"Crux right now: {s['crux']}")

        if s["hypotheses"]:
            lines.append("Hypotheses:")
            for h in s["hypotheses"][-max_items:]:
                ev = f" — {h['evidence']}" if h.get("evidence") else ""
                lines.append(f"  [{h['status']}] {h['id']}: {h['statement']}{ev}")

        if s["findings"]:
            lines.append("Findings (the spine — decisions hang off these):")
            for f in s["findings"][-max_items:]:
                ins = f" — {f['insight']}" if f.get("insight") else ""
                lines.append(f"  [{f['kind']}] {f.get('id', '?')}: {f['text']}{ins}")

        if s["experiments"]:
            lines.append("Experiments:")
            for e in s["experiments"][-max_items:]:
                why = f" ({e['rationale']})" if e.get("rationale") else ""
                label = e.get("name") or e.get("agent", "")
                lines.append(f"  {e['run_id']} {label} [{e['status']}]{why}")

        if s["open_questions"]:
            lines.append("Open questions:")
            for q in s["open_questions"][:max_items]:
                lines.append(f"  - {q}")

        if s["decisions"]:
            lines.append("Decisions made (finding/layer):")
            for d in s["decisions"][-max_items:]:
                ch = f" → {d['chosen']}" if d.get("chosen") else ""
                tag = f" [{d.get('finding', 'global')}/{d.get('layer') or '-'}]"
                lines.append(f"  - {d['question']}{ch}{tag}")

        recent_incidents = self.state.get("incidents", [])[-3:]
        if recent_incidents:
            lines.append("Recent incidents (things that went wrong — own them, "
                         "don't pretend they didn't happen):")
            for inc in recent_incidents:
                lines.append(f"  ⚠ [{inc.get('kind')}] {inc.get('detail')}")

        warns = self.consistency_warnings()
        if warns:
            lines.append("⚠ CONSISTENCY — fix these before moving on:")
            for w in warns:
                lines.append(f"  - {w}")

        # Remind the manager of the panel it designed, so it keeps custom
        # sections' data current (and doesn't redesign the layout each turn).
        if s.get("sections"):
            lines.append("Custom panel sections you defined "
                         "(keep their data current via design_panel):")
            for sid, sec in s["sections"].items():
                lines.append(f"  [{sec.get('kind', 'text')}] {sid}: "
                             f"{sec.get('title', sid)}")
        if s.get("panel_layout"):
            lines.append("Panel order: " + ", ".join(s["panel_layout"]))

        return "\n".join(lines)
