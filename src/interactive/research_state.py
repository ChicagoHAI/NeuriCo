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
os.replace) to avoid torn reads. NOTE: the current ``_save`` is last-writer-wins —
safe for a single writer (the manager) but not for concurrent multi-agent writes;
concurrency-safe merging is a separate, later change, gated on sub-agents writing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
BUILTIN_SECTIONS = ("crux", "current_best", "narrative", "assessment",
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


class ResearchState:
    """Structured, persistent model of the research-in-progress (v3)."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.neurico_dir / "research_state.json"

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
            "assessments": [],      # DEPRECATED (removed with the `assess` tool in a later PR) — {ts, situation, uncertainty, crux, decision_pending, engage_user, rationale}
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
            self._save()

    # ------------------------------------------------------------------ io
    def _save(self) -> None:
        self.state["updated_at"] = _now()
        tmp = self.state_file.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.state_file)
        except OSError:
            pass

    # -------------------------------------------------------------- mutate
    def _next_id(self, key: str, prefix: str) -> str:
        # Derive from the max existing id rather than the list length: the lists
        # are append-only today (so max+1 == len+1), but length-based ids would
        # collide the moment any list gains a delete/prune path.
        nums = [int(x["id"][len(prefix):]) for x in self.state.get(key, [])
                if str(x.get("id", "")).startswith(prefix)
                and x["id"][len(prefix):].isdigit()]
        return f"{prefix}{(max(nums) + 1) if nums else 1}"

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
        if current_best is not None and current_best.strip():
            self.state["current_best"] = current_best.strip()
        if crux is not None and crux.strip():
            self.state["crux"] = crux.strip()
        self._save()

    def set_open_questions(self, questions: List[str]) -> None:
        self.state["open_questions"] = [q.strip() for q in questions if q and q.strip()]
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

    def add_assessment(self, situation: str = "", uncertainty: str = "",
                       crux: str = "", decision_pending: str = "",
                       engage_user: bool = False, rationale: str = "") -> None:
        """DEPRECATED. The manager's per-cycle metacognition log — kept working so
        the existing `assess` tool doesn't break, but slated for removal: with the
        world model now multi-agent shared memory, the engage signal moves onto
        each decision (``should_engage``), owned by a human-interactor subagent."""
        self.state["assessments"].append({
            "ts": _now(), "situation": (situation or "").strip(),
            "uncertainty": (uncertainty or "").strip(), "crux": (crux or "").strip(),
            "decision_pending": (decision_pending or "").strip(),
            "engage_user": bool(engage_user), "rationale": (rationale or "").strip(),
        })
        # The crux from the latest assessment is the live crux.
        if crux and crux.strip():
            self.state["crux"] = crux.strip()
        self._save()

    # --------------------------------------------------------- panel (L2)
    def set_panel_layout(self, layout: List[str]) -> None:
        """Set the ordered list of section ids the whiteboard renders. Entries
        may be built-in ids (see BUILTIN_SECTIONS) or custom section ids. Empty
        list restores the default order."""
        self.state["panel_layout"] = [str(s).strip() for s in (layout or [])
                                      if str(s).strip()]
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
    @property
    def latest_assessment(self) -> Optional[Dict[str, Any]]:
        return self.state["assessments"][-1] if self.state["assessments"] else None

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
            "latest_assessment": self.latest_assessment,
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

        la = self.latest_assessment
        if la:
            lines.append(
                f"Your last assessment: {la.get('situation', '')} "
                f"| uncertainty: {la.get('uncertainty', '')} "
                f"| engage_user={la.get('engage_user')}")

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
