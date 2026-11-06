"""Agents available inside a manager-controlled proposal-preparation session.

These runs deliberately do not participate in ``PipelineState``.  They belong
to the preparation session preceding an AutoResearch candidate and use the
ordinary plan-centered HITL worker lifecycle after the manager admits them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.hitl import HitlRuntime
from core.hitl_mode import HitlMode
from core.hitl_planning_mode import (
    COLLABORATIVE_PLANNING_MODE,
    PENDING_PLANNING_POLICY_FIELD,
    PlanningModeConfig,
    normalize_pending_planning_policy,
)
from core.hitl_resource_finder import (
    run_resource_finder_hitl,
    validate_resource_finder_outputs,
)
from core.hitl_runtime_state import HitlRuntimeState, worker_command_requires_resume
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard


AdditionalAgentExecutor = Callable[..., Dict[str, Any]]


@dataclass(frozen=True)
class AdditionalAgentSpec:
    """One manager-callable agent and its ordinary HITL stage identity."""

    name: str
    pipeline_stage: str
    executor: AdditionalAgentExecutor


def _resource_artifact_validator(work_dir: Path) -> Dict[str, Any]:
    return validate_resource_finder_outputs(work_dir)


def _resource_outputs(work_dir: Path) -> Dict[str, str]:
    candidates = {
        "literature_review": work_dir / "literature_review.md",
        "resources_catalog": work_dir / "resources.md",
        "papers_dir": work_dir / "papers",
        "datasets_dir": work_dir / "datasets",
        "code_dir": work_dir / "code",
        "hitl_plan": work_dir / "plans" / "resource_finder_plan.md",
    }
    return {name: str(path) for name, path in candidates.items() if path.exists()}


def _approved_saved_request(
    *,
    work_dir: Path,
    pipeline_stage: str,
    provenance: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Reuse only the exact, manager-approved workspace that was reviewed."""
    state = HitlRuntimeState(work_dir)
    action = state.snapshot().get("next_autoresearch_action")
    action_status = str(action.get("status", "")) if isinstance(action, dict) else ""
    resolved_agent_action = (
        isinstance(action, dict)
        and action.get("kind") == "prepare_proposal"
        and action_status in {"decision_recorded", "resolved"}
        and (
            dict(action.get("decision") or {}).get("choice") == "call_additional_agent"
            or dict(action.get("result") or {}).get("choice")
            == "call_additional_agent"
        )
    )
    pending = state.pending_worker_command()
    if not isinstance(pending, dict):
        if resolved_agent_action and action_status == "decision_recorded":
            return None
        if resolved_agent_action:
            raise RuntimeError(
                "The recovered additional-agent action has no approved worker request. "
                "The whole attempt must roll back."
            )
        return None
    response = pending.get("response")
    continuation = state.worker_continuation()
    request_belongs_here = bool(
        pending.get("pipeline_stage") == pipeline_stage
        and dict(pending.get("provenance") or {}) == provenance
    )
    if (
        resolved_agent_action
        and action_status == "decision_recorded"
        and not request_belongs_here
        and pending.get("status") == "resolved"
    ):
        # A newly authorized agent may replace the completed request retained
        # for idempotence by the preceding stage.
        return None
    approved_plan_handoff = bool(
        request_belongs_here
        and pending.get("kind") == "phase_finish"
        and pending.get("hitl_stage") == "plan"
        and pending.get("status") == "resolved"
        and isinstance(response, dict)
        and response.get("status") == "approved"
        and isinstance(continuation, dict)
        and continuation.get("pipeline_stage") == pipeline_stage
        and continuation.get("hitl_stage") == "execution"
        and dict(continuation.get("provenance") or {}) == provenance
    )
    if resolved_agent_action and request_belongs_here and (
        worker_command_requires_resume(pending) or approved_plan_handoff
    ):
        # The ordinary plan-centered stage validates the saved continuation
        # before reconnecting a replacement worker. This helper only consumes
        # a fully approved final workspace.
        return None
    matches = (
        request_belongs_here
        and pending.get("kind") == "phase_finish"
        and pending.get("status") == "resolved"
        and pending.get("hitl_stage") in {"execution", "review"}
        and isinstance(response, dict)
        and response.get("status") == "approved"
    )
    if not matches:
        if resolved_agent_action:
            raise RuntimeError(
                "The recovered additional-agent action does not match its approved "
                "worker request. The whole attempt must roll back."
            )
        return None
    expected = str(pending.get("workspace_fingerprint", "")).strip()
    current = HitlWorkspaceWriteGuard.public_fingerprint(
        work_dir,
        scope=pending.get("workspace_fingerprint_scope"),
    )
    if not expected or current != expected:
        raise RuntimeError(
            "The recovered additional-agent workspace differs from the exact "
            "snapshot approved by the manager. The whole attempt must roll back."
        )
    validation = _resource_artifact_validator(work_dir)
    if not validation["valid"]:
        raise RuntimeError(
            "The recovered resource-finder approval no longer satisfies its artifact "
            f"contract: {validation['issues']}"
        )
    state.clear_worker_continuation()
    return pending


