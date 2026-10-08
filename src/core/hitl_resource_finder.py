"""Shared resource-finder HITL execution built from the ordinary stage runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agents.resource_finder import generate_resource_finder_prompt, run_resource_finder
from core.agent_runner import next_attempt_number
from core.hitl import HitlValidationError, RequiredArtifact, verify_required_artifacts
from core.hitl_stage_runtime import run_plan_centered_hitl_stage

ResumeHook = Callable[
    [Any, Callable[..., Dict[str, Any]], Dict[str, str], Callable[[], Dict[str, Any]]],
    Optional[tuple[Dict[str, Any], Dict[str, Any]]],
]


def run_resource_finder_hitl(
    *,
    runtime: Any,
    idea: Dict[str, Any],
    work_dir: Path,
    provider: str,
    templates_dir: Path,
    timeout: Optional[int],
    full_permissions: bool,
    on_approved: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    on_failed: Callable[[Dict[str, Any]], Dict[str, Any]],
    objective: str = "",
    provenance: Optional[Dict[str, Any]] = None,
    resume_worker: Optional[ResumeHook] = None,
    force_fresh_plan: bool = False,
    log_prefix: str = "resource_finder_hitl",
    preserve_log_history: bool = False,
) -> Dict[str, Any]:
    """Run the established resource-finder plan/review/execution lifecycle."""
    root = Path(work_dir)
    worker_prompt_contexts = {
        phase: generate_resource_finder_prompt(
            idea,
            templates_dir,
            hitl_runtime_completion=True,
            provider=provider,
            hitl_phase=phase,
            objective=objective,
        )
        for phase in ("plan", "execution", "review")
    }

    def validate_outputs() -> Dict[str, Any]:
        issues = []
        for relative in ("literature_review.md", "resources.md"):
            try:
                verify_required_artifacts(
                    root,
                    [
                        RequiredArtifact(
                            path=relative,
                            purpose="Resource-finder stage output",
                            required=True,
                        )
                    ],
                )
            except HitlValidationError:
                issues.append(f"Required resource artifact is missing or empty: {relative}")
        return {"valid": not issues, "issues": issues}

    def launch_worker(
        worker_prompt: str,
        worker_log_prefix: str,
        *,
        record_continuation: bool,
    ) -> Dict[str, Any]:
        if record_continuation:
            runtime.register_worker_prompt(worker_prompt)
        launch_log_prefix = worker_log_prefix
        if preserve_log_history:
            logs_dir = root / "logs"
            attempt = next_attempt_number(
                logs_dir,
                lambda number: f"{worker_log_prefix}_attempt{number}_prompt.txt",
            )
            launch_log_prefix = f"{worker_log_prefix}_attempt{attempt}"
        return run_resource_finder(
            idea=idea,
            work_dir=root,
            provider=provider,
            templates_dir=templates_dir,
            timeout=timeout,
            full_permissions=full_permissions,
            completion_mode="hitl_runtime",
            log_prefix=launch_log_prefix,
            include_hitl_outputs=True,
            env_extra=runtime.idea_tool_env(),
            prompt_override=worker_prompt,
        )

    if resume_worker is not None:
        resumed = resume_worker(
            runtime,
            launch_worker,
            worker_prompt_contexts,
            validate_outputs,
        )
        if resumed is not None:
            result, finish = resumed
            return (
                on_approved(result, finish)
                if finish.get("approved")
                else on_failed(finish or result)
            )

    return run_plan_centered_hitl_stage(
        runtime=runtime,
        actor="resource_finder",
        worker_name="resource_finder",
        worker_prompt_contexts=worker_prompt_contexts,
        phase_finish_validator=validate_outputs,
        launch_worker=launch_worker,
        plan_log_prefix=f"{log_prefix}_plan",
        execution_log_prefix=f"{log_prefix}_execute_1",
        on_approved=on_approved,
        on_failed=on_failed,
        expected_provenance=provenance,
        force_fresh_plan=force_fresh_plan,
    )
