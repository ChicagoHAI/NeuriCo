"""Read-only projection of canonical HITL workspace artifacts for the web UI.

The browser never reads workspace files directly and never reconstructs research
state from SSE fragments.  This module is the one translation boundary between
the durable HITL records and a complete UI snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.hitl import HitlIdeaLog, HitlValidationError
from core.hitl_frontier import HitlFrontierError, HitlFrontierStore
from core.hitl_lock import active_hitl_workspace_run
from core.hitl_manager_history import HitlManagerHistory
from core.hitl_manager_inbox import HitlManagerInbox
from core.hitl_manager_context import HitlManagerContext
from core.hitl_paths import (
    hitl_launch_status_path,
    hitl_runtime_state_path,
    hitl_state_dir,
)
from core.hitl_whiteboard import hitl_whiteboard_path
from core.whiteboard import MAX_TIP_CONTENT_CHARS


class HitlWorkspaceViewError(RuntimeError):
    """A durable HITL artifact cannot be faithfully presented."""


def _read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HitlWorkspaceViewError(f"Missing {label}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HitlWorkspaceViewError(f"Unreadable {label}: {path}") from exc
    if not isinstance(value, dict):
        raise HitlWorkspaceViewError(f"{label.capitalize()} must be a JSON object: {path}")
    return value


def _as_records(value: Any, label: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise HitlWorkspaceViewError(f"{label} must be a list of objects.")
    return [dict(item) for item in value]


class HitlWorkspaceView:
    """Build an immutable, complete UI snapshot from one HITL workspace."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.root = hitl_state_dir(self.work_dir)

    def snapshot(self) -> Dict[str, Any]:
        if not self.root.is_dir():
            raise HitlWorkspaceViewError(
                f"This workspace has no HITL state at {self.root}."
            )
        ideas = self._ideas()
        nodes, attempts, frontier = self._frontier()
        whiteboard = self._whiteboard()
        research = self._research_state()
        runtime = self._runtime_state()
        inbox = self._inbox(runtime)
        conversation = self._conversation(inbox)
        notifications = self._notifications(runtime, ideas)
        return {
            "workspace": self.work_dir.name,
            "autoresearch": self._autoresearch_status(),
            "live": self._live_status(runtime),
            "conversation": conversation,
            "notifications": notifications,
            "inbox": inbox,
            "research": research,
            "ideas": ideas,
            "frontier": frontier,
            "nodes": nodes,
            "attempts": attempts,
            "whiteboard": whiteboard,
            "activity": self._activity(ideas, nodes, attempts, whiteboard),
            "context": self._context(),
        }

    def live_status(self) -> Dict[str, Any]:
        """Project the durable workflow into one interface-neutral live status."""
        runtime = self._runtime_state()
        return self._live_status(runtime)

    def notifications(self) -> List[Dict[str, Any]]:
        """Return the shared, user-facing projection of durable interface events."""
        runtime = self._runtime_state()
        return self._notifications(runtime, self._ideas())

    def _runtime_state(self) -> Dict[str, Any]:
        path = hitl_runtime_state_path(self.work_dir)
        return _read_object(path, "HITL runtime state") if path.exists() else {}

    def _launch_status(self) -> Dict[str, Any]:
        path = hitl_launch_status_path(self.work_dir)
        return _read_object(path, "HITL launch status") if path.exists() else {}

    @staticmethod
    def _record_timestamp(record: Any) -> str:
        if not isinstance(record, dict):
            return ""
        for key in (
            "updated_at",
            "resolved_at",
            "decision_recorded_at",
            "created_at",
            "started_at",
        ):
            value = str(record.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _phase_start_timestamp(record: Any) -> str:
        if not isinstance(record, dict):
            return ""
        for key in ("started_at", "created_at", "updated_at", "resolved_at"):
            value = str(record.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _workflow_token(value: Any) -> str:
        token = str(value or "").strip()
        return "" if token.lower() in {"none", "null"} else token

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _latest_phase_event(
        self,
        runtime: Dict[str, Any],
        run_started_at: str,
    ) -> Dict[str, Any]:
        """Return the latest visible phase transition from the current durable run."""
        run_start = self._parse_timestamp(run_started_at)
        events = runtime.get("interface_events", [])
        if not isinstance(events, list):
            return {}
        for event in reversed(events):
            if not isinstance(event, dict) or event.get("kind") != "phase_transition":
                continue
            if self._retired_run_event(event):
                continue
            if str(event.get("activity", "")).strip() == "revising":
                continue
            created_at = self._parse_timestamp(event.get("created_at"))
            if run_start is not None and (created_at is None or created_at < run_start):
                continue
            return event
        return {}

    @classmethod
    def _retired_run_event(cls, event: Dict[str, Any]) -> bool:
        return (
            cls._workflow_token(event.get("stage")) == "research"
            and cls._workflow_token(event.get("phase"))
            in {"starting", "completed", "stopped"}
        )

    @staticmethod
    def _stage_label(stage: str) -> str:
        labels = {
            "resource_finder": "Resource finding",
            "rule_maker": "Rule making",
            "experiment_runner": "Experiment",
            "paper_writer": "Paper writing",
        }
        return labels.get(stage, stage.replace("_", " ").strip().title())

    @staticmethod
    def _working_phase_label(phase: str) -> str:
        labels = {
            "proposal": "Preparing proposal",
            "plan": "Planning",
            "execution": "Executing",
            "review": "Revising",
        }
        return labels.get(phase, phase.replace("_", " ").strip().title())

    @staticmethod
    def _review_phase_label(phase: str) -> str:
        labels = {
            "proposal": "Proposal review",
            "plan": "Plan review",
            "execution": "Execution review",
            "review": "Revision review",
        }
        return labels.get(phase, f"{phase.replace('_', ' ').strip().title()} review")

    @staticmethod
    def _next_after_phase(phase: str) -> str:
        return {
            "proposal": "Review follows.",
            "plan": "Review follows.",
            "execution": "Results are reviewed next.",
            "review": "The next research step follows.",
        }.get(phase, "Research continues to the next step.")

    def _pipeline_state(self) -> Dict[str, Any]:
        path = self.work_dir / ".neurico" / "pipeline_state.json"
        return _read_object(path, "pipeline state") if path.exists() else {}

    def _live_status(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        """Interpret runtime facts once for every HITL user interface."""
        owner = active_hitl_workspace_run(self.work_dir)
        pipeline = self._pipeline_state()
        pending = runtime.get("pending_worker_command")
        pending = pending if isinstance(pending, dict) else {}
        continuation = runtime.get("worker_continuation")
        continuation = continuation if isinstance(continuation, dict) else {}
        next_action = runtime.get("next_autoresearch_action")
        next_action = next_action if isinstance(next_action, dict) else {}
        frontier_transition = runtime.get("frontier_decision_transition")
        frontier_transition = frontier_transition if isinstance(frontier_transition, dict) else {}
        root_transition = runtime.get("initial_root_publication_transition")
        root_transition = root_transition if isinstance(root_transition, dict) else {}
        cleanup = runtime.get("rejected_whiteboard_cleanup")
        cleanup = cleanup if isinstance(cleanup, dict) else {}
        pending_status = str(pending.get("status", "")).strip()
        unresolved = pending_status in {
            "pending",
            "scoring_approval_pending",
            "scoring",
        }
        active_pending = pending if unresolved else {}
        stage = self._workflow_token(
            active_pending.get("pipeline_stage")
            or continuation.get("pipeline_stage")
            or pipeline.get("current_stage")
            or ""
        )
        phase = self._workflow_token(
            active_pending.get("hitl_stage") or continuation.get("hitl_stage") or ""
        )
        stage_label = self._stage_label(stage) if stage else ""
        phase_label = self._working_phase_label(phase) if phase else ""
        started_at = str((owner or {}).get("started_at") or "").strip()
        provider = str((owner or {}).get("provider") or "").strip()
        mode = str((owner or {}).get("mode") or "").strip()
        latest_phase_event = self._latest_phase_event(runtime, started_at)
        latest_phase_started_at = str(latest_phase_event.get("created_at", "")).strip()
        paper_phase = bool(
            self._workflow_token(latest_phase_event.get("stage")) == "paper_writer"
            and self._workflow_token(latest_phase_event.get("phase")) == "drafting"
        )

        def projected(
            state: str,
            title: str,
            detail: str,
            *,
            next_step: str,
            record: Any = None,
            active: bool = True,
            display_stage: Optional[str] = None,
            display_phase: Optional[str] = None,
            phase_started_at: Optional[str] = None,
        ) -> Dict[str, Any]:
            visible_stage = stage_label if display_stage is None else display_stage
            visible_phase = phase_label if display_phase is None else display_phase
            label = " · ".join(part for part in (visible_stage, visible_phase) if part) or title
            return {
                "state": state,
                "active": active,
                "can_launch": not active,
                "title": title,
                "detail": detail,
                "stage": stage,
                "stage_label": visible_stage,
                "phase": phase,
                "phase_label": visible_phase,
                "label": label,
                "mode": mode,
                "provider": provider,
                "started_at": started_at,
                "phase_started_at": (
                    phase_started_at
                    if phase_started_at is not None
                    else latest_phase_started_at
                    or self._phase_start_timestamp(record)
                    or started_at
                ),
                "updated_at": self._record_timestamp(record),
                "next_action": next_step,
            }

        human_request = unresolved and bool(
            pending.get("human_request_record_id")
            and str(pending.get("human_request_record_id")).strip()
        )
        action_status = str(next_action.get("status", "")).strip()
        frontier_status = str(frontier_transition.get("status", "")).strip()
        root_status = str(root_transition.get("status", "")).strip()
        cleanup_pending = str(cleanup.get("status", "")).strip() == "pending"
        continuation_status = str(continuation.get("status", "")).strip()
        launch_status = self._launch_status()

        pending_kind = str(pending.get("kind", "")).strip()
        manager_review_kind = str(pending.get("manager_review_kind", "")).strip()

        def pending_labels() -> tuple[str, str]:
            if manager_review_kind == "initial_scoring":
                return "Scoring", "Initial result review"
            if manager_review_kind == "frontier_scoring":
                return "Candidate decision", "Accept or reject"
            if manager_review_kind == "scoring_failure":
                return "Scoring", "Repair review"
            if pending_kind == "proposal":
                return "Experiment", "Proposal review"
            return stage_label, self._review_phase_label(phase) if phase else "Review"

        def durable_boundary_labels() -> tuple[str, str]:
            if unresolved:
                return pending_labels()
            if action_status in {"pending", "decision_recorded"}:
                kind = str(next_action.get("kind", "")).strip()
                if kind == "prune_frontier":
                    return "Frontier", (
                        "Pruning" if action_status == "pending" else "Saving prune decision"
                    )
                if kind == "select_frontier":
                    return "Frontier", (
                        "Selecting next" if action_status == "pending" else "Saving selection"
                    )
            if frontier_status not in {"", "completed"}:
                return "Candidate decision", "Saving result"
            if root_status not in {"", "completed"}:
                return "Frontier", "Creating root"
            if cleanup_pending:
                return "Candidate decision", "Applying result"
            if continuation_status:
                return stage_label, self._working_phase_label(phase) if phase else "Working"
            if paper_phase:
                return "Paper writing", "Drafting"
            if stage_label:
                return stage_label, "Starting"
            return "Research", "Starting"

        has_pending_work = bool(
            unresolved
            or action_status in {"pending", "decision_recorded"}
            or frontier_status not in {"", "completed"}
            or root_status not in {"", "completed"}
            or cleanup_pending
            or continuation_status
        )
        if owner is None:
            if str(launch_status.get("status", "")).strip() == "failed":
                mode = str(launch_status.get("mode", "")).strip()
                provider = str(launch_status.get("provider", "")).strip()
                return projected(
                    "failed",
                    "Unable to start",
                    str(launch_status.get("message", "")).strip()
                    or "Research could not start.",
                    next_step="Review the issue, then try again.",
                    record=launch_status,
                    active=False,
                    display_stage="Start failed",
                    display_phase="",
                )
            if has_pending_work:
                if unresolved:
                    record = pending
                elif action_status in {"pending", "decision_recorded"}:
                    record = next_action
                elif frontier_status not in {"", "completed"}:
                    record = frontier_transition
                elif root_status not in {"", "completed"}:
                    record = root_transition
                elif cleanup_pending:
                    record = cleanup
                elif continuation_status:
                    record = continuation
                paused_stage, paused_phase = durable_boundary_labels()
                return projected(
                    "paused",
                    "Paused",
                    "Progress is saved.",
                    next_step="Continue when ready.",
                    record=record,
                    active=False,
                    display_stage=paused_stage,
                    display_phase=f"{paused_phase} paused" if paused_phase else "Paused",
                )
            if bool(pipeline.get("completed")):
                return projected(
                    "completed",
                    "Complete",
                    "Research is ready to inspect.",
                    next_step=(
                        "Continue research when ready."
                        if HitlFrontierStore(self.work_dir).exists()
                        else "Inspect the completed research artifacts."
                    ),
                    record=pipeline,
                    active=False,
                    display_stage="Complete",
                    display_phase="",
                    phase_started_at=str(pipeline.get("completed_at", "")),
                )
            if HitlFrontierStore(self.work_dir).exists():
                return projected(
                    "idle",
                    "Ready",
                    "Previous research is available.",
                    next_step="Continue research when ready.",
                    active=False,
                    display_stage="Ready",
                    display_phase="",
                )
            return projected(
                "idle",
                "Ready",
                "No research run has started yet.",
                next_step="Start research when ready.",
                active=False,
                display_stage="Ready",
                display_phase="",
            )

        if human_request:
            review_stage, review_phase = pending_labels()
            return projected(
                "review_needed",
                "Review needed",
                "A decision is needed to continue.",
                next_step="Open the request to approve it or provide feedback.",
                record=pending,
                display_stage=review_stage,
                display_phase=review_phase,
            )

        if pending_status == "scoring_approval_pending":
            return projected(
                "evaluating",
                "Preparing scoring",
                "The approved result is being prepared for scoring.",
                next_step="Scoring begins automatically.",
                record=pending,
                display_stage="Scoring",
                display_phase="Preparing",
            )
        if pending_status == "scoring":
            return projected(
                "evaluating",
                "Scoring",
                "Evaluating the latest result.",
                next_step="The score is reviewed next.",
                record=pending,
                display_stage="Scoring",
                display_phase="Evaluating results",
            )
        if pending_status == "pending":
            review_stage, review_phase = pending_labels()
            return projected(
                "reviewing",
                "Reviewing",
                "Checking the latest research.",
                next_step="Research continues or a decision is requested.",
                record=pending,
                display_stage=review_stage,
                display_phase=review_phase,
            )

        if action_status in {"pending", "decision_recorded"}:
            action_stage, action_phase = durable_boundary_labels()
            if action_status == "pending":
                return projected(
                    "reviewing",
                    "Reviewing",
                    "Choosing the next research direction.",
                    next_step="Research continues from the selected direction.",
                    record=next_action,
                    display_stage=action_stage,
                    display_phase=action_phase,
                )
            return projected(
                "saving",
                "Saving progress",
                "Updating the research direction.",
                next_step="Research continues from the selected direction.",
                record=next_action,
                display_stage=action_stage,
                display_phase=action_phase,
            )

        transition = frontier_transition if frontier_status not in {"", "completed"} else root_transition
        transition_status = frontier_status if transition is frontier_transition else root_status
        if transition_status not in {"", "completed"}:
            transition_stage, transition_phase = durable_boundary_labels()
            return projected(
                "saving",
                "Saving progress",
                "Recording the latest research.",
                next_step="Research continues from the saved progress.",
                record=transition,
                display_stage=transition_stage,
                display_phase=transition_phase,
            )

        if cleanup_pending:
            record = cleanup
            resume_stage, resume_phase = durable_boundary_labels()
            return projected(
                "resuming",
                "Resuming",
                "Continuing from saved progress.",
                next_step="Research resumes automatically.",
                record=record,
                display_stage=resume_stage,
                display_phase=resume_phase,
            )

        if continuation_status:
            working_stage, working_phase = durable_boundary_labels()
            return projected(
                "researching",
                "Researching",
                "Working on the current research step.",
                next_step=self._next_after_phase(phase),
                record=continuation,
                display_stage=working_stage,
                display_phase=working_phase,
            )

        if paper_phase:
            return projected(
                "researching",
                "Writing paper",
                "Preparing the research paper.",
                next_step="The completed research is available when writing finishes.",
                record=latest_phase_event,
                display_stage="Paper writing",
                display_phase="Drafting",
                phase_started_at=latest_phase_started_at,
            )

        current_stage = self._workflow_token(pipeline.get("current_stage", ""))
        if current_stage:
            stage = current_stage
            stage_label = self._stage_label(stage)
            stage_record = (pipeline.get("stages") or {}).get(stage, {})
            return projected(
                "researching",
                "Researching",
                "Working on the current research step.",
                next_step="Review follows when this step is ready.",
                record=stage_record,
                display_phase="Starting",
            )

        return projected(
            "starting",
            "Starting",
            "Preparing the research.",
            next_step="Research begins shortly.",
            record=owner,
            display_stage="Research",
            display_phase="Starting",
        )

    def _autoresearch_status(self) -> Dict[str, Any]:
        has_frontier_state = HitlFrontierStore(self.work_dir).exists()
        return {
            "mode": "continue" if has_frontier_state else "fresh",
            "has_frontier_state": has_frontier_state,
        }

    @staticmethod
    def _compact_notification_text(value: Any, limit: int = 220) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
        return f"{shortened or text[: limit - 1]}…"

    @staticmethod
    def _decision_option_text(idea: Dict[str, Any]) -> str:
        selected = str(idea.get("decision", "")).strip()
        for option in idea.get("options", []):
            if isinstance(option, str):
                option_id = option_text = option
            elif isinstance(option, dict):
                option_id = str(option.get("option_id", "")).strip()
                option_text = str(option.get("text", "")).strip()
            else:
                continue
            if selected and selected in {option_id, option_text}:
                return option_text
        return selected

    def _phase_notification(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        stage = self._workflow_token(event.get("stage", ""))
        phase = self._workflow_token(event.get("phase", ""))
        activity = str(event.get("activity", "")).strip()
        if activity == "revising":
            return None
        stage_labels = {
            "research": "Research",
            "scoring": "Scoring",
            "candidate_decision": "Candidate decision",
            "frontier": "Frontier",
        }
        title = stage_labels.get(stage, self._stage_label(stage) if stage else "Research")

        special_summaries = {
            "starting": "Starting.",
            "completed": "Run completed.",
            "stopped": "Run stopped.",
            "initial_result_review": "Reviewing the initial score.",
            "accept_or_reject": "Reviewing whether to accept or reject the latest result.",
            "repair_review": "Reviewing a scoring issue.",
            "preparing": "Preparing the approved result for scoring.",
            "evaluating_results": "Evaluating the latest result.",
            "pruning": "Pruning the frontier.",
            "selecting_next": "Selecting the next research basis.",
            "saving_prune_decision": "Saving the prune decision.",
            "saving_selection": "Saving the frontier selection.",
            "saving_result": "Saving the candidate decision.",
            "creating_root": "Creating the initial frontier root.",
            "applying_result": "Applying the candidate decision.",
        }
        summary = special_summaries.get(phase, "")
        if not summary and not phase and stage == "experiment_runner" and activity == "reviewing":
            summary = "Proposal review started."
        if not summary:
            if activity == "reviewing":
                phase_label = self._review_phase_label(phase)
            elif activity == "revising":
                phase_label = "Revising" if phase == "review" else f"Revising {phase.replace('_', ' ')}"
            else:
                phase_label = self._working_phase_label(phase)
            summary = f"{phase_label} started." if phase_label else "Research advanced."
        return {
            "id": str(event.get("id", "")),
            "kind": "phase",
            "created_at": str(event.get("created_at", "")),
            "tone": "neutral",
            "title": title,
            "summary": summary,
        }

    def _idea_notification(
        self,
        event: Dict[str, Any],
        idea: Dict[str, Any],
    ) -> Dict[str, Any]:
        idea_type = str(idea.get("idea_type", "")).strip()
        idea_id = str(idea.get("idea_id", "")).strip()
        if idea_type == "decision":
            title = "Decision made"
            question = self._compact_notification_text(idea.get("decision_needed"), 120)
            decision = self._compact_notification_text(self._decision_option_text(idea), 160)
            if question and decision:
                summary = f"About {question}: {decision}"
            else:
                summary = decision or question or "A research decision was recorded."
            tone = "decision"
        elif idea_type == "evidence":
            title = "Evidence recorded"
            summary = self._compact_notification_text(
                idea.get("evidence") or idea.get("context") or "New research evidence was recorded."
            )
            tone = "evidence"
        else:
            title = "Proposal generated"
            summary = self._compact_notification_text(
                idea.get("proposal") or idea.get("context") or "A new research proposal was generated."
            )
            tone = "proposal"
        return {
            "id": str(event.get("id", "")),
            "kind": "idea",
            "created_at": str(event.get("created_at", "")),
            "tone": tone,
            "title": title,
            "summary": summary,
            "idea_id": idea_id,
            "idea_type": idea_type,
        }

    def _request_notification(self, event: Dict[str, Any]) -> Dict[str, Any]:
        outcome = str(event.get("outcome", "")).strip().lower()
        summaries = {
            "approved": "Approved. Research continues.",
            "feedback": "Feedback recorded. Revision follows.",
            "rejected": "Not approved. Research continues from saved progress.",
        }
        return {
            "id": str(event.get("id", "")),
            "kind": "request",
            "created_at": str(event.get("created_at", "")),
            "tone": "resolved",
            "title": "Review resolved",
            "summary": summaries.get(outcome, "Response recorded. Research continues."),
        }

    def _notifications(
        self,
        runtime: Dict[str, Any],
        ideas: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        events = runtime.get("interface_events", [])
        if not isinstance(events, list):
            return []
        ideas_by_id = {str(idea.get("idea_id", "")): idea for idea in ideas}
        projected: List[Dict[str, Any]] = []
        last_phase_signature: Optional[tuple[str, str]] = None
        first_phase_event = next(
            (
                event
                for event in events
                if isinstance(event, dict)
                and event.get("kind") == "phase_transition"
                and not self._retired_run_event(event)
            ),
            None,
        )
        if first_phase_event is not None and not (
            self._workflow_token(first_phase_event.get("stage")) == "research"
            and self._workflow_token(first_phase_event.get("phase")) == "starting"
        ):
            projected.append(
                {
                    "id": f"start:{first_phase_event.get('id', '')}",
                    "kind": "phase",
                    "created_at": str(first_phase_event.get("created_at", "")),
                    "tone": "phase",
                    "title": "Research",
                    "summary": "Starting.",
                }
            )
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("kind") == "phase_transition":
                if self._retired_run_event(event):
                    continue
                notification = self._phase_notification(event)
                if notification is not None:
                    phase_signature = (
                        str(notification.get("title", "")),
                        str(notification.get("summary", "")),
                    )
                    if phase_signature == last_phase_signature:
                        continue
                    last_phase_signature = phase_signature
                    projected.append(notification)
            elif event.get("kind") == "idea_created":
                idea = ideas_by_id.get(str(event.get("idea_id", "")))
                if idea is not None:
                    projected.append(self._idea_notification(event, idea))
            elif event.get("kind") == "request_resolved":
                if bool(event.get("human_involved")):
                    projected.append(self._request_notification(event))
        return sorted(projected, key=lambda item: str(item.get("created_at", "")))

    def _ideas(self) -> List[Dict[str, Any]]:
        log = HitlIdeaLog(self.work_dir)
        records = log.records()
        seen: set[str] = set()
        for record in records:
            try:
                HitlIdeaLog.validate(record, existing_ids=seen)
            except HitlValidationError as exc:
                raise HitlWorkspaceViewError(
                    f"Invalid finalized HITL idea {record.get('idea_id', '<unknown>')}: {exc}"
                ) from exc
            seen.add(str(record["idea_id"]))
        return records

    def _frontier(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        store = HitlFrontierStore(self.work_dir)
        if not store.exists():
            return [], [], {"selected_frontier_node_sha": None, "active_frontier_node_shas": []}
        try:
            state = store.state(allow_unselected=True)
        except HitlFrontierError as exc:
            raise HitlWorkspaceViewError(str(exc)) from exc

        node_paths = sorted((self.root / "nodes").glob("*/*.json"))
        nodes: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        nodes_by_sha: Dict[str, Dict[str, Any]] = {}
        for path in node_paths:
            payload = _read_object(path, "frontier node")
            node_sha = str(payload.get("node_sha", "")).strip()
            if not node_sha or node_sha != path.stem:
                raise HitlWorkspaceViewError(f"Invalid node identity in {path}")
            if node_sha in nodes_by_sha:
                raise HitlWorkspaceViewError(f"Duplicate HITL node record for {node_sha}")
            plan_path = path.with_suffix(".md")
            if not plan_path.is_file():
                raise HitlWorkspaceViewError(f"Accepted HITL node is missing its saved plan: {node_sha}")
            try:
                payload["plan"] = plan_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise HitlWorkspaceViewError(
                    f"Accepted HITL node has an unreadable saved plan: {node_sha}"
                ) from exc
            payload["active"] = node_sha in state["active_frontier_node_shas"]
            payload["selected"] = node_sha == state["selected_frontier_node_sha"]
            nodes_by_sha[node_sha] = payload
            nodes.append(payload)

        for parent_dir in sorted((self.root / "nodes").glob("*")):
            attempts_dir = parent_dir / "attempts"
            if not attempts_dir.is_dir():
                continue
            parent_sha = parent_dir.name
            if parent_sha not in nodes_by_sha:
                raise HitlWorkspaceViewError(
                    f"Attempt history has no parent frontier node: {parent_sha}"
                )
            for path in sorted(attempts_dir.glob("*.json")):
                payload = _read_object(path, "frontier attempt")
                candidate = str(payload.get("node_sha", "")).strip()
                if not candidate or candidate != path.stem:
                    raise HitlWorkspaceViewError(f"Invalid attempt identity in {path}")
                if not isinstance(payload.get("accepted"), bool):
                    raise HitlWorkspaceViewError(f"Attempt accepted flag must be boolean: {path}")
                if payload["accepted"] and candidate not in nodes_by_sha:
                    raise HitlWorkspaceViewError(
                        f"Accepted attempt {candidate} is missing its frontier node record."
                    )
                payload["parent_node_sha"] = parent_sha
                attempts.append(payload)

        missing_active = [sha for sha in state["active_frontier_node_shas"] if sha not in nodes_by_sha]
        if missing_active:
            raise HitlWorkspaceViewError(
                "Active frontier refers to missing node record(s): " + ", ".join(missing_active)
            )
        return nodes, attempts, state

    def _whiteboard(self) -> Dict[str, Any]:
        path = hitl_whiteboard_path(self.work_dir)
        if not path.exists():
            return {"tips": []}
        payload = _read_object(path, "HITL whiteboard")
        tips = _as_records(payload.get("tips", []), "HITL whiteboard tips")
        for tip in tips:
            content = str(tip.get("content", ""))
            if not str(tip.get("id", "")).strip() or not content.strip():
                raise HitlWorkspaceViewError("Every HITL whiteboard tip requires id and content.")
            if len(content) > MAX_TIP_CONTENT_CHARS:
                tip["content"] = content[:MAX_TIP_CONTENT_CHARS]
            if not isinstance(tip.get("affects", []), list) or any(
                not isinstance(value, str) for value in tip.get("affects", [])
            ):
                raise HitlWorkspaceViewError("Every HITL whiteboard tip affects field must be a list of paths.")
        return {"tips": tips}

    def _research_state(self) -> Dict[str, Any]:
        path = self.work_dir / ".neurico" / "research_state.json"
        if not path.exists():
            return {"narrative": "", "crux": "", "hypotheses": [], "open_questions": []}
        state = _read_object(path, "research state")
        for key in ("narrative", "crux"):
            if key in state and not isinstance(state[key], str):
                raise HitlWorkspaceViewError(f"Research state {key} must be a string.")
        for key in ("hypotheses", "experiments", "findings", "decisions"):
            if key in state:
                _as_records(state[key], f"research state {key}")
        questions = state.get("open_questions", [])
        if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
            raise HitlWorkspaceViewError("Research state open_questions must be a list of strings.")
        return state

    def _context(self) -> Dict[str, int]:
        manager_dir = self.root / "manager"
        if not (manager_dir / "context.jsonl").exists():
            return {"used_tokens": 0, "limit_tokens": 300_000, "percent": 0}
        try:
            return HitlManagerContext(manager_dir).usage()
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read NeuriCo conversation context.") from exc

    @staticmethod
    def _artifact_timestamp(path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except OSError as exc:
            raise HitlWorkspaceViewError(f"Could not read artifact timestamp: {path}") from exc

    def _activity(
        self,
        ideas: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        attempts: List[Dict[str, Any]],
        whiteboard: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Chronological activity sourced only from durable HITL artifacts."""
        activity: List[Dict[str, Any]] = [
            {
                "id": f"idea:{idea['idea_id']}",
                "kind": "idea",
                "timestamp": idea["timestamp"],
                "record": idea,
            }
            for idea in ideas
        ]
        for node in nodes:
            path = self.root / "nodes" / str(node["node_sha"]) / f"{node['node_sha']}.json"
            activity.append({
                "id": f"node:{node['node_sha']}",
                "kind": "node",
                "timestamp": self._artifact_timestamp(path),
                "record": node,
            })
        for attempt in attempts:
            if bool(attempt.get("accepted")):
                continue
            parent = str(attempt["parent_node_sha"])
            candidate = str(attempt["node_sha"])
            path = self.root / "nodes" / parent / "attempts" / f"{candidate}.json"
            activity.append({
                "id": f"attempt:{candidate}",
                "kind": "attempt",
                "timestamp": self._artifact_timestamp(path),
                "record": attempt,
            })
        for tip in whiteboard["tips"]:
            timestamp = tip.get("written_at")
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if not isinstance(timestamp, str) or not timestamp.strip():
                timestamp = self._artifact_timestamp(hitl_whiteboard_path(self.work_dir))
            activity.append({
                "id": f"whiteboard:{tip['id']}",
                "kind": "whiteboard",
                "timestamp": timestamp,
                "record": tip,
            })
        return sorted(activity, key=lambda entry: str(entry["timestamp"]))

    def _conversation(self, inbox: Dict[str, Any]) -> List[Dict[str, str]]:
        manager_dir = self.root / "manager"
        path = manager_dir / "history.sqlite"
        if not path.exists():
            return []
        try:
            records = HitlManagerHistory.read_messages(manager_dir)
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read NeuriCo conversation history.") from exc
        # A request is a manager conversation turn with an additional structured
        # action surface.  Keep it in the durable transcript; the browser hides
        # that exact turn only while its request panel remains unresolved.
        del inbox
        conversation: List[Dict[str, str]] = []
        for record in records:
            metadata = record.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("visibility") != "human":
                continue
            if metadata.get("kind") not in {
                "human_message",
                "human_reply",
                "human_request",
                "manager_reply",
            }:
                continue
            content = str(record.get("content") or "").strip()
            if not content or content.lower() == "null":
                continue
            normalized = dict(record)
            normalized["content"] = content
            conversation.append(normalized)
        return conversation

    def _inbox(self, runtime: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = HitlManagerInbox(self.work_dir).snapshot()
        except Exception as exc:
            raise HitlWorkspaceViewError("Could not read the NeuriCo input state.") from exc
        queue = _as_records(payload.get("queue", []), "NeuriCo input queue")
        for entry in queue:
            if not str(entry.get("id", "")).strip() or not str(entry.get("text", "")).strip():
                raise HitlWorkspaceViewError("Every queued NeuriCo message requires id and text.")
        pending = runtime.get("pending_worker_command")
        pending = pending if isinstance(pending, dict) else None
        record_id = str((pending or {}).get("human_request_record_id") or "").strip()
        request = None
        if record_id:
            request_key = str(pending.get("request_key", "")).strip()
            try:
                record = next(
                    item
                    for item in HitlManagerHistory.read_messages(self.root / "manager")
                    if str(item.get("record_id", "")) == record_id
                )
            except StopIteration as exc:
                raise HitlWorkspaceViewError("The pending request is missing its conversation record.") from exc
            metadata = record.get("metadata")
            if (
                not request_key
                or not isinstance(metadata, dict)
                or metadata.get("kind") != "human_request"
                or str(metadata.get("request_key", "")) != request_key
            ):
                raise HitlWorkspaceViewError("The pending request is incomplete.")
            options = metadata.get("options")
            if not isinstance(options, list):
                raise HitlWorkspaceViewError("The pending request options are invalid.")
            request = {
                "request_key": request_key,
                "message": str(record.get("content", "")).strip(),
                "options": [
                    {"id": f"option_{index + 1}", "text": str(option)}
                    for index, option in enumerate(options)
                    if str(option).strip()
                ],
                "created_at": record.get("created_at", ""),
                "conversation_record_id": record_id,
            }
        return {"queue": queue, "pending_request": request}
