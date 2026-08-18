"""Durable runtime control state for one HITL workspace.

This state is intentionally separate from the interactive manager's
conversation.  It records only workflow facts that must survive a worker or
manager process restart.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_paths import hitl_runtime_state_path, hitl_state_dir
from core.hitl_util import atomic_write_json, utc_now


# Durable review identity and the only finalizer legal at each scoring boundary.
MANAGER_REVIEW_FINALIZERS = {
    "initial_scoring": "finalize_worker_request",
    "frontier_scoring": "finalize_frontier_decision",
    "scoring_failure": "finalize_worker_request",
}
UNRESOLVED_WORKER_COMMAND_STATUSES = frozenset(
    {
        "pending",
        "scoring_approval_pending",
        "scoring",
    }
)
MAX_INTERFACE_EVENTS = 500
LOGGER = logging.getLogger(__name__)


def worker_command_requires_resume(command: Any) -> bool:
    """Return whether a replacement worker must reconnect to this command."""
    if not isinstance(command, dict):
        return False
    status = str(command.get("status", "")).strip()
    if status in UNRESOLVED_WORKER_COMMAND_STATUSES:
        return True
    if status != "resolved":
        return False
    response = command.get("response")
    if not isinstance(response, dict):
        return False
    return (
        str(response.get("status", "")).strip() == "feedback"
        and not bool(response.get("final"))
        and not isinstance(response.get("scored_candidate"), dict)
        and not isinstance(response.get("scorer_result"), dict)
    )


class HitlRuntimeStateError(RuntimeError):
    """Raised when HITL runtime control state cannot make a safe transition."""


class HitlResolutionReplyStaleError(HitlRuntimeStateError):
    """A durable human reply no longer matches the active worker request."""


def _now() -> str:
    return utc_now()


class HitlRuntimeState:
    """Atomic workspace-level state for the current HITL workflow.

    A manager may converse freely at all times.  The only exclusive runtime
    resource is one blocking worker command, represented by
    ``pending_worker_command``.  AutoResearch frontier selection is stored as a
    separate next action because no worker is waiting for it.
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.hitl_dir = hitl_state_dir(self.work_dir)
        self.path = hitl_runtime_state_path(self.work_dir)
        self.lock_path = self.hitl_dir / "runtime.lock"
        self.hitl_dir.mkdir(parents=True, exist_ok=True)
        with self._locked():
            loaded = self._load_unlocked()
            self._state = loaded or self._default()
            if loaded is None:
                self._save_unlocked()

    @staticmethod
    def _default() -> Dict[str, Any]:
        return {
            "manager_provider": "",
            "worker_continuation": None,
            "pending_worker_command": None,
            "next_autoresearch_action": None,
            "rejected_whiteboard_cleanup": None,
            "frontier_decision_transition": None,
            "initial_root_publication_transition": None,
            "approved_plans": {},
            "interface_events": [],
            "interface_event_sequence": 0,
            "interface_phase_key": "",
        }

    def _append_interface_event_unlocked(self, kind: str, **values: Any) -> Dict[str, Any]:
        sequence = int(self._state.get("interface_event_sequence", 0)) + 1
        event = {
            "id": f"N{sequence}",
            "kind": str(kind),
            "created_at": _now(),
            **self._copy(values),
        }
        events = self._state.setdefault("interface_events", [])
        if not isinstance(events, list):
            events = []
        events.append(event)
        self._state["interface_events"] = events[-MAX_INTERFACE_EVENTS:]
        self._state["interface_event_sequence"] = sequence
        return event

    def _record_phase_transition_unlocked(
        self,
        *,
        stage: str,
        phase: str,
        activity: str,
    ) -> Optional[Dict[str, Any]]:
        previous_phase_key = str(self._state.get("interface_phase_key", ""))
        try:
            normalized = tuple(str(value or "").strip() for value in (stage, phase, activity))
            if not any(normalized):
                return None
            phase_key = ":".join(normalized)
            if previous_phase_key == phase_key:
                return None
            self._state["interface_phase_key"] = phase_key
            return self._append_interface_event_unlocked(
                "phase_transition",
                stage=normalized[0],
                phase=normalized[1],
                activity=normalized[2],
            )
        except Exception:
            self._state["interface_phase_key"] = previous_phase_key
            LOGGER.warning(
                "Unable to record observational HITL phase metadata.",
                exc_info=True,
            )
            return None

    def _record_worker_command_phase_unlocked(self, command: Dict[str, Any]) -> None:
        review_kind = str(command.get("manager_review_kind", ""))
        status = str(command.get("status", ""))
        if review_kind == "initial_scoring":
            stage, phase = "scoring", "initial_result_review"
        elif review_kind == "frontier_scoring":
            stage, phase = "candidate_decision", "accept_or_reject"
        elif review_kind == "scoring_failure":
            stage, phase = "scoring", "repair_review"
        elif str(command.get("kind", "")).strip() == "proposal":
            stage, phase = str(command.get("pipeline_stage", "")), "proposal"
        elif status == "scoring_approval_pending":
            stage, phase = "scoring", "preparing"
        elif status == "scoring":
            stage, phase = "scoring", "evaluating_results"
        else:
            stage = str(command.get("pipeline_stage", ""))
            phase = str(command.get("hitl_stage", ""))
        if review_kind or status == "pending":
            activity = "reviewing"
        elif status == "scoring_approval_pending":
            activity = "preparing"
        elif status == "scoring":
            activity = "evaluating"
        else:
            activity = status or "reviewing"
        self._record_phase_transition_unlocked(
            stage=stage,
            phase=phase,
            activity=activity,
        )

    def record_interface_idea(self, idea_id: str) -> Optional[Dict[str, Any]]:
        """Record a derived UI notice after an authoritative idea is appended."""
        normalized = str(idea_id).strip()
        if not normalized:
            raise HitlRuntimeStateError("Interface idea event requires idea_id")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            events = self._state.get("interface_events", [])
            if isinstance(events, list) and any(
                isinstance(event, dict)
                and event.get("kind") == "idea_created"
                and str(event.get("idea_id", "")) == normalized
                for event in events
            ):
                return None
            event = self._append_interface_event_unlocked(
                "idea_created",
                idea_id=normalized,
            )
            self._save_unlocked()
            return self._copy(event)

    def interface_events(self) -> list[Dict[str, Any]]:
        events = self.snapshot().get("interface_events", [])
        if not isinstance(events, list):
            return []
        return [self._copy(event) for event in events if isinstance(event, dict)]

    def record_interface_phase(
        self,
        *,
        stage: str,
        phase: str,
        activity: str,
    ) -> Optional[Dict[str, Any]]:
        """Record a user-facing phase transition without changing workflow state."""
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            event = self._record_phase_transition_unlocked(
                stage=stage,
                phase=phase,
                activity=activity,
            )
            self._save_unlocked()
            return self._copy(event) if event is not None else None

    def _locked(self) -> Iterator[None]:
        return exclusive_file_lock(self.lock_path)

    @staticmethod
    def _copy(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _load_unlocked(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HitlRuntimeStateError("Invalid .neurico/hitl/runtime.json") from exc
        if not isinstance(payload, dict):
            raise HitlRuntimeStateError("HITL runtime state must be a JSON object")
        merged = self._default()
        merged.update(payload)
        # Ignore the retired interface-owned run shadow in existing workspaces.
        merged.pop("run", None)
        return merged

    def _save_unlocked(self) -> None:
        self._state["updated_at"] = _now()
        atomic_write_json(self.path, self._state, ensure_ascii=False, indent=2)

    def snapshot(self) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            return self._copy(self._state)

    def manager_provider(self) -> str:
        """Return the workspace's selected manager backend, if configured."""
        provider = str(self.snapshot().get("manager_provider", "")).strip().lower()
        return provider if provider in {"claude", "codex"} else ""

    def set_manager_provider(self, provider: str) -> str:
        """Persist the backend selected for this workspace's manager."""
        provider = str(provider or "").strip().lower()
        if provider not in {"claude", "codex"}:
            raise ValueError("Choose Claude or Codex for the HITL manager.")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            self._state["manager_provider"] = provider
            self._save_unlocked()
        return provider

    def worker_continuation(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("worker_continuation")
        return value if isinstance(value, dict) and value else None

    def record_worker_continuation(self, continuation: Dict[str, Any]) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            value = self._copy(continuation)
            value["replacement_count"] = 0
            value["status"] = "running"
            value["started_at"] = _now()
            self._state["worker_continuation"] = value
            self._record_phase_transition_unlocked(
                stage=str(value.get("pipeline_stage", "")),
                phase=str(value.get("hitl_stage", "")),
                activity="working",
            )
            self._save_unlocked()

    def update_worker_continuation(self, **updates: Any) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            continuation = self._state.get("worker_continuation")
            if not isinstance(continuation, dict):
                return
            continuation.update(self._copy(updates))
            continuation["updated_at"] = _now()
            status = str(continuation.get("status", ""))
            self._record_phase_transition_unlocked(
                stage=str(continuation.get("pipeline_stage", "")),
                phase=str(continuation.get("hitl_stage", "")),
                activity="revising" if status.startswith("replacement") else "working",
            )
            self._save_unlocked()

    def mark_worker_replacement(self) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            continuation = self._state.get("worker_continuation")
            if not isinstance(continuation, dict):
                return
            continuation["replacement_count"] = int(continuation.get("replacement_count", 0)) + 1
            continuation["status"] = "replacement_running"
            continuation["updated_at"] = _now()
            self._record_phase_transition_unlocked(
                stage=str(continuation.get("pipeline_stage", "")),
                phase=str(continuation.get("hitl_stage", "")),
                activity="revising",
            )
            self._save_unlocked()

    def clear_worker_continuation(self) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            self._state["worker_continuation"] = None
            self._save_unlocked()

    def mark_plan_approved(
        self,
        *,
        pipeline_stage: str,
        plan_fingerprint: str,
        approval_level: str = "A",
    ) -> None:
        if not pipeline_stage or not plan_fingerprint:
            raise HitlRuntimeStateError(
                "Plan approval requires pipeline stage and plan fingerprint"
            )
        if approval_level not in {"A", "B"}:
            raise HitlRuntimeStateError("Plan approval level must be A or B")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            approvals = self._state.setdefault("approved_plans", {})
            approvals[str(pipeline_stage)] = {
                "plan_fingerprint": str(plan_fingerprint),
                "approval_level": approval_level,
                "approved_at": _now(),
            }
            self._save_unlocked()

    def has_plan_approval(
        self,
        *,
        pipeline_stage: str,
        plan_fingerprint: str,
        approval_levels: tuple[str, ...] = ("A",),
    ) -> bool:
        approvals = self.snapshot().get("approved_plans", {})
        record = approvals.get(str(pipeline_stage)) if isinstance(approvals, dict) else None
        if not isinstance(record, dict):
            return False
        level = str(record.get("approval_level") or "A")
        return (
            record.get("plan_fingerprint") == str(plan_fingerprint)
            and level in approval_levels
        )

    def adopt_hitl_mode(self, hitl_mode: str) -> Dict[str, Any]:
        """Apply one run's policy to restartable, unresolved HITL state.

        Resolved commands and audit records are historical facts and are never
        rewritten. Switching to Auto closes any outstanding human-resolution
        pointer while preserving the request key and worker continuation.
        """

        from core.hitl_mode import HitlMode, normalize_hitl_mode

        selected = normalize_hitl_mode(hitl_mode)
        result: Dict[str, Any] = {
            "hitl_mode": selected.value,
            "discard_resolution_reply_for": "",
        }
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            continuation = self._state.get("worker_continuation")
            if isinstance(continuation, dict):
                continuation["hitl_mode"] = selected.value
                continuation["updated_at"] = _now()

            command = self._state.get("pending_worker_command")
            if isinstance(command, dict) and command.get("status") in {
                "pending",
                "scoring_approval_pending",
                "scoring",
            }:
                command["hitl_mode"] = selected.value
                if command.get("kind") == "phase_finish":
                    # Human plan approval is derived from the policy of the
                    # run that resumes this unresolved command.  Keeping the
                    # prior run's value would make the validator and manager
                    # tool surface disagree after an Auto -> Full switch.
                    command["requires_human_approval"] = bool(
                        selected is HitlMode.FULL and command.get("hitl_stage") == "plan"
                    )
                command["updated_at"] = _now()
                if selected is HitlMode.AUTO:
                    request_key = str(command.get("request_key", "")).strip()
                    # Return this on every adoption so a restart can complete
                    # inbox cleanup after a crash between the two durable files.
                    result["discard_resolution_reply_for"] = request_key
                    command["human_request_record_id"] = None
                    command["human_reply_record_ids"] = []
            self._save_unlocked()
        return result

    def pending_worker_command(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("pending_worker_command")
        return value if isinstance(value, dict) and value else None

    def begin_worker_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Persist one worker command or return its matching retry record."""
        request_key = str(command.get("request_key", "")).strip()
        if not request_key:
            raise HitlRuntimeStateError("Pending HITL worker command requires request_key")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("pending_worker_command")
            if isinstance(existing, dict) and existing:
                if existing.get("request_key") == request_key:
                    return self._copy(existing)
                if existing.get("status") == "resolved":
                    # Keep a resolved command long enough for an idempotent retry
                    # of that exact command. A distinct command marks the next
                    # worker interaction, so it can safely replace the old result.
                    self._state["pending_worker_command"] = None
                else:
                    raise HitlRuntimeStateError(
                        "Another blocking HITL worker command is already unresolved."
                    )
            record = self._copy(command)
            record.setdefault("status", "pending")
            record.setdefault("human_request_record_id", None)
            record.setdefault("human_reply_record_ids", [])
            record["created_at"] = _now()
            self._state["pending_worker_command"] = record
            self._record_worker_command_phase_unlocked(record)
            self._save_unlocked()
            return self._copy(record)

    def update_pending_worker_command(self, request_key: str, **updates: Any) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            next_status = updates.get("status")
            if (
                command.get("status") == "cancelled"
                and next_status is not None
                and next_status != "cancelled"
            ):
                raise HitlRuntimeStateError(
                    "A cancelled HITL worker command cannot return to an active state."
                )
            command.update(self._copy(updates))
            command["updated_at"] = _now()
            self._record_worker_command_phase_unlocked(command)
            self._save_unlocked()
            return self._copy(command)

    def complete_worker_command(self, request_key: str, response: Dict[str, Any]) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            if command.get("status") == "cancelled":
                raise HitlRuntimeStateError(
                    "A cancelled HITL worker command cannot be completed."
                )
            command["status"] = "resolved"
            command["response"] = self._copy(response)
            command["resolved_at"] = _now()
            self._state["pending_worker_command"] = command
            events = self._state.get("interface_events", [])
            already_recorded = isinstance(events, list) and any(
                isinstance(event, dict)
                and event.get("kind") == "request_resolved"
                and str(event.get("request_key", "")) == str(request_key)
                for event in events
            )
            if not already_recorded:
                try:
                    self._append_interface_event_unlocked(
                        "request_resolved",
                        request_key=str(request_key),
                        stage=str(command.get("pipeline_stage", "")),
                        phase=str(command.get("hitl_stage", "")),
                        outcome=str(response.get("status", "")).strip(),
                        human_involved=bool(command.get("human_reply_record_ids")),
                    )
                except Exception:
                    LOGGER.warning(
                        "Unable to record observational HITL request metadata.",
                        exc_info=True,
                    )
            self._save_unlocked()

    def cancel_pending_worker_command(
        self,
        request_key: str,
        *,
        reason: str,
        cancellation_kind: str = "attempt_rollback",
    ) -> Dict[str, Any]:
        """Release a held command before restoring its attempt boundary.

        This is only for runtime rollback. A cancelled command is never a worker
        response and must not be finalized by a stale manager turn.
        """
        message = str(reason).strip()
        if not message:
            raise HitlRuntimeStateError("Cancelled HITL worker command requires a reason")
        kind = str(cancellation_kind).strip()
        if not kind:
            raise HitlRuntimeStateError("Cancelled HITL worker command requires a cancellation kind")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            if command.get("status") in {"resolved", "cancelled"}:
                return self._copy(command)
            command["status"] = "cancelled"
            command["cancellation_reason"] = message
            command["cancellation_kind"] = kind
            command["cancelled_at"] = _now()
            command["human_request_record_id"] = None
            self._state["pending_worker_command"] = command
            self._save_unlocked()
            return self._copy(command)

    def begin_scoring_handoff(
        self,
        request_key: str,
        *,
        context: str,
        review: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist scoring intent before recording or starting scoring.

        A process can stop between the manager's approval and the durable audit
        write. This intermediate state gives recovery enough information to
        finish that write idempotently before it resumes scoring.
        """
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            if command.get("status") not in {"pending", "scoring_approval_pending"}:
                raise HitlRuntimeStateError(
                    "HITL worker command is not available for scoring approval"
                )
            command["status"] = "scoring_approval_pending"
            command["scoring_context"] = str(context)
            command["scoring_review"] = self._copy(review)
            command["updated_at"] = _now()
            self._state["pending_worker_command"] = command
            self._record_phase_transition_unlocked(
                stage="scoring",
                phase="preparing",
                activity="preparing",
            )
            self._save_unlocked()
            return self._copy(command)

    def complete_scoring_handoff(self, request_key: str, *, scoring_review_idea_id: str) -> None:
        """Mark the scoring handoff restartable after its audit record exists."""
        if not str(scoring_review_idea_id).strip():
            raise HitlRuntimeStateError("Scoring handoff requires its manager idea id")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            if command.get("status") not in {"scoring_approval_pending", "scoring"}:
                raise HitlRuntimeStateError(
                    "HITL worker command has no scoring handoff to complete"
                )
            command["status"] = "scoring"
            command["scoring_review_idea_id"] = str(scoring_review_idea_id)
            command.pop("scoring_review", None)
            command["updated_at"] = _now()
            self._state["pending_worker_command"] = command
            self._record_phase_transition_unlocked(
                stage="scoring",
                phase="evaluating_results",
                activity="evaluating",
            )
            self._save_unlocked()

    def clear_completed_worker_command(self, request_key: str) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if isinstance(command, dict) and command.get("request_key") == request_key:
                self._state["pending_worker_command"] = None
                self._save_unlocked()

    def request_human_reply(self, request_key: str, *, record_id: str) -> Dict[str, Any]:
        record_id = str(record_id).strip()
        if not record_id:
            raise HitlRuntimeStateError("Human resolution question requires a transcript record")
        return self.update_pending_worker_command(
            request_key,
            human_request_record_id=record_id,
        )

    def record_human_reply(self, request_key: str, record_id: str) -> Dict[str, Any]:
        request_key = str(request_key).strip()
        record_id = str(record_id).strip()
        if not request_key:
            raise HitlRuntimeStateError("Human resolution reply requires request_key")
        if not record_id:
            raise HitlRuntimeStateError("Human resolution reply requires a transcript record")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlResolutionReplyStaleError(
                    "The human reply no longer matches the active HITL worker request."
                )
            if not str(command.get("human_request_record_id", "")).strip():
                raise HitlResolutionReplyStaleError(
                    "The matching HITL worker request no longer has an open human question."
                )
            command.setdefault("human_reply_record_ids", []).append(record_id)
            command["human_request_record_id"] = None
            command["updated_at"] = _now()
            self._save_unlocked()
            return self._copy(command)

    def begin_next_autoresearch_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(action.get("kind", "")).strip()
        if not kind:
            raise HitlRuntimeStateError("AutoResearch next action requires kind")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("next_autoresearch_action")
            if isinstance(existing, dict) and existing:
                if existing.get("kind") == kind:
                    if existing.get("status") == "cancelled":
                        existing["status"] = "pending"
                        existing.pop("cancellation_reason", None)
                        existing["restarted_at"] = _now()
                        self._state["next_autoresearch_action"] = existing
                        self._save_unlocked()
                    return self._copy(existing)
                raise HitlRuntimeStateError("Another AutoResearch action is already pending")
            record = self._copy(action)
            record["status"] = "pending"
            record["created_at"] = _now()
            self._state["next_autoresearch_action"] = record
            self._record_phase_transition_unlocked(
                stage="frontier",
                phase="pruning" if kind == "prune_frontier" else "selecting_next",
                activity="reviewing",
            )
            self._save_unlocked()
            return self._copy(record)

    def record_next_autoresearch_action_decision(
        self,
        kind: str,
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist a manager's frontier choice before applying it.

        A prune or selection changes more than one store.  Retaining the
        command arguments in runtime state first makes the remaining log and
        frontier updates restartable without asking the manager to decide a
        second time.
        """
        normalized_kind = str(kind).strip()
        if not normalized_kind:
            raise HitlRuntimeStateError("AutoResearch action decision requires kind")
        if not isinstance(decision, dict):
            raise HitlRuntimeStateError("AutoResearch action decision must be an object")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if not isinstance(action, dict) or action.get("kind") != normalized_kind:
                raise HitlRuntimeStateError("No matching pending AutoResearch action")
            existing = action.get("decision")
            if action.get("status") == "decision_recorded":
                if existing == self._copy(decision):
                    return self._copy(action)
                raise HitlRuntimeStateError(
                    "Runtime already recorded a different manager choice for this AutoResearch action"
                )
            if action.get("status") != "pending":
                raise HitlRuntimeStateError("AutoResearch action is not available for a manager choice")
            action["decision"] = self._copy(decision)
            action["status"] = "decision_recorded"
            action["decision_recorded_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._record_phase_transition_unlocked(
                stage="frontier",
                phase=(
                    "saving_prune_decision"
                    if normalized_kind == "prune_frontier"
                    else "saving_selection"
                ),
                activity="saving",
            )
            self._save_unlocked()
            return self._copy(action)

    def complete_next_autoresearch_action(self, kind: str, result: Dict[str, Any]) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if not isinstance(action, dict) or action.get("kind") != kind:
                raise HitlRuntimeStateError("No matching pending AutoResearch action")
            if action.get("status") != "decision_recorded":
                raise HitlRuntimeStateError(
                    "AutoResearch action cannot complete before runtime records the manager choice"
                )
            action["status"] = "resolved"
            action["result"] = self._copy(result)
            action["resolved_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()

    def clear_completed_next_autoresearch_action(self, kind: str) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if (
                isinstance(action, dict)
                and action.get("kind") == kind
                and action.get("status") == "resolved"
            ):
                self._state["next_autoresearch_action"] = None
                self._save_unlocked()

    def cancel_next_autoresearch_action(self, kind: str, *, reason: str) -> Dict[str, Any]:
        message = str(reason).strip()
        if not message:
            raise HitlRuntimeStateError("Cancelled AutoResearch action requires a reason")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if not isinstance(action, dict) or action.get("kind") != kind:
                raise HitlRuntimeStateError("No matching pending AutoResearch action")
            if action.get("status") == "resolved":
                return self._copy(action)
            action["status"] = "cancelled"
            action["cancellation_reason"] = message
            action["cancelled_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(action)

    def begin_rejected_whiteboard_cleanup(self, attempt_id: str) -> Dict[str, Any]:
        """Persist the one remaining cleanup step for a rejected candidate.

        A rejected candidate is valid completed research: its whiteboard adds
        remain useful, while clear/prune mutations made for the rejected
        workspace must be reverted.  This state makes that narrow cleanup
        restartable without treating the whole attempt as failed.
        """
        normalized = str(attempt_id).strip()
        if not normalized:
            raise HitlRuntimeStateError("Rejected whiteboard cleanup requires attempt_id")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("rejected_whiteboard_cleanup")
            if isinstance(existing, dict) and existing:
                if existing.get("attempt_id") == normalized:
                    return self._copy(existing)
                raise HitlRuntimeStateError(
                    "Another rejected whiteboard cleanup is already pending"
                )
            record = {
                "attempt_id": normalized,
                "status": "pending",
                "created_at": _now(),
            }
            self._state["rejected_whiteboard_cleanup"] = record
            self._record_phase_transition_unlocked(
                stage="candidate_decision",
                phase="applying_result",
                activity="saving",
            )
            self._save_unlocked()
            return self._copy(record)

    def pending_rejected_whiteboard_cleanup(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("rejected_whiteboard_cleanup")
        return value if isinstance(value, dict) and value else None

    def begin_frontier_decision_transition(
        self,
        transition: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist one scored-candidate commit before touching its stores.

        The idea log, hidden frontier, public mirror, and worker response are
        separate durable stores.  This record is their small write-ahead log:
        each following step is idempotent and recovery resumes it in order.
        """
        attempt_id = str(transition.get("attempt_id", "")).strip()
        candidate_sha = str(transition.get("candidate_node_sha", "")).strip()
        if not attempt_id or not candidate_sha:
            raise HitlRuntimeStateError(
                "Frontier decision transition requires attempt_id and candidate_node_sha"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("frontier_decision_transition")
            if isinstance(existing, dict) and existing:
                if (
                    existing.get("attempt_id") == attempt_id
                    and existing.get("candidate_node_sha") == candidate_sha
                ):
                    return self._copy(existing)
                if existing.get("status") not in {"completed", "mirrored"}:
                    raise HitlRuntimeStateError(
                        "Another HITL frontier decision transition is still incomplete"
                    )
            record = self._copy(transition)
            record["status"] = "prepared"
            record["created_at"] = _now()
            self._state["frontier_decision_transition"] = record
            self._record_phase_transition_unlocked(
                stage="candidate_decision",
                phase="saving_result",
                activity="saving",
            )
            self._save_unlocked()
            return self._copy(record)

    def frontier_decision_transition(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("frontier_decision_transition")
        return value if isinstance(value, dict) and value else None

    def begin_initial_root_publication_transition(
        self,
        transition: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist initial-root publication before its first public checkpoint."""
        required_text = (
            "plan_text",
            "reason_for_acceptance",
            "history_root",
        )
        if any(not str(transition.get(key, "")).strip() for key in required_text):
            raise HitlRuntimeStateError(
                "Initial-root publication requires plan, acceptance reason, and history root"
            )
        if not isinstance(transition.get("objective_score"), dict):
            raise HitlRuntimeStateError(
                "Initial-root publication requires the complete objective score"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("initial_root_publication_transition")
            if isinstance(existing, dict) and existing:
                return self._copy(existing)
            record = self._copy(transition)
            record["status"] = "prepared"
            record["created_at"] = _now()
            self._state["initial_root_publication_transition"] = record
            self._record_phase_transition_unlocked(
                stage="frontier",
                phase="creating_root",
                activity="saving",
            )
            self._save_unlocked()
            return self._copy(record)

    def initial_root_publication_transition(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("initial_root_publication_transition")
        return value if isinstance(value, dict) and value else None

    def advance_initial_root_publication_transition(
        self,
        *,
        status: str,
        **updates: Any,
    ) -> Dict[str, Any]:
        valid_statuses = {
            "prepared",
            "checkpoint_created",
            "root_initialized",
            "run_configured",
            "mirrored",
            "completed",
        }
        if status not in valid_statuses:
            raise HitlRuntimeStateError(
                f"Invalid initial-root publication status: {status}"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            current = self._state.get("initial_root_publication_transition")
            if not isinstance(current, dict) or not current:
                raise HitlRuntimeStateError(
                    "No initial-root publication transition is pending"
                )
            current.update(self._copy(updates))
            current["status"] = status
            current["updated_at"] = _now()
            self._state["initial_root_publication_transition"] = current
            self._save_unlocked()
            return self._copy(current)

    def advance_frontier_decision_transition(
        self,
        *,
        attempt_id: str,
        candidate_node_sha: str,
        status: str,
        **updates: Any,
    ) -> Dict[str, Any]:
        if status not in {"prepared", "idea_logged", "frontier_finalized", "mirrored", "completed"}:
            raise HitlRuntimeStateError(f"Invalid frontier decision transition status: {status}")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            current = self._state.get("frontier_decision_transition")
            if (
                not isinstance(current, dict)
                or current.get("attempt_id") != str(attempt_id).strip()
                or current.get("candidate_node_sha") != str(candidate_node_sha).strip()
            ):
                raise HitlRuntimeStateError("No matching HITL frontier decision transition")
            current.update(self._copy(updates))
            current["status"] = status
            current["updated_at"] = _now()
            self._state["frontier_decision_transition"] = current
            self._save_unlocked()
            return self._copy(current)

    def complete_rejected_whiteboard_cleanup(self, attempt_id: str) -> None:
        normalized = str(attempt_id).strip()
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("rejected_whiteboard_cleanup")
            if not isinstance(existing, dict) or existing.get("attempt_id") != normalized:
                raise HitlRuntimeStateError("No matching rejected whiteboard cleanup exists")
            self._state["rejected_whiteboard_cleanup"] = None
            self._save_unlocked()
