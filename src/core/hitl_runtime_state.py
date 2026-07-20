"""Durable runtime control state for one HITL workspace.

This state is intentionally separate from the interactive manager's
conversation.  It records only workflow facts that must survive a worker or
manager process restart.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from core.hitl_lock import exclusive_file_lock


class HitlRuntimeStateError(RuntimeError):
    """Raised when HITL runtime control state cannot make a safe transition."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class HitlRuntimeState:
    """Atomic workspace-level state for the current HITL workflow.

    A manager may converse freely at all times.  The only exclusive runtime
    resource is one blocking worker command, represented by
    ``pending_worker_command``.  AutoResearch frontier selection is stored as a
    separate next action because no worker is waiting for it.
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.hitl_dir = self.work_dir / ".neurico" / "hitl"
        self.path = self.hitl_dir / "runtime.json"
        self.lock_path = self.hitl_dir / "runtime.lock"
        self.hitl_dir.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            self._save_unlocked()

    @staticmethod
    def _default() -> Dict[str, Any]:
        return {
            "worker_continuation": None,
            "pending_worker_command": None,
            "next_autoresearch_action": None,
            "rejected_whiteboard_cleanup": None,
            "frontier_decision_transition": None,
            "approved_plans": {},
        }

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
        return merged

    def _save_unlocked(self) -> None:
        self._state["updated_at"] = _now()
        temporary = self.path.with_suffix(".json.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._state, indent=2, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._fsync_parent_directory()
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _fsync_parent_directory(self) -> None:
        """Persist the replacement directory entry where the platform allows it."""
        try:
            descriptor = os.open(self.hitl_dir, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Some platforms do not permit directory fsync; the file itself is
            # still flushed before replacement.
            pass
        finally:
            os.close(descriptor)

    def snapshot(self) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            return self._copy(self._state)

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
            self._save_unlocked()

    def update_worker_continuation(self, **updates: Any) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            continuation = self._state.get("worker_continuation")
            if not isinstance(continuation, dict):
                return
            continuation.update(self._copy(updates))
            continuation["updated_at"] = _now()
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
            self._save_unlocked()

    def clear_worker_continuation(self) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            self._state["worker_continuation"] = None
            self._save_unlocked()

    def mark_plan_approved(self, *, pipeline_stage: str, plan_fingerprint: str) -> None:
        if not pipeline_stage or not plan_fingerprint:
            raise HitlRuntimeStateError(
                "Plan approval requires pipeline stage and plan fingerprint"
            )
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            approvals = self._state.setdefault("approved_plans", {})
            approvals[str(pipeline_stage)] = {
                "plan_fingerprint": str(plan_fingerprint),
                "approved_at": _now(),
            }
            self._save_unlocked()

    def has_plan_approval(self, *, pipeline_stage: str, plan_fingerprint: str) -> bool:
        approvals = self.snapshot().get("approved_plans", {})
        record = approvals.get(str(pipeline_stage)) if isinstance(approvals, dict) else None
        return isinstance(record, dict) and record.get("plan_fingerprint") == str(plan_fingerprint)

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
            record.setdefault("human_question", None)
            record.setdefault("human_replies", [])
            record.setdefault("manager_provider_turns", 0)
            record["created_at"] = _now()
            self._state["pending_worker_command"] = record
            self._save_unlocked()
            return self._copy(record)

    def consume_manager_provider_turn(self, request_key: str, *, limit: int) -> int:
        """Atomically charge one provider turn to a held worker request.

        Human waiting is not a provider turn. The count survives reminders and
        manager restarts, so a request cannot receive an unbounded sequence of
        fresh ReAct budgets.
        """
        if limit < 1:
            raise HitlRuntimeStateError("HITL manager provider-turn limit must be positive")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            used = int(command.get("manager_provider_turns", 0))
            if used >= limit:
                raise HitlRuntimeStateError(
                    f"HITL manager exhausted its {limit}-turn provider budget for this worker request."
                )
            command["manager_provider_turns"] = used + 1
            command["manager_provider_turn_limit"] = limit
            command["updated_at"] = _now()
            self._state["pending_worker_command"] = command
            self._save_unlocked()
            return used + 1

    def update_pending_worker_command(self, request_key: str, **updates: Any) -> Dict[str, Any]:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            command.update(self._copy(updates))
            command["updated_at"] = _now()
            self._save_unlocked()
            return self._copy(command)

    def complete_worker_command(self, request_key: str, response: Dict[str, Any]) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            command["status"] = "resolved"
            command["response"] = self._copy(response)
            command["resolved_at"] = _now()
            self._state["pending_worker_command"] = command
            self._save_unlocked()

    def cancel_pending_worker_command(self, request_key: str, *, reason: str) -> Dict[str, Any]:
        """Release a held command before restoring its attempt boundary.

        This is only for runtime rollback. A cancelled command is never a worker
        response and must not be finalized by a stale manager turn.
        """
        message = str(reason).strip()
        if not message:
            raise HitlRuntimeStateError("Cancelled HITL worker command requires a reason")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict) or command.get("request_key") != request_key:
                raise HitlRuntimeStateError("No matching pending HITL worker command")
            if command.get("status") == "resolved":
                return self._copy(command)
            command["status"] = "cancelled"
            command["cancellation_reason"] = message
            command["cancelled_at"] = _now()
            command["human_question"] = None
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
            self._save_unlocked()

    def clear_completed_worker_command(self, request_key: str) -> None:
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if isinstance(command, dict) and command.get("request_key") == request_key:
                self._state["pending_worker_command"] = None
                self._save_unlocked()

    def request_human_reply(
        self, request_key: str, *, message: str, options: list[str]
    ) -> Dict[str, Any]:
        if not message.strip():
            raise HitlRuntimeStateError("Human resolution question cannot be empty")
        return self.update_pending_worker_command(
            request_key,
            human_question={
                "message": message,
                "options": self._copy(options),
                "requested_at": _now(),
            },
        )

    def record_human_reply(self, response: str) -> Dict[str, Any]:
        reply = str(response).strip()
        if not reply:
            raise HitlRuntimeStateError("Human resolution reply cannot be empty")
        with self._locked():
            self._state = self._load_unlocked() or self._default()
            command = self._state.get("pending_worker_command")
            if not isinstance(command, dict):
                raise HitlRuntimeStateError("No pending HITL worker command needs a human reply")
            question = command.get("human_question")
            if not isinstance(question, dict):
                raise HitlRuntimeStateError(
                    "The pending HITL worker command has no open human question"
                )
            command.setdefault("human_replies", []).append(
                {
                    "message": question.get("message", ""),
                    "options": question.get("options", []),
                    "response": reply,
                }
            )
            command["human_question"] = None
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
            self._save_unlocked()
            return self._copy(record)

    def frontier_decision_transition(self) -> Optional[Dict[str, Any]]:
        value = self.snapshot().get("frontier_decision_transition")
        return value if isinstance(value, dict) and value else None

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
