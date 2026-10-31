"""Durable runtime control state for one HITL workspace.

This state is intentionally separate from the interactive manager's
conversation.  It records only workflow facts that must survive a worker or
manager process restart.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_paths import hitl_runtime_state_path, hitl_state_dir
from core.hitl_proposal_discussion import (
    PROPOSAL_DISCUSSION_SCHEMA_VERSION,
    normalize_proposal_discussion_record,
    parse_reopen_discussion_record_id,
    proposal_discussion_task_id,
    reopen_discussion_record_id,
    validate_proposal_discussion_task_id,
)
from core.hitl_proposal_round import PROPOSAL_ROUND_SCHEMA_VERSION
from core.hitl_util import atomic_write_json, utc_now


# Durable review identity and the only finalizer legal at each scoring boundary.
MANAGER_REVIEW_FINALIZERS = {
    "initial_scoring": "finalize_worker_request",
    "baseline_construction_scoring": "finalize_baseline_construction",
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
_LOCAL_ATTEMPT_ID = re.compile(r"^attempt_[0-9]+$")
_IDEA_ID = re.compile(r"^I[0-9]+$")
_PROPOSAL_ROUND_STAGES = {
    "proposing",
    "verifying",
    "reviewing",
    "manager_selection",
    "selected",
}
_PROPOSAL_ROLE_STAGES = {
    "proposer": frozenset({"proposing"}),
    "verifier": frozenset({"proposing", "verifying"}),
    "reviewer": frozenset({"reviewing"}),
}
_PROPOSAL_DISCUSSION_PHASES = frozenset(
    {"initial", "opening", "response", "decision", "final_writing", "reopen_pending"}
)
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


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
    ``pending_worker_command``. Runtime-controlled AutoResearch boundaries are
    stored as a separate next action because no worker is waiting for them.
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
            "workspace_guard_scope": {
                "runtime_private_roots": [],
                "immutable_resource_roots": [],
                "immutable_resource_digests": {},
            },
            "next_autoresearch_action": None,
            "rejected_whiteboard_cleanup": None,
            "frontier_decision_transition": None,
            "bootstrap_prepublication_boundary": None,
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
        elif review_kind == "baseline_construction_scoring":
            stage, phase = "scoring", "baseline_result_review"
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
            value["consecutive_provider_failures"] = 0
            value["status"] = "running"
            value["started_at"] = _now()
            self._state["worker_continuation"] = value
            self._record_phase_transition_unlocked(
                stage=str(value.get("pipeline_stage", "")),
                phase=str(value.get("hitl_stage", "")),
                activity="working",
            )
            self._save_unlocked()

    def record_worker_provider_result(self, *, failed: bool) -> int:
        """Record one provider-process result for the active continuation."""
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            continuation = self._state.get("worker_continuation")
            if not isinstance(continuation, dict):
                return 0
            failures = int(continuation.get("consecutive_provider_failures", 0))
            failures = failures + 1 if failed else 0
            continuation["consecutive_provider_failures"] = failures
            continuation["updated_at"] = _now()
            self._save_unlocked()
            return failures

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

    def workspace_guard_scope(self) -> Dict[str, Any]:
        """Return the normalized runtime-owned public-fingerprint scope."""
        from core.hitl_workspace_guard import WorkspaceGuardScope

        value = self.snapshot().get("workspace_guard_scope")
        return WorkspaceGuardScope.from_value(value).to_dict()

    def set_workspace_guard_scope(
        self,
        *,
        runtime_private_roots: Any = (),
        immutable_resource_roots: Any = (),
    ) -> Dict[str, Any]:
        """Register exact, existing roots before a worker boundary begins."""
        from core.hitl_workspace_guard import HitlWorkspaceWriteGuard, WorkspaceGuardScope

        requested = WorkspaceGuardScope.from_value(
            {
                "runtime_private_roots": runtime_private_roots,
                "immutable_resource_roots": immutable_resource_roots,
            }
        )
        for relative in requested.excluded_roots:
            path = self.work_dir / relative
            if not path.exists() and not path.is_symlink():
                raise HitlRuntimeStateError(
                    f"HITL workspace guard roots must exist before registration: {relative}"
                )
            if (
                relative in requested.runtime_private_roots
                and not path.is_dir()
                and not path.is_symlink()
            ):
                raise HitlRuntimeStateError(
                    f"HITL runtime-private roots must be directories or symlinks: {relative}"
                )
        try:
            current_digests = {
                relative: HitlWorkspaceWriteGuard.immutable_resource_digest(
                    self.work_dir,
                    relative,
                )
                for relative in requested.immutable_resource_roots
            }
        except (OSError, RuntimeError, ValueError) as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = WorkspaceGuardScope.from_value(self._state.get("workspace_guard_scope"))
            removed = sorted(
                set(existing.immutable_resource_roots) - set(requested.immutable_resource_roots)
            )
            if removed:
                raise HitlRuntimeStateError(
                    "HITL immutable resource roots cannot be unregistered: " + ", ".join(removed)
                )

            existing_digests = dict(existing.immutable_resource_digests)
            trusted_digests: Dict[str, str] = {}
            for relative in requested.immutable_resource_roots:
                if relative in existing.immutable_resource_roots:
                    expected = existing_digests.get(relative)
                    if not expected:
                        raise HitlRuntimeStateError(
                            "HITL immutable resource has no trusted registration digest: "
                            + relative
                        )
                else:
                    expected = current_digests[relative]
                current = current_digests[relative]
                if current != expected:
                    raise HitlRuntimeStateError(
                        "HITL immutable resource changed after registration: " + relative
                    )
                trusted_digests[relative] = expected

            scope = WorkspaceGuardScope.from_value(
                {
                    "runtime_private_roots": requested.runtime_private_roots,
                    "immutable_resource_roots": requested.immutable_resource_roots,
                    "immutable_resource_digests": trusted_digests,
                }
            ).require_immutable_resource_digests()
            self._state["workspace_guard_scope"] = scope.to_dict()
            self._save_unlocked()
        return scope.to_dict()

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

    @staticmethod
    def _proposal_round_identity(
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
    ) -> tuple[str, str, str, int]:
        parent = str(parent_node_sha).strip()
        preparation = str(preparation_attempt_id).strip()
        candidate = str(candidate_attempt_id).strip()
        if not parent or not preparation:
            raise HitlRuntimeStateError("Proposal round requires parent and preparation identity")
        if _LOCAL_ATTEMPT_ID.fullmatch(candidate) is None:
            raise HitlRuntimeStateError(
                "Proposal round candidate_attempt_id must be the local attempt_N component"
            )
        if isinstance(round_ordinal, bool) or not isinstance(round_ordinal, int):
            raise HitlRuntimeStateError("Proposal round ordinal must be a positive integer")
        if round_ordinal < 1:
            raise HitlRuntimeStateError("Proposal round ordinal must be a positive integer")
        return parent, preparation, candidate, round_ordinal

    def _proposal_preparation_unlocked(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
    ) -> Dict[str, Any]:
        action = self._state.get("next_autoresearch_action")
        decision = action.get("decision") if isinstance(action, dict) else None
        result = action.get("result") if isinstance(action, dict) else None
        if (
            not isinstance(action, dict)
            or action.get("kind") != "prepare_proposal"
            or action.get("status") != "resolved"
            or str(action.get("parent_node_sha", "")).strip() != parent_node_sha
            or str(action.get("attempt_id", "")).strip() != preparation_attempt_id
            or not isinstance(decision, dict)
            or decision.get("choice") != "proceed"
            or not isinstance(result, dict)
            or result.get("choice") != "proceed"
        ):
            raise HitlRuntimeStateError(
                "No matching resolved proposal preparation owns this proposal round"
            )
        return action

    @staticmethod
    def _validate_proposal_round_shape(round_state: Any) -> Dict[str, Any]:
        if not isinstance(round_state, dict):
            raise HitlRuntimeStateError("Proposal round state is missing")
        if round_state.get("version") != PROPOSAL_ROUND_SCHEMA_VERSION:
            raise HitlRuntimeStateError("Unsupported proposal round schema version")
        if str(round_state.get("stage", "")) not in _PROPOSAL_ROUND_STAGES:
            raise HitlRuntimeStateError("Proposal round has an invalid stage")
        if not isinstance(round_state.get("tasks"), dict):
            raise HitlRuntimeStateError("Proposal round tasks must be an object")
        if isinstance(round_state.get("base_idea_number"), bool) or not isinstance(
            round_state.get("base_idea_number"), int
        ):
            raise HitlRuntimeStateError("Proposal round has an invalid idea boundary")
        if int(round_state["base_idea_number"]) < 0:
            raise HitlRuntimeStateError("Proposal round has an invalid idea boundary")
        from core.hitl_proposal_round import normalize_proposal_mode_config

        try:
            normalize_proposal_mode_config(
                "independent_ranked",
                proposer_count=round_state.get("proposer_count"),
                reviewer_count=round_state.get("reviewer_count"),
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        selection = round_state.get("selection")
        if selection is not None and not isinstance(selection, dict):
            raise HitlRuntimeStateError("Proposal round selection must be null or an object")
        return round_state

    def _proposal_round_unlocked(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        expected_stage: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        parent, preparation, candidate, ordinal = self._proposal_round_identity(
            parent_node_sha=parent_node_sha,
            preparation_attempt_id=preparation_attempt_id,
            candidate_attempt_id=candidate_attempt_id,
            round_ordinal=round_ordinal,
        )
        action = self._proposal_preparation_unlocked(
            parent_node_sha=parent,
            preparation_attempt_id=preparation,
        )
        if action.get("proposal_discussion") is not None:
            raise HitlRuntimeStateError(
                "Proposal preparation cannot own ranked and collaborative state together"
            )
        round_state = self._validate_proposal_round_shape(action.get("proposal_round"))
        if (
            str(round_state.get("candidate_attempt_id", "")).strip() != candidate
            or round_state.get("round_ordinal") != ordinal
        ):
            raise HitlRuntimeStateError("Proposal round identity is stale")
        if expected_stage is not None:
            if expected_stage not in _PROPOSAL_ROUND_STAGES:
                raise HitlRuntimeStateError("Expected proposal round stage is invalid")
            if round_state.get("stage") != expected_stage:
                raise HitlRuntimeStateError("Proposal round stage is stale")
        return action, round_state

    @staticmethod
    def _new_proposal_round(
        *,
        candidate_attempt_id: str,
        round_ordinal: int,
        base_idea_number: int,
        proposer_count: int,
        reviewer_count: int,
    ) -> Dict[str, Any]:
        from core.hitl_proposal_round import proposal_task_id

        return {
            "version": PROPOSAL_ROUND_SCHEMA_VERSION,
            "candidate_attempt_id": candidate_attempt_id,
            "round_ordinal": round_ordinal,
            "stage": "proposing",
            "base_idea_number": base_idea_number,
            "proposer_count": proposer_count,
            "reviewer_count": reviewer_count,
            "tasks": {
                proposal_task_id(round_ordinal, "proposer", ordinal): {
                    "role": "proposer",
                    "result_idea_id": None,
                }
                for ordinal in range(1, proposer_count + 1)
            },
            "selection": None,
        }

    @staticmethod
    def _proposal_task_unlocked(
        round_state: Dict[str, Any],
        *,
        proposal_task_id: str,
        role: str,
    ) -> Dict[str, Any]:
        from core.hitl_proposal_round import parse_proposal_task_id

        allowed_stages = _PROPOSAL_ROLE_STAGES.get(role)
        if allowed_stages is None:
            raise HitlRuntimeStateError("Proposal task role is invalid")
        try:
            identity = parse_proposal_task_id(proposal_task_id)
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        if (
            identity.round_ordinal != round_state.get("round_ordinal")
            or identity.role != role
            or round_state.get("stage") not in allowed_stages
        ):
            raise HitlRuntimeStateError("Proposal task identity or stage is stale")
        task = round_state["tasks"].get(proposal_task_id)
        if not isinstance(task, dict) or task.get("role") != role:
            raise HitlRuntimeStateError("No matching proposal task exists")
        return task

    def begin_proposal_round(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        workspace_fingerprint: str,
        base_idea_number: int,
        proposer_count: int,
        reviewer_count: int,
    ) -> Dict[str, Any]:
        """Create round one beneath one resolved proposal preparation."""

        parent, preparation, candidate, _ordinal = self._proposal_round_identity(
            parent_node_sha=parent_node_sha,
            preparation_attempt_id=preparation_attempt_id,
            candidate_attempt_id=candidate_attempt_id,
            round_ordinal=1,
        )
        if isinstance(base_idea_number, bool) or not isinstance(base_idea_number, int):
            raise HitlRuntimeStateError("Proposal round idea boundary must be non-negative")
        if base_idea_number < 0:
            raise HitlRuntimeStateError("Proposal round idea boundary must be non-negative")
        live_fingerprint = str(workspace_fingerprint).strip()
        if not live_fingerprint:
            raise HitlRuntimeStateError("Proposal round requires a workspace fingerprint")
        from core.hitl_proposal_round import normalize_proposal_mode_config

        try:
            config = normalize_proposal_mode_config(
                "independent_ranked",
                proposer_count=proposer_count,
                reviewer_count=reviewer_count,
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._proposal_preparation_unlocked(
                parent_node_sha=parent,
                preparation_attempt_id=preparation,
            )
            if action.get("proposal_discussion") is not None:
                raise HitlRuntimeStateError(
                    "Proposal preparation cannot own ranked and collaborative state together"
                )
            existing = action.get("proposal_round")
            if existing is not None:
                round_state = self._validate_proposal_round_shape(existing)
                if (
                    str(action.get("workspace_fingerprint", "")).strip()
                    == live_fingerprint
                    and round_state.get("candidate_attempt_id") == candidate
                    and round_state.get("round_ordinal") == 1
                    and round_state.get("base_idea_number") == base_idea_number
                    and round_state.get("proposer_count") == config.proposer_count
                    and round_state.get("reviewer_count") == config.reviewer_count
                ):
                    return self._copy(round_state)
                raise HitlRuntimeStateError(
                    "Proposal preparation already owns a different proposal round"
                )
            round_state = self._new_proposal_round(
                candidate_attempt_id=candidate,
                round_ordinal=1,
                base_idea_number=base_idea_number,
                proposer_count=int(config.proposer_count),
                reviewer_count=int(config.reviewer_count),
            )
            action["workspace_fingerprint"] = live_fingerprint
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(round_state)

    def proposal_round_snapshot(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
    ) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            _action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
            )
            return self._copy(round_state)

    def ensure_proposal_verifier_task(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        proposer_task_id: str,
    ) -> Dict[str, Any]:
        """Create the verifier paired with one completed proposer, idempotently."""

        from core.hitl_proposal_round import parse_proposal_task_id, proposal_task_id

        try:
            proposer_identity = parse_proposal_task_id(proposer_task_id)
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        if (
            proposer_identity.round_ordinal != round_ordinal
            or proposer_identity.role != "proposer"
        ):
            raise HitlRuntimeStateError("Verifier task requires a current-round proposer")
        verifier_task_id = proposal_task_id(
            round_ordinal,
            "verifier",
            proposer_identity.ordinal,
        )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
                expected_stage="proposing",
            )
            proposer = self._proposal_task_unlocked(
                round_state,
                proposal_task_id=proposer_task_id,
                role="proposer",
            )
            proposal_idea_id = str(proposer.get("result_idea_id") or "").strip()
            if (
                _IDEA_ID.fullmatch(proposal_idea_id) is None
                or proposer.get("pending_finalization") is not None
            ):
                raise HitlRuntimeStateError(
                    "Verifier task requires a completed proposal task"
                )
            expected = {
                "role": "verifier",
                "assigned_proposal_idea_id": proposal_idea_id,
                "result_idea_id": None,
            }
            existing = round_state["tasks"].get(verifier_task_id)
            if existing is None:
                round_state["tasks"][verifier_task_id] = expected
                result = expected
            else:
                if (
                    not isinstance(existing, dict)
                    or existing.get("role") != "verifier"
                    or existing.get("assigned_proposal_idea_id") != proposal_idea_id
                ):
                    raise HitlRuntimeStateError(
                        "Existing verifier task conflicts with its completed proposer"
                    )
                result = existing
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(result)

    def record_proposal_task_provider_result(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        proposal_task_id: str,
        role: str,
        failed: bool,
    ) -> int:
        if not isinstance(failed, bool):
            raise HitlRuntimeStateError("Proposal task provider result requires failed=true/false")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
            )
            task = self._proposal_task_unlocked(
                round_state,
                proposal_task_id=proposal_task_id,
                role=role,
            )
            if (
                task.get("result_idea_id") is not None
                or task.get("pending_finalization") is not None
            ):
                raise HitlRuntimeStateError(
                    "Provider result applies only to an incomplete proposal task"
                )
            if failed:
                prior = task.get("consecutive_provider_failures", 0)
                if isinstance(prior, bool) or not isinstance(prior, int) or prior < 0:
                    raise HitlRuntimeStateError("Proposal task provider-failure counter is invalid")
                count = prior + 1
                task["consecutive_provider_failures"] = count
            else:
                count = 0
                task.pop("consecutive_provider_failures", None)
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return count

    def begin_proposal_task_finalization(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        proposal_task_id: str,
        role: str,
        normalized_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(normalized_output, dict) or not normalized_output:
            raise HitlRuntimeStateError(
                "Proposal task finalization requires validated normalized output"
            )
        intent = self._copy(normalized_output)
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
            )
            task = self._proposal_task_unlocked(
                round_state,
                proposal_task_id=proposal_task_id,
                role=role,
            )
            if task.get("result_idea_id") is not None:
                raise HitlRuntimeStateError("Proposal task is already complete")
            existing = task.get("pending_finalization")
            if existing is not None:
                if existing == intent:
                    return self._copy(existing)
                raise HitlRuntimeStateError(
                    "Proposal task already owns a different finalization intent"
                )
            task["pending_finalization"] = intent
            task.pop("consecutive_provider_failures", None)
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(intent)

    def complete_proposal_task_finalization(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        proposal_task_id: str,
        role: str,
        normalized_output: Dict[str, Any],
        result_idea_id: str,
    ) -> Dict[str, Any]:
        idea_id = str(result_idea_id).strip()
        if _IDEA_ID.fullmatch(idea_id) is None:
            raise HitlRuntimeStateError("Proposal task result requires a finalized idea ID")
        intent = self._copy(normalized_output)
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
            )
            task = self._proposal_task_unlocked(
                round_state,
                proposal_task_id=proposal_task_id,
                role=role,
            )
            if task.get("result_idea_id") is not None:
                raise HitlRuntimeStateError("Proposal task is already complete")
            if task.get("pending_finalization") != intent:
                raise HitlRuntimeStateError("Proposal task has no matching finalization intent")
            task["result_idea_id"] = idea_id
            task.pop("pending_finalization", None)
            task.pop("consecutive_provider_failures", None)
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(task)

    def advance_proposal_round(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        expected_stage: str,
    ) -> Dict[str, Any]:
        if expected_stage not in {"proposing", "verifying", "reviewing"}:
            raise HitlRuntimeStateError("Proposal round cannot advance from this stage")
        from core.hitl_proposal_round import proposal_task_id

        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
                expected_stage=expected_stage,
            )
            tasks = round_state["tasks"]
            proposer_ids = [
                proposal_task_id(round_ordinal, "proposer", ordinal)
                for ordinal in range(1, int(round_state["proposer_count"]) + 1)
            ]
            verifier_ids = [
                proposal_task_id(round_ordinal, "verifier", ordinal)
                for ordinal in range(1, int(round_state["proposer_count"]) + 1)
            ]
            reviewer_ids = [
                proposal_task_id(round_ordinal, "reviewer", ordinal)
                for ordinal in range(1, int(round_state["reviewer_count"]) + 1)
            ]
            if expected_stage == "proposing":
                if not set(proposer_ids).issubset(tasks) or not set(tasks).issubset(
                    {*proposer_ids, *verifier_ids}
                ):
                    raise HitlRuntimeStateError(
                        "Proposal round task set does not match its current stage"
                    )
            else:
                expected_ids = {
                    "verifying": [*proposer_ids, *verifier_ids],
                    "reviewing": [*proposer_ids, *verifier_ids, *reviewer_ids],
                }[expected_stage]
                if set(tasks) != set(expected_ids):
                    raise HitlRuntimeStateError(
                        "Proposal round task set does not match its current stage"
                    )
            active_ids = {
                "proposing": proposer_ids,
                "verifying": verifier_ids,
                "reviewing": reviewer_ids,
            }[expected_stage]
            for task_id in active_ids:
                task = tasks.get(task_id)
                if (
                    not isinstance(task, dict)
                    or task.get("role")
                    != {
                        "proposing": "proposer",
                        "verifying": "verifier",
                        "reviewing": "reviewer",
                    }[expected_stage]
                    or _IDEA_ID.fullmatch(str(task.get("result_idea_id", ""))) is None
                    or task.get("pending_finalization") is not None
                ):
                    raise HitlRuntimeStateError(
                        "Proposal round cannot advance before every task is complete"
                    )
            if expected_stage == "proposing":
                for ordinal, task_id in enumerate(verifier_ids, start=1):
                    expected = {
                        "role": "verifier",
                        "assigned_proposal_idea_id": tasks[proposer_ids[ordinal - 1]][
                            "result_idea_id"
                        ],
                        "result_idea_id": None,
                    }
                    existing = tasks.get(task_id)
                    if existing is None:
                        tasks[task_id] = expected
                    elif (
                        not isinstance(existing, dict)
                        or existing.get("role") != "verifier"
                        or existing.get("assigned_proposal_idea_id")
                        != expected["assigned_proposal_idea_id"]
                    ):
                        raise HitlRuntimeStateError(
                            "Existing verifier task conflicts with its completed proposer"
                        )
                round_state["tasks"] = {
                    task_id: tasks[task_id]
                    for task_id in [*proposer_ids, *verifier_ids]
                }
                round_state["stage"] = "verifying"
            elif expected_stage == "verifying":
                for task_id in reviewer_ids:
                    tasks[task_id] = {
                        "role": "reviewer",
                        "result_idea_id": None,
                    }
                round_state["stage"] = "reviewing"
            else:
                round_state["stage"] = "manager_selection"
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(round_state)

    def record_proposal_selection_choice(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        choice: str,
        reason: str,
        proposal_idea_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_choice = str(choice).strip()
        normalized_reason = str(reason).strip()
        candidate_id = str(proposal_idea_id or "").strip()
        if normalized_choice not in {"select", "new_round"} or not normalized_reason:
            raise HitlRuntimeStateError(
                "Proposal selection requires select/new_round and a nonempty reason"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
                expected_stage="manager_selection",
            )
            if normalized_choice == "select":
                proposer_results = {
                    str(task.get("result_idea_id", ""))
                    for task in round_state["tasks"].values()
                    if isinstance(task, dict) and task.get("role") == "proposer"
                }
                if candidate_id not in proposer_results:
                    raise HitlRuntimeStateError(
                        "Selected proposal is not a current-round candidate"
                    )
                selection = {
                    "choice": "select",
                    "proposal_idea_id": candidate_id,
                    "reason": normalized_reason,
                    "decision_idea_id": None,
                }
            else:
                if candidate_id:
                    raise HitlRuntimeStateError("A new-round choice must not select a proposal")
                selection = {
                    "choice": "new_round",
                    "reason": normalized_reason,
                    "decision_idea_id": None,
                }
            existing = round_state.get("selection")
            if existing is not None:
                comparable_existing = (
                    {key: value for key, value in existing.items() if key != "decision_idea_id"}
                    if isinstance(existing, dict)
                    else existing
                )
                comparable_selection = {
                    key: value for key, value in selection.items() if key != "decision_idea_id"
                }
                if comparable_existing == comparable_selection:
                    return self._copy(existing)
                raise HitlRuntimeStateError(
                    "Proposal round already records a different manager choice"
                )
            round_state["selection"] = selection
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(selection)

    def record_proposal_selection_decision(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        choice: str,
        decision_idea_id: str,
        proposal_idea_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        decision_id = str(decision_idea_id).strip()
        if _IDEA_ID.fullmatch(decision_id) is None:
            raise HitlRuntimeStateError("Proposal selection requires a decision idea ID")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
                expected_stage="manager_selection",
            )
            selection = round_state.get("selection")
            candidate_id = str(proposal_idea_id or "").strip()
            if (
                not isinstance(selection, dict)
                or selection.get("choice") != str(choice).strip()
                or (
                    selection.get("choice") == "select"
                    and selection.get("proposal_idea_id") != candidate_id
                )
                or (selection.get("choice") == "new_round" and candidate_id)
            ):
                raise HitlRuntimeStateError(
                    "Proposal decision does not match the recorded manager choice"
                )
            existing = selection.get("decision_idea_id")
            if existing is not None:
                if existing == decision_id:
                    return self._copy(selection)
                raise HitlRuntimeStateError(
                    "Proposal selection already references a different decision idea"
                )
            selection["decision_idea_id"] = decision_id
            round_state["selection"] = selection
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(selection)

    def complete_proposal_selection(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
    ) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
                expected_stage="manager_selection",
            )
            selection = round_state.get("selection")
            if (
                not isinstance(selection, dict)
                or selection.get("choice") != "select"
                or _IDEA_ID.fullmatch(str(selection.get("proposal_idea_id", ""))) is None
                or _IDEA_ID.fullmatch(str(selection.get("decision_idea_id", ""))) is None
            ):
                raise HitlRuntimeStateError(
                    "Proposal selection is not durably ready for completion"
                )
            round_state["stage"] = "selected"
            action["proposal_round"] = round_state
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(round_state)

    def begin_next_proposal_round(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        base_idea_number: int,
        non_admitted_proposal_idea_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if isinstance(base_idea_number, bool) or not isinstance(base_idea_number, int):
            raise HitlRuntimeStateError("Proposal round idea boundary must be non-negative")
        if base_idea_number < 0:
            raise HitlRuntimeStateError("Proposal round idea boundary must be non-negative")
        non_admitted_id = str(non_admitted_proposal_idea_id or "").strip()
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, round_state = self._proposal_round_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal,
            )
            selection = round_state.get("selection")
            durable_new_round = bool(
                round_state.get("stage") == "manager_selection"
                and not non_admitted_id
                and isinstance(selection, dict)
                and selection.get("choice") == "new_round"
                and _IDEA_ID.fullmatch(str(selection.get("decision_idea_id", "")))
            )
            durable_non_admission = bool(
                round_state.get("stage") == "selected"
                and non_admitted_id
                and isinstance(selection, dict)
                and selection.get("choice") == "select"
                and selection.get("proposal_idea_id") == non_admitted_id
                and _IDEA_ID.fullmatch(str(selection.get("decision_idea_id", "")))
            )
            if not durable_new_round and not durable_non_admission:
                raise HitlRuntimeStateError(
                    "Proposal round cannot restart before a durable new-round decision or non-admission"
                )
            next_round = self._new_proposal_round(
                candidate_attempt_id=candidate_attempt_id,
                round_ordinal=round_ordinal + 1,
                base_idea_number=base_idea_number,
                proposer_count=int(round_state["proposer_count"]),
                reviewer_count=int(round_state["reviewer_count"]),
            )
            action["proposal_round"] = next_round
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(next_round)

    @staticmethod
    def _proposal_discussion_identity(
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
    ) -> tuple[str, str, str]:
        parent = str(parent_node_sha).strip()
        preparation = str(preparation_attempt_id).strip()
        candidate = str(candidate_attempt_id).strip()
        if not parent or not preparation:
            raise HitlRuntimeStateError(
                "Proposal discussion requires parent and preparation identity"
            )
        if _LOCAL_ATTEMPT_ID.fullmatch(candidate) is None:
            raise HitlRuntimeStateError(
                "Proposal discussion candidate_attempt_id must be the local attempt_N component"
            )
        return parent, preparation, candidate

    @staticmethod
    def _normalized_whiteboard_boundary_sha(value: Any) -> str:
        normalized = str(value).strip()
        if _FULL_GIT_SHA.fullmatch(normalized) is None:
            raise HitlRuntimeStateError(
                "Proposal discussion whiteboard boundary must be a full lowercase commit SHA"
            )
        return normalized

    @staticmethod
    def _proposal_discussion_response_ids(
        round_ordinal: int,
        participant_count: int,
    ) -> list[str]:
        return [
            proposal_discussion_task_id(
                "response",
                participant_ordinal=ordinal,
                round_ordinal=round_ordinal,
            )
            for ordinal in range(2, participant_count + 1)
        ]

    @staticmethod
    def _new_proposal_discussion(
        *,
        candidate_attempt_id: str,
        base_idea_number: int,
        whiteboard_boundary_sha: str,
        participant_count: int,
        max_response_rounds: int,
    ) -> Dict[str, Any]:
        return {
            "version": PROPOSAL_DISCUSSION_SCHEMA_VERSION,
            "candidate_attempt_id": candidate_attempt_id,
            "phase": "initial",
            "base_idea_number": base_idea_number,
            "whiteboard_boundary_sha": whiteboard_boundary_sha,
            "participant_count": participant_count,
            "max_response_rounds": max_response_rounds,
            "round_ordinal": 0,
            "tasks": {
                proposal_discussion_task_id(
                    "initial",
                    participant_ordinal=ordinal,
                ): {
                    "kind": "contribution",
                    "result_record_id": None,
                }
                for ordinal in range(1, participant_count + 1)
            },
        }

    @staticmethod
    def _proposal_discussion_expected_task_ids(
        session: Dict[str, Any],
    ) -> list[str]:
        participant_count = int(session["participant_count"])
        round_ordinal = int(session["round_ordinal"])
        phase = str(session["phase"])
        task_ids = [
            proposal_discussion_task_id(
                "initial",
                participant_ordinal=ordinal,
            )
            for ordinal in range(1, participant_count + 1)
        ]
        if phase == "initial":
            return task_ids
        task_ids.append(proposal_discussion_task_id("opening", participant_ordinal=1))
        if phase == "opening":
            return task_ids
        for ordinal in range(1, round_ordinal + 1):
            task_ids.extend(
                HitlRuntimeState._proposal_discussion_response_ids(
                    ordinal,
                    participant_count,
                )
            )
            if ordinal < round_ordinal:
                task_ids.append(
                    proposal_discussion_task_id(
                        "decision",
                        participant_ordinal=1,
                        round_ordinal=ordinal,
                    )
                )
        if phase == "decision" or (
            phase in {"final_writing", "reopen_pending"}
            and round_ordinal < int(session["max_response_rounds"])
        ):
            task_ids.append(
                proposal_discussion_task_id(
                    "decision",
                    participant_ordinal=1,
                    round_ordinal=round_ordinal,
                )
            )
        return task_ids

    @staticmethod
    def _proposal_discussion_task_complete(task: Any) -> bool:
        if not isinstance(task, dict):
            return False
        record_id = task.get("result_record_id")
        return bool(
            isinstance(record_id, str)
            and record_id.strip()
            and task.get("pending_finalization") is None
        )

    @staticmethod
    def _validate_proposal_discussion_task_shape(
        task_id: str,
        task: Any,
        *,
        participant_count: int,
        max_response_rounds: int,
    ) -> Dict[str, Any]:
        if not isinstance(task, dict):
            raise HitlRuntimeStateError("Proposal discussion task must be an object")
        try:
            identity = validate_proposal_discussion_task_id(
                task_id,
                participant_count=participant_count,
                max_response_rounds=max_response_rounds,
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        expected_kind = "decision" if identity.phase == "decision" else "contribution"
        allowed_keys = {
            "kind",
            "result_record_id",
            "pending_finalization",
            "consecutive_provider_failures",
            "choice",
        }
        if set(task) - allowed_keys:
            raise HitlRuntimeStateError("Proposal discussion task contains unsupported fields")
        if task.get("kind") != expected_kind or "result_record_id" not in task:
            raise HitlRuntimeStateError("Proposal discussion task kind is invalid")
        result_record_id = task.get("result_record_id")
        if result_record_id is not None and result_record_id != task_id:
            raise HitlRuntimeStateError(
                "Proposal discussion task result reference does not match its task ID"
            )
        pending = task.get("pending_finalization")
        if "pending_finalization" in task and pending is None:
            raise HitlRuntimeStateError(
                "Proposal discussion task must omit an empty finalization intent"
            )
        if pending is not None:
            if result_record_id is not None:
                raise HitlRuntimeStateError(
                    "Completed proposal discussion task cannot retain finalization intent"
                )
            try:
                normalized = normalize_proposal_discussion_record(
                    task_id,
                    expected_kind,
                    pending,
                )["result"]
            except ValueError as exc:
                raise HitlRuntimeStateError(str(exc)) from exc
            if pending != normalized:
                raise HitlRuntimeStateError(
                    "Proposal discussion task finalization intent is not normalized"
                )
        failures = task.get("consecutive_provider_failures")
        if "consecutive_provider_failures" in task and failures is None:
            raise HitlRuntimeStateError(
                "Proposal discussion task must omit an empty provider-failure counter"
            )
        if failures is not None:
            if (
                isinstance(failures, bool)
                or not isinstance(failures, int)
                or failures < 1
                or result_record_id is not None
                or pending is not None
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion provider-failure counter is invalid"
                )
        choice = task.get("choice")
        if "choice" in task and choice is None:
            raise HitlRuntimeStateError(
                "Proposal discussion task must omit an empty scheduling choice"
            )
        if expected_kind == "decision" and result_record_id is not None:
            if choice not in {"continue", "finalize"}:
                raise HitlRuntimeStateError(
                    "Completed proposal discussion decision requires its scheduling choice"
                )
        elif choice is not None:
            raise HitlRuntimeStateError(
                "Only a completed proposal discussion decision retains a choice"
            )
        if result_record_id is not None and (
            "pending_finalization" in task or "consecutive_provider_failures" in task
        ):
            raise HitlRuntimeStateError(
                "Completed proposal discussion task contains transient state"
            )
        return task

    @staticmethod
    def _validate_proposal_discussion_shape(session: Any) -> Dict[str, Any]:
        if not isinstance(session, dict):
            raise HitlRuntimeStateError("Proposal discussion state is missing")
        required_keys = {
            "version",
            "candidate_attempt_id",
            "phase",
            "base_idea_number",
            "whiteboard_boundary_sha",
            "participant_count",
            "max_response_rounds",
            "round_ordinal",
            "tasks",
        }
        phase = str(session.get("phase", ""))
        expected_keys = required_keys | ({"reopen_handoff"} if phase == "reopen_pending" else set())
        if set(session) != expected_keys:
            raise HitlRuntimeStateError(
                "Proposal discussion state contains missing or unsupported fields"
            )
        if session.get("version") != PROPOSAL_DISCUSSION_SCHEMA_VERSION:
            raise HitlRuntimeStateError("Unsupported proposal discussion schema version")
        if _LOCAL_ATTEMPT_ID.fullmatch(
            str(session.get("candidate_attempt_id", ""))
        ) is None:
            raise HitlRuntimeStateError("Proposal discussion candidate attempt is invalid")
        if phase not in _PROPOSAL_DISCUSSION_PHASES:
            raise HitlRuntimeStateError("Proposal discussion phase is invalid")
        base_idea_number = session.get("base_idea_number")
        if (
            isinstance(base_idea_number, bool)
            or not isinstance(base_idea_number, int)
            or base_idea_number < 0
        ):
            raise HitlRuntimeStateError("Proposal discussion idea boundary is invalid")
        HitlRuntimeState._normalized_whiteboard_boundary_sha(
            session.get("whiteboard_boundary_sha")
        )
        from core.hitl_proposal_round import normalize_proposal_mode_config

        try:
            config = normalize_proposal_mode_config(
                "collaborative",
                participant_count=session.get("participant_count"),
                discussion_rounds=session.get("max_response_rounds"),
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        participant_count = int(config.participant_count)
        max_response_rounds = int(config.discussion_rounds)
        round_ordinal = session.get("round_ordinal")
        if isinstance(round_ordinal, bool) or not isinstance(round_ordinal, int):
            raise HitlRuntimeStateError("Proposal discussion round ordinal is invalid")
        if phase in {"initial", "opening"}:
            if round_ordinal != 0:
                raise HitlRuntimeStateError(
                    "Proposal discussion has a round before member responses begin"
                )
        elif round_ordinal < 1 or round_ordinal > max_response_rounds:
            raise HitlRuntimeStateError("Proposal discussion round ordinal is invalid")
        tasks = session.get("tasks")
        if not isinstance(tasks, dict):
            raise HitlRuntimeStateError("Proposal discussion tasks must be an object")
        expected_task_ids = HitlRuntimeState._proposal_discussion_expected_task_ids(session)
        if set(tasks) != set(expected_task_ids):
            raise HitlRuntimeStateError(
                "Proposal discussion task set does not match its phase"
            )
        for task_id in expected_task_ids:
            HitlRuntimeState._validate_proposal_discussion_task_shape(
                task_id,
                tasks[task_id],
                participant_count=participant_count,
                max_response_rounds=max_response_rounds,
            )
        initial_ids = [
            proposal_discussion_task_id("initial", participant_ordinal=ordinal)
            for ordinal in range(1, participant_count + 1)
        ]
        if phase != "initial" and not all(
            HitlRuntimeState._proposal_discussion_task_complete(tasks[task_id])
            for task_id in initial_ids
        ):
            raise HitlRuntimeStateError(
                "Proposal discussion advanced before initial contributions completed"
            )
        if phase not in {"initial", "opening"}:
            opening_id = proposal_discussion_task_id("opening", participant_ordinal=1)
            if not HitlRuntimeState._proposal_discussion_task_complete(tasks[opening_id]):
                raise HitlRuntimeStateError(
                    "Proposal discussion advanced before the lead opening completed"
                )
        if round_ordinal:
            for ordinal in range(1, round_ordinal):
                prior_ids = HitlRuntimeState._proposal_discussion_response_ids(
                    ordinal,
                    participant_count,
                )
                prior_ids.append(
                    proposal_discussion_task_id(
                        "decision",
                        participant_ordinal=1,
                        round_ordinal=ordinal,
                    )
                )
                if not all(
                    HitlRuntimeState._proposal_discussion_task_complete(tasks[task_id])
                    for task_id in prior_ids
                ):
                    raise HitlRuntimeStateError(
                        "Proposal discussion has an incomplete earlier response round"
                    )
            current_response_ids = HitlRuntimeState._proposal_discussion_response_ids(
                round_ordinal,
                participant_count,
            )
            if phase != "response" and not all(
                HitlRuntimeState._proposal_discussion_task_complete(tasks[task_id])
                for task_id in current_response_ids
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion advanced before member responses completed"
                )
            if phase in {"final_writing", "reopen_pending"} and round_ordinal < max_response_rounds:
                decision_id = proposal_discussion_task_id(
                    "decision",
                    participant_ordinal=1,
                    round_ordinal=round_ordinal,
                )
                decision = tasks[decision_id]
                if (
                    not HitlRuntimeState._proposal_discussion_task_complete(decision)
                    or decision.get("choice") != "finalize"
                ):
                    raise HitlRuntimeStateError(
                        "Proposal discussion final writing requires a finalized lead decision"
                    )
        handoff = session.get("reopen_handoff")
        if phase == "reopen_pending":
            if round_ordinal >= max_response_rounds or not isinstance(handoff, dict):
                raise HitlRuntimeStateError("Proposal discussion reopen handoff is invalid")
            expected_handoff_keys = {
                "worker_request_key",
                "proposal_idea_id",
                "feedback_ref",
                "reopen_record_id",
            }
            if set(handoff) != expected_handoff_keys:
                raise HitlRuntimeStateError("Proposal discussion reopen handoff is invalid")
            if not str(handoff.get("worker_request_key", "")).strip():
                raise HitlRuntimeStateError("Proposal discussion reopen request key is invalid")
            if _IDEA_ID.fullmatch(str(handoff.get("proposal_idea_id", ""))) is None:
                raise HitlRuntimeStateError("Proposal discussion reopen proposal ID is invalid")
            if not str(handoff.get("feedback_ref", "")).strip():
                raise HitlRuntimeStateError("Proposal discussion feedback reference is invalid")
            if handoff.get("reopen_record_id") != reopen_discussion_record_id(
                round_ordinal + 1
            ):
                raise HitlRuntimeStateError("Proposal discussion reopen record is invalid")
        return session

    def _proposal_discussion_unlocked(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        expected_phase: Optional[str] = None,
        expected_round_ordinal: Optional[int] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        parent, preparation, candidate = self._proposal_discussion_identity(
            parent_node_sha=parent_node_sha,
            preparation_attempt_id=preparation_attempt_id,
            candidate_attempt_id=candidate_attempt_id,
        )
        action = self._proposal_preparation_unlocked(
            parent_node_sha=parent,
            preparation_attempt_id=preparation,
        )
        if action.get("proposal_round") is not None:
            raise HitlRuntimeStateError(
                "Proposal preparation cannot own ranked and collaborative state together"
            )
        if not str(action.get("workspace_fingerprint", "")).strip():
            raise HitlRuntimeStateError(
                "Proposal discussion preparation has no workspace fingerprint"
            )
        session = self._validate_proposal_discussion_shape(
            action.get("proposal_discussion")
        )
        if session.get("candidate_attempt_id") != candidate:
            raise HitlRuntimeStateError("Proposal discussion identity is stale")
        if expected_phase is not None and session.get("phase") != expected_phase:
            raise HitlRuntimeStateError("Proposal discussion phase is stale")
        if (
            expected_round_ordinal is not None
            and session.get("round_ordinal") != expected_round_ordinal
        ):
            raise HitlRuntimeStateError("Proposal discussion round is stale")
        return action, session

    @staticmethod
    def _active_proposal_discussion_task_unlocked(
        session: Dict[str, Any],
        *,
        discussion_task_id: str,
    ) -> Dict[str, Any]:
        try:
            identity = validate_proposal_discussion_task_id(
                discussion_task_id,
                participant_count=int(session["participant_count"]),
                max_response_rounds=int(session["max_response_rounds"]),
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        phase = str(session["phase"])
        if identity.phase != phase:
            raise HitlRuntimeStateError("Proposal discussion task is not active")
        task = session["tasks"].get(discussion_task_id)
        if not isinstance(task, dict):
            raise HitlRuntimeStateError("No matching proposal discussion task exists")
        if phase == "response":
            active_id = next(
                (
                    task_id
                    for task_id in HitlRuntimeState._proposal_discussion_response_ids(
                        int(session["round_ordinal"]),
                        int(session["participant_count"]),
                    )
                    if not HitlRuntimeState._proposal_discussion_task_complete(
                        session["tasks"][task_id]
                    )
                ),
                None,
            )
            if active_id != discussion_task_id:
                raise HitlRuntimeStateError("Proposal discussion response task is not next")
        if HitlRuntimeState._proposal_discussion_task_complete(task):
            raise HitlRuntimeStateError("Proposal discussion task is already complete")
        return task

    def begin_proposal_discussion(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        workspace_fingerprint: str,
        base_idea_number: int,
        whiteboard_boundary_sha: str,
        participant_count: int,
        max_response_rounds: int,
    ) -> Dict[str, Any]:
        """Create one collaborative session beneath a resolved proposal preparation."""

        parent, preparation, candidate = self._proposal_discussion_identity(
            parent_node_sha=parent_node_sha,
            preparation_attempt_id=preparation_attempt_id,
            candidate_attempt_id=candidate_attempt_id,
        )
        if (
            isinstance(base_idea_number, bool)
            or not isinstance(base_idea_number, int)
            or base_idea_number < 0
        ):
            raise HitlRuntimeStateError(
                "Proposal discussion idea boundary must be non-negative"
            )
        live_fingerprint = str(workspace_fingerprint).strip()
        if not live_fingerprint:
            raise HitlRuntimeStateError(
                "Proposal discussion requires a workspace fingerprint"
            )
        whiteboard_sha = self._normalized_whiteboard_boundary_sha(
            whiteboard_boundary_sha
        )
        from core.hitl_proposal_round import normalize_proposal_mode_config

        try:
            config = normalize_proposal_mode_config(
                "collaborative",
                participant_count=participant_count,
                discussion_rounds=max_response_rounds,
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._proposal_preparation_unlocked(
                parent_node_sha=parent,
                preparation_attempt_id=preparation,
            )
            if action.get("proposal_round") is not None:
                raise HitlRuntimeStateError(
                    "Proposal preparation cannot own ranked and collaborative state together"
                )
            existing = action.get("proposal_discussion")
            if existing is not None:
                session = self._validate_proposal_discussion_shape(existing)
                if (
                    str(action.get("workspace_fingerprint", "")).strip()
                    == live_fingerprint
                    and session.get("candidate_attempt_id") == candidate
                    and session.get("base_idea_number") == base_idea_number
                    and (
                        session.get("phase") != "initial"
                        or session.get("whiteboard_boundary_sha") == whiteboard_sha
                    )
                    and session.get("participant_count") == config.participant_count
                    and session.get("max_response_rounds") == config.discussion_rounds
                ):
                    return self._copy(session)
                raise HitlRuntimeStateError(
                    "Proposal preparation already owns a different proposal discussion"
                )
            session = self._new_proposal_discussion(
                candidate_attempt_id=candidate,
                base_idea_number=base_idea_number,
                whiteboard_boundary_sha=whiteboard_sha,
                participant_count=int(config.participant_count),
                max_response_rounds=int(config.discussion_rounds),
            )
            action["workspace_fingerprint"] = live_fingerprint
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(session)

    def proposal_discussion_snapshot(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
    ) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            _action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            return self._copy(session)

    def proposal_discussion_task_snapshot(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        discussion_task_id: str,
    ) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            _action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            try:
                validate_proposal_discussion_task_id(
                    discussion_task_id,
                    participant_count=int(session["participant_count"]),
                    max_response_rounds=int(session["max_response_rounds"]),
                )
            except ValueError as exc:
                raise HitlRuntimeStateError(str(exc)) from exc
            task = session["tasks"].get(discussion_task_id)
            if not isinstance(task, dict):
                raise HitlRuntimeStateError("No matching proposal discussion task exists")
            return self._copy(task)

    def active_proposal_discussion_task_snapshot(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        discussion_task_id: str,
    ) -> Dict[str, Any]:
        """Return one task and session only while that task is authorized to act."""

        with self._locked():
            self._state = self._load_unlocked() or self._default()
            _action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            task = self._active_proposal_discussion_task_unlocked(
                session,
                discussion_task_id=discussion_task_id,
            )
            return {
                "session": self._copy(session),
                "task": self._copy(task),
            }

    def record_proposal_discussion_task_provider_result(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        discussion_task_id: str,
        failed: bool,
    ) -> int:
        if not isinstance(failed, bool):
            raise HitlRuntimeStateError(
                "Proposal discussion provider result requires failed=true/false"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            task = self._active_proposal_discussion_task_unlocked(
                session,
                discussion_task_id=discussion_task_id,
            )
            if task.get("pending_finalization") is not None:
                raise HitlRuntimeStateError(
                    "Provider result applies only before discussion task finalization"
                )
            if failed:
                prior = task.get("consecutive_provider_failures", 0)
                if isinstance(prior, bool) or not isinstance(prior, int) or prior < 0:
                    raise HitlRuntimeStateError(
                        "Proposal discussion provider-failure counter is invalid"
                    )
                count = prior + 1
                task["consecutive_provider_failures"] = count
            else:
                count = 0
                task.pop("consecutive_provider_failures", None)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return count

    def begin_proposal_discussion_task_finalization(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        discussion_task_id: str,
        normalized_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            task = self._active_proposal_discussion_task_unlocked(
                session,
                discussion_task_id=discussion_task_id,
            )
            try:
                intent = normalize_proposal_discussion_record(
                    discussion_task_id,
                    task["kind"],
                    normalized_output,
                )["result"]
            except ValueError as exc:
                raise HitlRuntimeStateError(str(exc)) from exc
            existing = task.get("pending_finalization")
            if existing is not None:
                if existing == intent:
                    return self._copy(existing)
                raise HitlRuntimeStateError(
                    "Proposal discussion task already owns a different finalization intent"
                )
            task["pending_finalization"] = intent
            task.pop("consecutive_provider_failures", None)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(intent)

    def complete_proposal_discussion_task_finalization(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        discussion_task_id: str,
        normalized_output: Dict[str, Any],
        result_record_id: str,
    ) -> Dict[str, Any]:
        record_id = str(result_record_id).strip()
        if record_id != discussion_task_id:
            raise HitlRuntimeStateError(
                "Proposal discussion result record must match its task ID"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            task = session["tasks"].get(discussion_task_id)
            if not isinstance(task, dict):
                raise HitlRuntimeStateError("No matching proposal discussion task exists")
            try:
                intent = normalize_proposal_discussion_record(
                    discussion_task_id,
                    task["kind"],
                    normalized_output,
                )["result"]
            except ValueError as exc:
                raise HitlRuntimeStateError(str(exc)) from exc
            if task.get("result_record_id") is not None:
                if task.get("result_record_id") == record_id and (
                    task.get("kind") != "decision"
                    or task.get("choice") == intent.get("choice")
                ):
                    return self._copy(task)
                raise HitlRuntimeStateError(
                    "Proposal discussion task already references a different result"
                )
            self._active_proposal_discussion_task_unlocked(
                session,
                discussion_task_id=discussion_task_id,
            )
            if task.get("pending_finalization") != intent:
                raise HitlRuntimeStateError(
                    "Proposal discussion task has no matching finalization intent"
                )
            task["result_record_id"] = record_id
            if task.get("kind") == "decision":
                task["choice"] = intent["choice"]
            task.pop("pending_finalization", None)
            task.pop("consecutive_provider_failures", None)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(task)

    def advance_proposal_discussion(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        expected_phase: str,
        round_ordinal: int,
    ) -> Dict[str, Any]:
        if expected_phase not in {"initial", "opening", "response"}:
            raise HitlRuntimeStateError(
                "Proposal discussion cannot advance from this phase"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            current_phase = str(session["phase"])
            current_round = int(session["round_ordinal"])
            if expected_phase == "initial" and current_phase == "opening" and current_round == 0:
                return self._copy(session)
            if expected_phase == "opening" and current_phase == "response" and current_round == 1:
                return self._copy(session)
            if (
                expected_phase == "response"
                and current_round == round_ordinal
                and current_phase in {"decision", "final_writing"}
            ):
                return self._copy(session)
            if current_phase != expected_phase or current_round != round_ordinal:
                raise HitlRuntimeStateError("Proposal discussion advance identity is stale")
            if expected_phase == "initial":
                active_ids = [
                    proposal_discussion_task_id("initial", participant_ordinal=ordinal)
                    for ordinal in range(1, int(session["participant_count"]) + 1)
                ]
            elif expected_phase == "opening":
                active_ids = [
                    proposal_discussion_task_id("opening", participant_ordinal=1)
                ]
            else:
                active_ids = self._proposal_discussion_response_ids(
                    current_round,
                    int(session["participant_count"]),
                )
            if not all(
                self._proposal_discussion_task_complete(session["tasks"][task_id])
                for task_id in active_ids
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion cannot advance before every active task completes"
                )
            if expected_phase == "initial":
                opening_id = proposal_discussion_task_id("opening", participant_ordinal=1)
                session["tasks"][opening_id] = {
                    "kind": "contribution",
                    "result_record_id": None,
                }
                session["phase"] = "opening"
            elif expected_phase == "opening":
                session["round_ordinal"] = 1
                for task_id in self._proposal_discussion_response_ids(
                    1,
                    int(session["participant_count"]),
                ):
                    session["tasks"][task_id] = {
                        "kind": "contribution",
                        "result_record_id": None,
                    }
                session["phase"] = "response"
            elif current_round == int(session["max_response_rounds"]):
                session["phase"] = "final_writing"
            else:
                decision_id = proposal_discussion_task_id(
                    "decision",
                    participant_ordinal=1,
                    round_ordinal=current_round,
                )
                session["tasks"][decision_id] = {
                    "kind": "decision",
                    "result_record_id": None,
                }
                session["phase"] = "decision"
            self._validate_proposal_discussion_shape(session)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(session)

    def apply_proposal_discussion_decision(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        round_ordinal: int,
        choice: str,
    ) -> Dict[str, Any]:
        normalized_choice = str(choice).strip().lower()
        if normalized_choice not in {"continue", "finalize"}:
            raise HitlRuntimeStateError(
                "Proposal discussion decision must be continue or finalize"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            if (
                normalized_choice == "continue"
                and session["phase"] == "response"
                and session["round_ordinal"] == round_ordinal + 1
            ) or (
                normalized_choice == "finalize"
                and session["phase"] == "final_writing"
                and session["round_ordinal"] == round_ordinal
            ):
                return self._copy(session)
            if session["phase"] != "decision" or session["round_ordinal"] != round_ordinal:
                raise HitlRuntimeStateError("Proposal discussion decision identity is stale")
            decision_id = proposal_discussion_task_id(
                "decision",
                participant_ordinal=1,
                round_ordinal=round_ordinal,
            )
            decision = session["tasks"].get(decision_id)
            if (
                not self._proposal_discussion_task_complete(decision)
                or decision.get("choice") != normalized_choice
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion decision is not durably ready"
                )
            if normalized_choice == "continue":
                next_round = round_ordinal + 1
                if next_round > int(session["max_response_rounds"]):
                    raise HitlRuntimeStateError(
                        "Proposal discussion cannot continue beyond its round limit"
                    )
                for task_id in self._proposal_discussion_response_ids(
                    next_round,
                    int(session["participant_count"]),
                ):
                    session["tasks"][task_id] = {
                        "kind": "contribution",
                        "result_record_id": None,
                    }
                session["round_ordinal"] = next_round
                session["phase"] = "response"
            else:
                session["phase"] = "final_writing"
            self._validate_proposal_discussion_shape(session)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(session)

    def begin_proposal_discussion_reopen(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        worker_request_key: str,
        proposal_idea_id: str,
        feedback_ref: str,
        reopen_record_id: str,
    ) -> Dict[str, Any]:
        handoff = {
            "worker_request_key": str(worker_request_key).strip(),
            "proposal_idea_id": str(proposal_idea_id).strip(),
            "feedback_ref": str(feedback_ref).strip(),
            "reopen_record_id": str(reopen_record_id).strip(),
        }
        if (
            not handoff["worker_request_key"]
            or _IDEA_ID.fullmatch(handoff["proposal_idea_id"]) is None
            or not handoff["feedback_ref"]
        ):
            raise HitlRuntimeStateError("Proposal discussion reopen identity is invalid")
        try:
            reopen_identity = parse_reopen_discussion_record_id(
                handoff["reopen_record_id"]
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            if session["phase"] == "reopen_pending":
                if session.get("reopen_handoff") == handoff:
                    return self._copy(session)
                raise HitlRuntimeStateError(
                    "Proposal discussion already owns a different reopen handoff"
                )
            if session["phase"] != "final_writing":
                raise HitlRuntimeStateError(
                    "Proposal discussion can reopen only from final writing"
                )
            next_round = int(session["round_ordinal"]) + 1
            if (
                next_round > int(session["max_response_rounds"])
                or reopen_identity.round_ordinal != next_round
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion reopen exceeds or mismatches its round limit"
                )
            session["phase"] = "reopen_pending"
            session["reopen_handoff"] = handoff
            self._validate_proposal_discussion_shape(session)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(session)

    def apply_proposal_discussion_reopen(
        self,
        *,
        parent_node_sha: str,
        preparation_attempt_id: str,
        candidate_attempt_id: str,
        reopen_record_id: str,
        whiteboard_boundary_sha: str,
    ) -> Dict[str, Any]:
        normalized_record_id = str(reopen_record_id).strip()
        try:
            reopen_identity = parse_reopen_discussion_record_id(
                normalized_record_id
            )
        except ValueError as exc:
            raise HitlRuntimeStateError(str(exc)) from exc
        whiteboard_sha = self._normalized_whiteboard_boundary_sha(
            whiteboard_boundary_sha
        )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action, session = self._proposal_discussion_unlocked(
                parent_node_sha=parent_node_sha,
                preparation_attempt_id=preparation_attempt_id,
                candidate_attempt_id=candidate_attempt_id,
            )
            if (
                session["phase"] == "response"
                and session["round_ordinal"] == reopen_identity.round_ordinal
                and session["whiteboard_boundary_sha"] == whiteboard_sha
            ):
                return self._copy(session)
            if (
                session["phase"] != "reopen_pending"
                or not isinstance(session.get("reopen_handoff"), dict)
                or session["reopen_handoff"].get("reopen_record_id")
                != normalized_record_id
                or reopen_identity.round_ordinal != int(session["round_ordinal"]) + 1
            ):
                raise HitlRuntimeStateError(
                    "Proposal discussion reopen handoff identity is stale"
                )
            next_round = reopen_identity.round_ordinal
            for task_id in self._proposal_discussion_response_ids(
                next_round,
                int(session["participant_count"]),
            ):
                session["tasks"][task_id] = {
                    "kind": "contribution",
                    "result_record_id": None,
                }
            session["round_ordinal"] = next_round
            session["phase"] = "response"
            session["whiteboard_boundary_sha"] = whiteboard_sha
            session.pop("reopen_handoff", None)
            self._validate_proposal_discussion_shape(session)
            action["proposal_discussion"] = session
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(session)

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
            phase = {
                "prune_frontier": "pruning",
                "select_frontier": "selecting_next",
                "prepare_proposal": "preparing_proposal",
            }.get(kind, kind)
            self._record_phase_transition_unlocked(
                stage=("experiment_runner" if kind == "prepare_proposal" else "frontier"),
                phase=phase,
                activity="reviewing",
            )
            self._save_unlocked()
            return self._copy(record)

    def record_next_autoresearch_action_decision(
        self,
        kind: str,
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist a manager's AutoResearch choice before applying it.

        A runtime-controlled choice may change more than one store. Retaining the
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
            phase = {
                "prune_frontier": "saving_prune_decision",
                "select_frontier": "saving_selection",
                "prepare_proposal": "saving_proposal_preparation",
            }.get(normalized_kind, f"saving_{normalized_kind}")
            self._record_phase_transition_unlocked(
                stage=(
                    "experiment_runner"
                    if normalized_kind == "prepare_proposal"
                    else "frontier"
                ),
                phase=phase,
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

    def record_next_autoresearch_action_recovery(
        self,
        kind: str,
        recovery: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach one durable stage rollback descriptor to a recorded action."""
        normalized_kind = str(kind).strip()
        if not normalized_kind or not isinstance(recovery, dict) or not recovery:
            raise HitlRuntimeStateError(
                "AutoResearch action recovery requires a kind and descriptor"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if (
                not isinstance(action, dict)
                or action.get("kind") != normalized_kind
                or action.get("status") not in {"decision_recorded", "resolved"}
            ):
                raise HitlRuntimeStateError(
                    "No matching recorded AutoResearch action accepts recovery state"
                )
            existing = action.get("recovery")
            if isinstance(existing, dict):
                if existing == self._copy(recovery):
                    return self._copy(action)
                raise HitlRuntimeStateError(
                    "AutoResearch action already has a different recovery descriptor"
                )
            action["recovery"] = self._copy(recovery)
            action["updated_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(action)

    def record_proposal_preparation_recovery(
        self,
        *,
        workspace_fingerprint: str,
        workspace_fingerprint_scope: Optional[Dict[str, Any]],
        proposal_base_sha: str,
        recovery: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Rebase an undecided preparation action onto one durable boundary."""
        fingerprint = str(workspace_fingerprint).strip()
        prepared_base = str(proposal_base_sha).strip()
        if not fingerprint or not prepared_base or not isinstance(recovery, dict) or not recovery:
            raise HitlRuntimeStateError(
                "Proposal preparation recovery requires a fingerprint, base, and descriptor"
            )
        if workspace_fingerprint_scope is None:
            fingerprint_scope = None
        else:
            from core.hitl_workspace_guard import WorkspaceGuardScope

            fingerprint_scope = WorkspaceGuardScope.from_value(
                workspace_fingerprint_scope
            ).to_dict()
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if (
                not isinstance(action, dict)
                or action.get("kind") != "prepare_proposal"
                or action.get("status") not in {"pending", "cancelled"}
                or isinstance(action.get("decision"), dict)
            ):
                raise HitlRuntimeStateError(
                    "No matching undecided proposal preparation accepts recovery state"
                )
            existing = action.get("recovery")
            if existing is not None:
                if not isinstance(existing, dict):
                    raise HitlRuntimeStateError(
                        "Proposal preparation recovery state is invalid"
                    )
                if existing != self._copy(recovery):
                    raise HitlRuntimeStateError(
                        "Proposal preparation already has a different recovery descriptor"
                    )
            action["workspace_fingerprint"] = fingerprint
            action["proposal_base_sha"] = prepared_base
            if fingerprint_scope is None:
                action.pop("workspace_fingerprint_scope", None)
            else:
                action["workspace_fingerprint_scope"] = fingerprint_scope
            action["recovery"] = self._copy(recovery)
            action["status"] = "pending"
            action.pop("cancellation_reason", None)
            action["updated_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(action)

    def release_next_autoresearch_action_recovery(
        self,
        kind: str,
        *,
        expected: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Detach and return a stage rollback descriptor before discarding it."""
        normalized_kind = str(kind).strip()
        if not normalized_kind:
            raise HitlRuntimeStateError("AutoResearch action recovery requires kind")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if not isinstance(action, dict) or action.get("kind") != normalized_kind:
                raise HitlRuntimeStateError("No matching AutoResearch action owns recovery state")
            recovery = action.get("recovery")
            if recovery is not None and not isinstance(recovery, dict):
                raise HitlRuntimeStateError("AutoResearch action recovery state is invalid")
            if expected is not None and recovery != self._copy(expected):
                raise HitlRuntimeStateError(
                    "AutoResearch action recovery ownership changed before release"
                )
            action.pop("recovery", None)
            action["updated_at"] = _now()
            self._state["next_autoresearch_action"] = action
            self._save_unlocked()
            return self._copy(recovery) if isinstance(recovery, dict) else None

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

    def retire_proposal_preparation_for_budget(
        self,
        *,
        parent_node_sha: str,
    ) -> str:
        """Replay-safely retire control state owned by budget-ended preparation."""
        parent = str(parent_node_sha).strip()
        if not parent:
            raise HitlRuntimeStateError(
                "Budget preparation cleanup requires a frontier parent"
            )

        def belongs_to_parent(value: Any) -> bool:
            if not isinstance(value, dict):
                return False
            provenance = value.get("provenance")
            return bool(
                isinstance(provenance, dict)
                and str(provenance.get("parent_node_id", "")).strip() == parent
            )

        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if isinstance(action, dict) and action:
                if action.get("kind") != "prepare_proposal":
                    raise HitlRuntimeStateError(
                        "Another AutoResearch action replaced proposal preparation"
                    )
                if str(action.get("parent_node_sha", "")).strip() != parent:
                    raise HitlRuntimeStateError(
                        "Proposal preparation belongs to a different frontier node"
                    )

            request_key = ""
            command = self._state.get("pending_worker_command")
            if (
                isinstance(command, dict)
                and command.get("pipeline_stage") == "resource_finder"
                and belongs_to_parent(command)
            ):
                request_key = str(command.get("request_key", "")).strip()
                self._state["pending_worker_command"] = None

            continuation = self._state.get("worker_continuation")
            if (
                isinstance(continuation, dict)
                and continuation.get("pipeline_stage") == "resource_finder"
                and continuation.get("actor") == "resource_finder"
                and belongs_to_parent(continuation)
            ):
                self._state["worker_continuation"] = None

            if isinstance(action, dict) and action:
                self._state["next_autoresearch_action"] = None
            self._save_unlocked()
            return request_key

    def advance_proposal_preparation_after_agent(
        self,
        *,
        parent_node_sha: str,
        attempt_id: str,
        completed_ordinal: int,
        workspace_fingerprint: str,
        workspace_fingerprint_scope: Optional[Dict[str, Any]],
        provenance: Dict[str, Any],
        agent: str,
        pipeline_stage: str,
        proposal_base_sha: Optional[str] = None,
        proposal_artifact_snapshot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically retire one approved agent call and open the next boundary."""
        parent = str(parent_node_sha).strip()
        attempt = str(attempt_id).strip()
        ordinal = int(completed_ordinal)
        fingerprint = str(workspace_fingerprint).strip()
        if workspace_fingerprint_scope is None:
            fingerprint_scope = None
        else:
            from core.hitl_workspace_guard import WorkspaceGuardScope

            fingerprint_scope = WorkspaceGuardScope.from_value(
                workspace_fingerprint_scope
            ).to_dict()
        agent_name = str(agent).strip()
        stage = str(pipeline_stage).strip()
        prepared_base = str(proposal_base_sha or "").strip()
        prepared_artifacts = str(proposal_artifact_snapshot_id or "").strip()
        if prepared_artifacts and not prepared_base:
            raise HitlRuntimeStateError(
                "Prepared artifacts require a proposal workspace checkpoint"
            )
        expected_provenance = {
            str(key): str(value)
            for key, value in dict(provenance or {}).items()
            if str(value).strip()
        }
        if (
            not parent
            or not attempt
            or ordinal < 1
            or not fingerprint
            or not agent_name
            or not stage
        ):
            raise HitlRuntimeStateError(
                "Advancing proposal preparation requires its parent, attempt, "
                "completed ordinal, agent identity, and approved workspace fingerprint"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            action = self._state.get("next_autoresearch_action")
            if (
                not isinstance(action, dict)
                or action.get("kind") != "prepare_proposal"
                or action.get("status") != "resolved"
                or str(action.get("parent_node_sha", "")).strip() != parent
                or str(action.get("attempt_id", "")).strip() != attempt
                or int(action.get("additional_agent_ordinal", 0)) != ordinal
            ):
                raise HitlRuntimeStateError(
                    "Resolved proposal preparation does not match the completed agent call"
                )
            decision = action.get("decision")
            result = action.get("result")
            if (
                not isinstance(decision, dict)
                or decision.get("choice") != "call_additional_agent"
                or decision.get("agent") != agent_name
                or not isinstance(result, dict)
                or result.get("choice") != "call_additional_agent"
                or result.get("agent") != agent_name
            ):
                raise HitlRuntimeStateError(
                    "Resolved proposal preparation is not an approved additional-agent call"
                )

            command = self._state.get("pending_worker_command")
            response = command.get("response") if isinstance(command, dict) else None
            command_provenance = (
                {
                    str(key): str(value)
                    for key, value in dict(command.get("provenance") or {}).items()
                    if str(value).strip()
                }
                if isinstance(command, dict)
                else {}
            )
            command_scope = (
                command.get("workspace_fingerprint_scope")
                if isinstance(command, dict)
                else None
            )
            if (
                not isinstance(command, dict)
                or command.get("pipeline_stage") != stage
                or command.get("kind") != "phase_finish"
                or command.get("hitl_stage") not in {"execution", "review"}
                or command.get("status") != "resolved"
                or not isinstance(response, dict)
                or response.get("status") != "approved"
                or command_provenance != expected_provenance
                or str(command.get("workspace_fingerprint", "")).strip() != fingerprint
                or command_scope != fingerprint_scope
            ):
                raise HitlRuntimeStateError(
                    "The completed agent call has no matching approved worker request"
                )

            next_action = {
                "kind": "prepare_proposal",
                "parent_node_sha": parent,
                "attempt_id": attempt,
                "additional_agent_ordinal": ordinal + 1,
                "workspace_fingerprint": fingerprint,
                "status": "pending",
                "created_at": _now(),
            }
            if prepared_base:
                next_action["proposal_base_sha"] = prepared_base
            if prepared_artifacts:
                next_action["proposal_artifact_snapshot_id"] = prepared_artifacts
            if fingerprint_scope is not None:
                next_action["workspace_fingerprint_scope"] = fingerprint_scope
            self._state["pending_worker_command"] = None
            self._state["worker_continuation"] = None
            self._state["next_autoresearch_action"] = next_action
            self._record_phase_transition_unlocked(
                stage="experiment_runner",
                phase="preparing_proposal",
                activity="reviewing",
            )
            self._save_unlocked()
            return self._copy(next_action)

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

    def begin_bootstrap_prepublication_boundary(
        self,
        boundary: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist the pre-publication bootstrap recovery boundary.

        Recorded before a bootstrap mutates the workspace (preparation and
        scoring), so an interrupted run killed before the publication transition
        exists is rolled back on a later invocation instead of being adopted as
        a new baseline. Carries the source checkpoint and the durable
        provider-local snapshot location, the two things a rollback needs.
        Idempotent: an existing boundary is returned unchanged.
        """
        source_sha = str(boundary.get("source_sha", "")).strip()
        backup_dir = str(boundary.get("agent_local_backup", "")).strip()
        if not source_sha or not backup_dir:
            raise HitlRuntimeStateError(
                "Bootstrap pre-publication boundary requires a source checkpoint "
                "and a durable provider-local snapshot location"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            existing = self._state.get("bootstrap_prepublication_boundary")
            if isinstance(existing, dict) and existing:
                return self._copy(existing)
            record = self._copy(boundary)
            record["status"] = "prepared"
            record["created_at"] = _now()
            self._state["bootstrap_prepublication_boundary"] = record
            self._save_unlocked()
            return self._copy(record)

    def bootstrap_prepublication_boundary(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("bootstrap_prepublication_boundary")
        return value if isinstance(value, dict) and value else None

    def clear_bootstrap_prepublication_boundary(self) -> None:
        """Retire the pre-publication boundary once it is no longer the recovery
        point: after a successful rollback, or after the publication transition
        has been durably established and owns recovery from here on."""
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            if self._state.get("bootstrap_prepublication_boundary"):
                self._state["bootstrap_prepublication_boundary"] = None
                self._save_unlocked()

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
