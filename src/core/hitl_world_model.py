"""Runtime-owned projection of HITL sources into the manager world model.

The idea log, AutoResearch frontier, and cross-attempt whiteboard remain the
authoritative HITL stores.  This module maintains the small, source-linked
ResearchState view that lets the manager reason from those stores without
manually reconstructing them every turn.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_frontier import HitlFrontierStore
from core.hitl_paths import hitl_idea_log_path, hitl_state_dir
from core.hitl_util import read_jsonl_objects
from core.hitl_whiteboard import hitl_whiteboard_path
from interactive.research_state import ResearchState

_IDEA_SOURCE = "hitl_idea"
_FRONTIER_NODE_SOURCE = "hitl_frontier_node"
_WHITEBOARD_SECTION = "hitl_cross_attempt_lessons"


class HitlWorldModelSync:
    """Synchronize runtime-owned HITL facts into ``ResearchState``.

    Reconciliation is deliberately idempotent.  A finalized idea is identified
    by its source link, while frontier and whiteboard panels are overwritten
    from their current authoritative state.  This lets a later manager turn
    repair an interruption between log finalization and world-model projection.
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.hitl_dir = hitl_state_dir(self.work_dir)
        self.idea_log_path = hitl_idea_log_path(self.work_dir)
        self.whiteboard_path = hitl_whiteboard_path(self.work_dir)

    @contextmanager
    def locked_research_state(self) -> Iterator[ResearchState]:
        """Yield the current state under HITL's single workspace writer lock.

        ``ResearchState`` intentionally remains a general last-writer-wins
        primitive. HITL has both worker-command projection and manager
        synthesis writers, so it serializes only its own writes here and
        always reloads the durable state after acquiring the lock.
        """
        self.hitl_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.hitl_dir / "research_state.lock"
        with exclusive_file_lock(lock_path):
            yield ResearchState(self.work_dir)

    @contextmanager
    def synchronized_research_state(self) -> Iterator[ResearchState]:
        """Yield current ``ResearchState`` after projecting authoritative HITL data."""
        with self.locked_research_state() as research:
            self._reconcile_unlocked(research)
            yield research

    def reconcile(self, research: Optional[ResearchState] = None) -> ResearchState:
        with self.synchronized_research_state() as current:
            synchronized = current
        if research is not None:
            # Preserve the caller's object identity while ensuring its next
            # write starts from the state that was current under the lock.
            research.state = current.state
            return research
        return synchronized

    def _reconcile_unlocked(self, research: ResearchState) -> None:
        """Project authoritative stores while ``locked_research_state`` is held."""
        ideas = self._ideas()
        self._sync_idea_records(research, ideas)
        self._sync_frontier(research, ideas)
        self._sync_whiteboard(research)

    def runtime_digest(self) -> str:
        """Render bounded dynamic context that should not be copied into prose memory."""
        lines: List[str] = []
        tips = self._active_whiteboard_tips()
        if tips:
            lines.append("\n## Active Cross-Attempt Lessons")
            for tip in tips[-8:]:
                lines.append(f"- {tip['id']} [{tip['category']}]: {tip['content']}")
            lines.append(
                "These are retained hints, not ground truth. The full whiteboard "
                "remains the authoritative cross-attempt record."
            )
        return "\n".join(lines)

    def _ideas(self) -> List[Dict[str, Any]]:
        return read_jsonl_objects(
            self.idea_log_path,
            record_label="finalized HITL idea record",
        )

    def _sync_idea_records(
        self,
        research: ResearchState,
        ideas: Iterable[Dict[str, Any]],
    ) -> Dict[str, str]:
        finding_ids: Dict[str, str] = {}
        records = list(ideas)
        for record in records:
            if record.get("idea_type") != "evidence":
                continue
            idea_id = self._idea_id(record)
            if not idea_id:
                continue
            finding_id = research.add_finding(
                text=str(record.get("evidence", "")).strip(),
                kind="note",
                insight=str(record.get("context", "")).strip(),
                evidence=list(record.get("related_artifacts") or []),
                links=[self._idea_link(idea_id)],
                author="hitl_runtime",
            )
            if finding_id:
                finding_ids[idea_id] = finding_id

        for record in records:
            if record.get("idea_type") != "decision":
                continue
            idea_id = self._idea_id(record)
            if not idea_id:
                continue
            premises = self._premises(record)
            finding = next(
                (finding_ids[premise] for premise in premises if premise in finding_ids),
                "global",
            )
            research.add_decision(
                question=str(record.get("decision_needed", "")).strip(),
                chosen=self._decision_text(record),
                rationale=self._decision_rationale(record),
                options=list(record.get("options") or []),
                by=str(record.get("actor", "hitl_runtime")).strip() or "hitl_runtime",
                finding=finding,
                layer=self._decision_layer(record),
                evidence=[
                    *list(record.get("related_artifacts") or []),
                    *[{"source": _IDEA_SOURCE, "idea_id": value} for value in premises],
                ],
                links=[self._idea_link(idea_id)],
                author="hitl_runtime",
            )
        return finding_ids

    def _sync_frontier(
        self,
        research: ResearchState,
        ideas: Iterable[Dict[str, Any]],
    ) -> None:
        views = self._frontier_views(ideas)
        if views is None:
            return
        current_best, portfolio = views
        research.set_fields(current_best=json.dumps(current_best, ensure_ascii=False, indent=2))
        research.replace_experiments_by_link_source(
            _FRONTIER_NODE_SOURCE,
            [
                {
                    "name": f"Active HITL frontier node {node['node_sha']}",
                    "mode": "other",
                    "design": "",
                    "agent": "experiment_runner",
                    "ranBy": "experiment_runner",
                    "run_id": f"hitl-frontier:{node['node_sha']}",
                    "rationale": node["reason_for_acceptance"],
                    "hypothesis": "",
                    "status": "active",
                    "result": "",
                    "links": [
                        {
                            "source": _FRONTIER_NODE_SOURCE,
                            "node_sha": node["node_sha"],
                        }
                    ],
                    **node,
                }
                for node in portfolio
            ],
        )

    def _frontier_views(
        self,
        ideas: Iterable[Dict[str, Any]],
    ) -> Optional[tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        store = HitlFrontierStore(self.work_dir)
        if not store.exists():
            return None
        # A frontier that does not yet exist is normal before the first scored
        # AutoResearch root. Once it exists, however, it is authoritative
        # runtime state: hiding corruption would let the manager reason from a
        # false empty portfolio.
        state = store.state(allow_unselected=True)
        proposals = {
            self._idea_id(record): str(record.get("proposal", "")).strip()
            for record in ideas
            if record.get("idea_type") == "proposal" and self._idea_id(record)
        }
        selected_sha = state["selected_frontier_node_sha"]
        selected = (
            self._manager_node_view(
                store.node(selected_sha),
                include_plan=True,
                include_proposal_content=True,
                proposals=proposals,
            )
            if selected_sha
            else {"status": "runtime frontier selection is pending"}
        )
        portfolio = [
            self._manager_node_view(
                store.node(node_sha),
                include_plan=False,
                include_proposal_content=False,
                proposals=proposals,
            )
            for node_sha in state["active_frontier_node_shas"]
        ]
        return selected, portfolio

    def _manager_node_view(
        self,
        node: Dict[str, Any],
        *,
        include_plan: bool,
        include_proposal_content: bool,
        proposals: Dict[str, str],
    ) -> Dict[str, Any]:
        attempt_history: List[Dict[str, Any]] = []
        for attempt in node.get("attempt_history", []):
            if not isinstance(attempt, dict):
                continue
            history_entry = {
                "proposal_idea_id": attempt.get("proposal_idea_id"),
                "proposal_type": attempt.get("proposal_type"),
                "objective_score": attempt.get("objective_score"),
                "accepted": attempt.get("accepted"),
                "manager_rationale": (
                    attempt.get("reason_for_acceptance")
                    or attempt.get("reason_for_rejection")
                    or ""
                ),
            }
            if include_proposal_content:
                proposal_id = str(attempt.get("proposal_idea_id", "")).strip()
                history_entry["proposal"] = proposals.get(proposal_id, "")
            attempt_history.append(history_entry)
        view = {
            "parent_node_sha": node.get("parent_node_sha"),
            "node_sha": node.get("node_sha"),
            "objective_score": node.get("objective_score"),
            "reason_for_acceptance": node.get("reason_for_acceptance"),
            "attempt_history": attempt_history,
        }
        if include_plan:
            view["saved_plan"] = node.get("plan", "")
        return view

    def _sync_whiteboard(self, research: ResearchState) -> None:
        tips = self._active_whiteboard_tips()
        research.upsert_section(
            _WHITEBOARD_SECTION,
            title="Active Cross-Attempt Lessons",
            kind="bullet_list",
            data=[f"{tip['id']} [{tip['category']}]: {tip['content']}" for tip in tips],
        )

    def _active_whiteboard_tips(self) -> List[Dict[str, str]]:
        if not self.whiteboard_path.exists():
            return []
        try:
            payload = json.loads(self.whiteboard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("HITL whiteboard is unreadable or malformed.") from exc
        raw_tips = payload.get("tips") if isinstance(payload, dict) else None
        if not isinstance(raw_tips, list):
            raise RuntimeError("HITL whiteboard must contain a tips array.")
        return [
            {
                "id": str(tip.get("id", "")).strip(),
                "category": str(tip.get("category", "")).strip(),
                "content": str(tip.get("content", "")).strip(),
            }
            for tip in raw_tips
            if isinstance(tip, dict)
            and tip.get("status") == "active"
            and str(tip.get("id", "")).strip()
            and str(tip.get("content", "")).strip()
        ]

    @staticmethod
    def _idea_id(record: Dict[str, Any]) -> str:
        return str(record.get("idea_id", "")).strip()

    @staticmethod
    def _idea_link(idea_id: str) -> Dict[str, str]:
        return {"source": _IDEA_SOURCE, "idea_id": idea_id}

    @staticmethod
    def _premises(record: Dict[str, Any]) -> List[str]:
        values = record.get("premises")
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    @staticmethod
    def _decision_rationale(record: Dict[str, Any]) -> str:
        return (
            str(record.get("manager_feedback", "")).strip()
            or str(record.get("human_feedback", "")).strip()
            or str(record.get("context", "")).strip()
        )

    @staticmethod
    def _decision_text(record: Dict[str, Any]) -> str:
        decision = str(record.get("decision", "")).strip()
        if decision == "CUSTOM":
            return str(record.get("human_feedback", "")).strip() or decision
        for option in record.get("options") or []:
            if isinstance(option, dict) and str(option.get("option_id", "")).strip() == decision:
                return str(option.get("text", "")).strip() or decision
        return decision

    @staticmethod
    def _decision_layer(record: Dict[str, Any]) -> Optional[str]:
        category = str(record.get("idea_category", "")).strip()
        return {
            "method_choice": "method",
            "evaluation_choice": "experiment_design",
            "artifact_boundary_choice": "experiment_design",
        }.get(category)
