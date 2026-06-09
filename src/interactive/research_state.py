"""
Shared Research State — the manager's world model.

This is the load-bearing primitive for treating the manager as a research
*expert* (a PI / co-author) rather than a tool dispatcher. Instead of reasoning
only over its last tool call, the manager reads and writes a structured picture
of the whole investigation: the hypotheses in play (alive / uncertain /
supported / dead), the experiments run and their results, the current best
result, the decisive open question (the *crux*), open questions, decisions made
(with rationale), and an append-only log of the manager's own per-cycle
*assessments* (what's happening, what's uncertain, whether the human should be
pulled in — and why).

Borrowed in spirit from AutoScientists' shared state `S` (champion, experiment
log, dead-end registry, research insights), but here it serves a *human-in-the-
loop* manager: it is what makes the manager legibly omniscient, what the
dashboard renders as a shared whiteboard, and what an annotator (or the model
itself) grades to find failures in the manager's judgement.

Persisted to ``<workspace>/.neurico/research_state.json``. The web server polls
that file to render the live "Research" pane, so writes are atomic (temp file +
os.replace) to avoid torn reads.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HYP_STATUSES = ("alive", "uncertain", "supported", "dead")

# Level 2 "PI designs the panel": the manager may declare custom whiteboard
# sections per run, each rendered from a small, safe block vocabulary. Keeping
# the vocabulary fixed (the manager picks *which* blocks and supplies data, not
# raw markup) preserves the client-side escaping that makes the board XSS-safe.
BLOCK_KINDS = ("text", "bullet_list", "key_value", "table", "status_list")

# Reserved ids for the built-in sections. A panel_layout entry that matches one
# of these renders the corresponding core section; any other id is looked up in
# the custom `sections` map.
BUILTIN_SECTIONS = ("crux", "current_best", "narrative", "assessment",
                    "hypotheses", "open_questions", "decisions", "experiments")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ResearchState:
    """Structured, persistent model of the research-in-progress."""

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
        else:
            self.state = self._blank()
            self._save()

    @staticmethod
    def _blank() -> Dict[str, Any]:
        return {
            "updated_at": _now(),
            "narrative": "",        # short rolling summary of where things stand
            "current_best": "",     # champion / best result so far
            "crux": "",             # the single most decision-relevant open issue
            "hypotheses": [],       # {id, statement, status, evidence, updated_at}
            "experiments": [],      # {id, agent, run_id, rationale, hypothesis, status, result, ts}
            "findings": [],         # {text, kind, ts}   kind: result | dead_end | note
            "open_questions": [],   # [str]
            "decisions": [],        # {id, question, options, chosen, rationale, by, ts}
            "assessments": [],      # {id, ts, situation, uncertainty, crux, decision_pending, engage_user, rationale}
            "incidents": [],        # {ts, kind, detail} — auto-logged tool errors + self-reported struggle
            # Level 2 — the PI-designed panel. `panel_layout` is an ordered list
            # of section ids (built-in or custom); empty → default order. Each
            # custom section in `sections` is {title, kind, data, updated_at}.
            "panel_layout": [],     # [section_id, ...]
            "sections": {},         # {id: {title, kind, data, updated_at}}
        }

    # ------------------------------------------------------------------ io
    def reload(self) -> None:
        """Re-read state from disk *in place* (mutates self.state, keeps the same
        object). Needed in MCP mode: tools run in a separate subprocess that owns
        its own ResearchState and writes research_state.json, so the manager calls
        this each turn before building its digest — otherwise it reasons over a
        stale, never-updated copy. In-place (not a fresh object) so the
        ToolExecutor's reference to this instance stays valid. Cheap and a no-op
        in practice for backends whose tools run in-process (disk == memory)."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # torn/missing read — keep what we have
        if not isinstance(loaded, dict):
            return
        for k, v in self._blank().items():
            loaded.setdefault(k, v)
        self.state = loaded

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
        return f"{prefix}{len(self.state.get(key, [])) + 1}"

    def upsert_hypothesis(self, statement: str, status: str = "alive",
                          evidence: str = "", hid: Optional[str] = None) -> str:
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
                h["updated_at"] = _now()
                self._save()
                return h["id"]
        new_id = hid or self._next_id("hypotheses", "H")
        self.state["hypotheses"].append({
            "id": new_id, "statement": statement, "status": status,
            "evidence": evidence, "updated_at": _now(),
        })
        self._save()
        return new_id

    def add_finding(self, text: str, kind: str = "result") -> None:
        text = (text or "").strip()
        if not text:
            return
        if kind not in ("result", "dead_end", "note"):
            kind = "note"
        if any(f["text"].lower() == text.lower() for f in self.state["findings"]):
            return
        self.state["findings"].append({"text": text, "kind": kind, "ts": _now()})
        self._save()

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

    def add_incident(self, kind: str, detail: str) -> None:
        """Record something that went wrong — an auto-detected tool error/unknown-
        tool call, or a self-reported struggle. This is what keeps the world model
        honest: failures leave a trace instead of being silently smoothed over."""
        detail = (detail or "").strip()
        if not detail:
            return
        inc = self.state.setdefault("incidents", [])
        # Skip consecutive duplicates (a confused loop shouldn't spam the board).
        if inc and inc[-1].get("kind") == kind and inc[-1].get("detail") == detail:
            return
        inc.append({"ts": _now(), "kind": kind, "detail": detail})
        # Bound growth — keep the most recent 50.
        if len(inc) > 50:
            self.state["incidents"] = inc[-50:]
        self._save()

    def add_decision(self, question: str, chosen: str = "", rationale: str = "",
                     options: Optional[List[str]] = None, by: str = "manager") -> None:
        question = (question or "").strip()
        if not question:
            return
        self.state["decisions"].append({
            "id": self._next_id("decisions", "D"), "question": question,
            "options": options or [], "chosen": (chosen or "").strip(),
            "rationale": (rationale or "").strip(), "by": by, "ts": _now(),
        })
        self._save()

    def add_experiment(self, agent: str, run_id: str, rationale: str = "",
                       hypothesis: str = "") -> None:
        self.state["experiments"].append({
            "id": self._next_id("experiments", "E"), "agent": agent,
            "run_id": run_id, "rationale": (rationale or "").strip(),
            "hypothesis": (hypothesis or "").strip(), "status": "running",
            "result": "", "ts": _now(),
        })
        self._save()

    def update_experiment(self, run_id: str, status: Optional[str] = None,
                          result: Optional[str] = None) -> None:
        changed = False
        for e in self.state["experiments"]:
            if e["run_id"] == run_id:
                if status and e.get("status") != status:
                    e["status"] = status
                    changed = True
                if result and e.get("result") != result.strip():
                    e["result"] = result.strip()
                    changed = True
                break
        if changed:
            self._save()

    def add_assessment(self, situation: str = "", uncertainty: str = "",
                       crux: str = "", decision_pending: str = "",
                       engage_user: bool = False, rationale: str = "") -> None:
        self.state["assessments"].append({
            # Stable id so offline-eval annotations can key on a specific
            # assessment (decisions already carry one; ts alone could collide).
            "id": self._next_id("assessments", "A"),
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
            if h["status"] in ("alive", "uncertain") and \
                    h.get("updated_at", "") <= e.get("ts", ""):
                warns.append(
                    f"Hypothesis {h['id']} was tested by {e['run_id']} "
                    f"({e['status']}) but is still '{h['status']}' — set it to "
                    f"supported/dead (with evidence) based on the result.")
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
            "updated_at": s["updated_at"],
            "narrative": s["narrative"],
            "current_best": s["current_best"],
            "crux": s["crux"],
            "hypotheses": s["hypotheses"],
            "experiments": s["experiments"][-12:],
            "findings": s["findings"][-12:],
            "open_questions": s["open_questions"],
            "decisions": s["decisions"][-8:],
            "latest_assessment": self.latest_assessment,
            "incidents": s.get("incidents", [])[-10:],
            "warnings": self.consistency_warnings(),
            "panel_layout": s.get("panel_layout", []),
            "sections": s.get("sections", {}),
            "counts": {
                "hypotheses_alive": alive,
                "hypotheses_total": len(s["hypotheses"]),
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
                    s.get("sections")]):
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

        if s["experiments"]:
            lines.append("Experiments:")
            for e in s["experiments"][-max_items:]:
                why = f" ({e['rationale']})" if e.get("rationale") else ""
                lines.append(f"  {e['run_id']} {e['agent']} [{e['status']}]{why}")

        if s["open_questions"]:
            lines.append("Open questions:")
            for q in s["open_questions"][:max_items]:
                lines.append(f"  - {q}")

        if s["decisions"]:
            lines.append("Decisions made:")
            for d in s["decisions"][-max_items:]:
                ch = f" → {d['chosen']}" if d.get("chosen") else ""
                lines.append(f"  - {d['question']}{ch}")

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
