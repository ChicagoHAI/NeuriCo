"""Attempt-scoped agents available at manager-controlled preparation boundaries.

These runs deliberately do not participate in ``PipelineState``.  They belong
to the active AutoResearch attempt and use the ordinary plan-centered HITL
worker lifecycle after the manager admits them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agents.resource_finder import generate_resource_finder_prompt, run_resource_finder
from core.hitl import (
    HitlRuntime,
    HitlValidationError,
    RequiredArtifact,
    verify_required_artifacts,
)
from core.hitl_mode import HitlMode
from core.hitl_runtime_state import HitlRuntimeState
from core.hitl_stage_runtime import run_plan_centered_hitl_stage
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard


AdditionalAgentExecutor = Callable[..., Dict[str, Any]]


@dataclass(frozen=True)
class AdditionalAgentSpec:
    """One manager-callable agent and its ordinary HITL stage identity."""

    name: str
    pipeline_stage: str
    executor: AdditionalAgentExecutor


def _resource_artifact_validator(work_dir: Path) -> Dict[str, Any]:
    required = [
        RequiredArtifact(
            path=relative,
            purpose="Resource-finder stage output",
            required=True,
        )
        for relative in ("literature_review.md", "resources.md")
    ]
    issues = []
    for artifact in required:
        try:
            verify_required_artifacts(work_dir, [artifact])
        except (OSError, ValueError, HitlValidationError) as exc:
            issues.append(str(exc))
    return {"valid": not issues, "issues": issues}


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
    pending = state.pending_worker_command()
    if not isinstance(pending, dict):
        return None
    response = pending.get("response")
    matches = (
        pending.get("pipeline_stage") == pipeline_stage
        and pending.get("kind") == "phase_finish"
        and pending.get("status") == "resolved"
        and pending.get("hitl_stage") in {"execution", "review"}
        and isinstance(response, dict)
        and response.get("status") == "approved"
        and dict(pending.get("provenance") or {}) == provenance
    )
    if not matches:
        return None
    expected = str(pending.get("workspace_fingerprint", "")).strip()
    current = HitlWorkspaceWriteGuard.public_fingerprint(work_dir)
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


def _with_manager_objective(prompt: str, objective: str) -> str:
    focus = str(objective).strip()
    if not focus:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        "## MANAGER-REQUESTED FOCUS\n\n"
        "Preserve useful existing resources and investigate this information gap:\n\n"
        f"{focus}\n"
    )


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
    worker_prompt_contexts = {
        phase: _with_manager_objective(
            generate_resource_finder_prompt(
                idea,
                templates_dir,
                hitl_runtime_completion=True,
                provider=provider,
                hitl_phase=phase,
            ),
            objective,
        )
        for phase in ("plan", "execution", "review")
    }

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

    def validator() -> Dict[str, Any]:
        return _resource_artifact_validator(work_dir)

    def launch_worker(
        worker_prompt: str,
        worker_log_prefix: str,
        *,
        record_continuation: bool,
    ) -> Dict[str, Any]:
        if record_continuation:
            runtime.register_worker_prompt(worker_prompt)
        safe_prefix = str(worker_log_prefix).replace("/", "_")
        launch_number = 1
        while any(run_logs_dir.glob(f"launch_{launch_number:03d}_*")):
            launch_number += 1
        return run_resource_finder(
            idea=idea,
            work_dir=work_dir,
            provider=provider,
            templates_dir=templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            completion_mode="hitl_runtime",
            log_prefix=f"launch_{launch_number:03d}_{safe_prefix}",
            include_hitl_outputs=True,
            env_extra=runtime.idea_tool_env(),
            prompt_override=worker_prompt,
            logs_dir=run_logs_dir,
        )

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
        return run_plan_centered_hitl_stage(
            runtime=runtime,
            actor="resource_finder",
            worker_name="resource_finder",
            worker_prompt_contexts=worker_prompt_contexts,
            phase_finish_validator=validator,
            launch_worker=launch_worker,
            plan_log_prefix="resource_finder_hitl_plan",
            execution_log_prefix="resource_finder_hitl_execute",
            on_approved=approved,
            on_failed=failed,
            provenance=provenance,
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