def _run_resource_finder_agent(
    *,
    idea: Dict[str, Any],
    work_dir: Path,
    templates_dir: Path,
    provider: str,
    timeout: Optional[int],
    full_permissions: bool,
    manager: Any,
    channel: Any,
    manager_config: Optional[Dict[str, Any]],
    hitl_mode: HitlMode | str,
    objective: str,
    attempt_dir: Path,
    ordinal: int,
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    runtime = HitlRuntime(
        work_dir,
        "resource_finder",
        manager=manager,
        channel=channel,
        config=manager_config,
        use_hitl_autoresearch_whiteboard=True,
        hitl_mode=hitl_mode,
    )
    run_logs_dir = Path(attempt_dir) / f"additional_agent_{ordinal:02d}_resource_finder"
    run_logs_dir.mkdir(parents=True, exist_ok=True)

    recovered = _approved_saved_request(
        work_dir=work_dir,
        pipeline_stage="resource_finder",
        provenance=provenance,
    )
    if recovered is not None:
        return {
            "success": True,
            "hitl": True,
            "phase": "complete",
            "resumed": True,
            "outputs": _resource_outputs(work_dir),
            "logs_dir": str(run_logs_dir),
        }

    planning_mode = PlanningModeConfig(mode="single")
    planning_owner = None
    planning_record_root = None
    state = HitlRuntimeState(work_dir)
    action = state.snapshot().get("next_autoresearch_action")
    attachment = state.stage_planning_discussion_attachment()
    policy_present = bool(
        isinstance(action, dict)
        and PENDING_PLANNING_POLICY_FIELD in action
    )
    raw_policy = (
        action.get(PENDING_PLANNING_POLICY_FIELD) if policy_present else None
    )
    if policy_present:
        policy = normalize_pending_planning_policy(raw_policy)
        planning_mode = PlanningModeConfig(
            mode=COLLABORATIVE_PLANNING_MODE,
            participant_count=policy["participant_count"],
            discussion_rounds=policy["discussion_rounds"],
        )
    if policy_present or attachment is not None:
        recovery = action.get("recovery") if isinstance(action, dict) else None
        if (
            not isinstance(action, dict)
            or action.get("kind") != "prepare_proposal"
            or not isinstance(recovery, dict)
            or recovery.get("stage") != "additional_agent"
        ):
            raise RuntimeError(
                "Collaborative resource planning requires its additional-agent recovery boundary."
            )
        planning_owner = {
            "kind": "additional_agent",
            "pipeline_stage": "resource_finder",
            "rollback_ref": str(recovery.get("hitl_snapshot_ref", "")).strip(),
            "parent_node_id": str(provenance.get("parent_node_id", "")).strip(),
            "attempt_id": str(provenance.get("attempt_id", "")).strip(),
            "additional_agent_ordinal": ordinal,
        }
        planning_record_root = run_logs_dir / "planning_discussion"

    def approved(result: Dict[str, Any], finish: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **result,
            "success": True,
            "hitl": True,
            "phase": "complete",
            "outputs": _resource_outputs(work_dir),
            "logs_dir": str(run_logs_dir),
            **(
                {"worker_exit_warning": finish["worker_exit_warning"]}
                if finish.get("worker_exit_warning")
                else {}
            ),
        }

    def failed(result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **result,
            "success": False,
            "hitl": True,
            "logs_dir": str(run_logs_dir),
        }

    try:
        return run_resource_finder_hitl(
            runtime=runtime,
            idea=idea,
            work_dir=work_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            on_approved=approved,
            on_failed=failed,
            provenance=provenance,
            objective=objective,
            invocation_mode="additive",
            force_fresh_plan=True,
            logs_dir=run_logs_dir,
            preserve_log_history=True,
            planning_mode_config=planning_mode,
            planning_meeting_owner=planning_owner,
            planning_meeting_record_root=planning_record_root,
        )
    finally:
        runtime.clear_idea_tool_context()


ADDITIONAL_AGENT_SPECS: Dict[str, AdditionalAgentSpec] = {
    "resource_finder": AdditionalAgentSpec(
        name="resource_finder",
        pipeline_stage="resource_finder",
        executor=_run_resource_finder_agent,
    )
}


def additional_agent_spec(name: str) -> AdditionalAgentSpec:
    """Return the normalized allowlisted agent or reject the request."""
    normalized = str(name).strip().lower().replace("-", "_")
    try:
        return ADDITIONAL_AGENT_SPECS[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(ADDITIONAL_AGENT_SPECS))
        raise ValueError(
            f"Unsupported additional agent '{name}'. Available: {available}"
        ) from exc


def run_additional_agent(agent: str, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch one admitted agent through its registered ordinary executor."""
    spec = additional_agent_spec(agent)
    result = spec.executor(**kwargs)
    return {**result, "agent": spec.name, "pipeline_stage": spec.pipeline_stage}
