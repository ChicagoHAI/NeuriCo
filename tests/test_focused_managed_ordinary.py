"""Focused managed Ordinary research routing and prompt contracts."""

from __future__ import annotations

import json
from copy import deepcopy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cli.hitl_run_worker as hitl_worker  # noqa: E402
import cli.hitl_launcher as hitl_launcher  # noqa: E402
from core.hitl_manager_react import HitlManager  # noqa: E402
from core.pipeline_orchestrator import (  # noqa: E402
    PipelineState,
    ResearchPipelineOrchestrator,
)
from templates.prompt_generator import PromptGenerator  # noqa: E402


IDEA = {
    "idea": {
        "title": "Solve the supplied task",
        "hypothesis": "A carefully tested solution will satisfy the task.",
        "description": "Develop, test, and deliver the strongest solution within the task requirements.",
        "domain": "artificial_intelligence",
    }
}


def _ordinary(work_dir: Path, focus: bool | None = None) -> ResearchPipelineOrchestrator:
    return ResearchPipelineOrchestrator(
        work_dir=work_dir,
        templates_dir=ROOT / "templates",
        managed_initial_run=True,
        focused_autoresearch=focus,
    )


def test_focused_ordinary_state_is_persisted_inherited_and_immutable(tmp_path):
    first = _ordinary(tmp_path, True)

    assert first.focused_managed_ordinary is True
    assert first.state.state["workflow"] == "ordinary"
    assert first.state.state["focused_autoresearch"] is True
    assert first._managed_initial_stages() == ("resource_finder", "experiment_runner")

    resumed = _ordinary(tmp_path)
    assert resumed.focused_managed_ordinary is True
    assert PipelineState.read_focused_managed_ordinary(tmp_path) is True

    with pytest.raises(RuntimeError, match="different focused-mode setting"):
        _ordinary(tmp_path, False)


def test_focused_ordinary_pipeline_runs_only_resource_and_experiment_stages(
    tmp_path, monkeypatch
):
    orchestrator = _ordinary(tmp_path, True)
    calls = []
    monkeypatch.setattr(
        orchestrator,
        "_run_resource_finder_hitl",
        lambda **_kwargs: calls.append("resource_finder") or {"success": True},
    )
    monkeypatch.setattr(
        orchestrator,
        "_run_experiment_runner_hitl",
        lambda **_kwargs: calls.append("experiment_runner") or {"success": True},
    )

    result = orchestrator.run_pipeline(
        IDEA,
        provider="codex",
        scoring_enabled=False,
        hitl_enabled=True,
    )

    assert result["success"] is True
    assert calls == ["resource_finder", "experiment_runner"]
    assert set(result["stages"]) == {"resource_finder", "experiment_runner"}


def test_legacy_ordinary_workspace_without_focus_remains_unfocused(tmp_path):
    state_dir = tmp_path / ".neurico"
    state_dir.mkdir(parents=True)
    (state_dir / "pipeline_state.json").write_text(
        json.dumps(
            {
                "created_at": "legacy",
                "workflow": "ordinary",
                "stages": {},
                "current_stage": None,
                "completed": False,
            }
        ),
        encoding="utf-8",
    )

    resumed = _ordinary(tmp_path)
    assert resumed.focused_managed_ordinary is False
    assert "focused_autoresearch" not in resumed.state.state

    with pytest.raises(RuntimeError, match="different focused-mode setting"):
        _ordinary(tmp_path, True)


def test_focus_survives_supported_ordinary_to_autoresearch_conversion(tmp_path):
    state = _ordinary(tmp_path, True).state
    state.state["completed"] = True
    state._save()

    state.convert_completed_ordinary_to_autoresearch()

    payload = json.loads(state.state_file.read_text(encoding="utf-8"))
    assert "workflow" not in payload
    assert payload["focused_autoresearch"] is True
    converted = ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=ROOT / "templates",
        hitl_autoresearch=True,
    )
    assert converted.focused_autoresearch is True
    assert converted.focused_managed_ordinary is False


def test_baseline_construction_cannot_change_focus(tmp_path):
    with pytest.raises(ValueError, match="Focused mode is valid only"):
        ResearchPipelineOrchestrator(
            work_dir=tmp_path,
            templates_dir=ROOT / "templates",
            baseline_construction=True,
            focused_autoresearch=True,
        )


@pytest.mark.parametrize("benchmark_mode", [False, True])
def test_focused_ordinary_experiment_prompts_are_solution_oriented_and_unscored(
    tmp_path, benchmark_mode
):
    orchestrator = _ordinary(tmp_path, True)

    prompts = {
        phase: orchestrator._hitl_experiment_runner_source_prompt(
            idea=IDEA,
            provider="codex",
            use_scribe=False,
            scoring_enabled=False,
            hitl_phase=phase,
            benchmark_mode=benchmark_mode,
        )
        for phase in ("plan", "execution", "review")
    }

    assert "Treat the resource finder's findings as inputs" in prompts["plan"]
    assert "develop, combine, or replace approaches as warranted" in prompts["plan"]
    assert "Each experiment should help develop, improve, or evaluate the solution" in prompts[
        "execution"
    ]
    assert "Apply the manager's feedback to improve or validate the solution" in prompts[
        "review"
    ]
    assert "Why You Expect This Solution to Best Address the Task" in prompts["execution"]
    assert "DIRECTION BUDGET" not in prompts["execution"]
    for phase, prompt in prompts.items():
        expected = phase in {"execution", "review"}
        assert prompt.count("When the task requires an answer") == int(expected)
        if expected:
            assert "make and submit your\nbest-supported judgment" in prompt
            assert "separately without changing the required output format" in prompt
            assert "required answer solely because uncertainty remains" in prompt
        assert "scoring/interface.md" not in prompt
        assert "selected direction" not in prompt.lower()


def test_autoresearch_and_unfocused_ordinary_keep_their_existing_prompt_branches(tmp_path):
    autoresearch = ResearchPipelineOrchestrator(
        work_dir=tmp_path / "autoresearch",
        templates_dir=ROOT / "templates",
        hitl_autoresearch=True,
        focused_autoresearch=True,
    )
    autoresearch_prompt = autoresearch._hitl_experiment_runner_source_prompt(
        idea=IDEA,
        provider="codex",
        use_scribe=False,
        scoring_enabled=True,
        hitl_phase="execution",
    )
    autoresearch_benchmark_prompt = autoresearch._hitl_experiment_runner_source_prompt(
        idea=IDEA,
        provider="codex",
        use_scribe=False,
        scoring_enabled=True,
        hitl_phase="execution",
        benchmark_mode=True,
    )
    ordinary_prompt = _ordinary(tmp_path / "ordinary", False)._hitl_experiment_runner_source_prompt(
        idea=IDEA,
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="execution",
    )

    assert "FOCUSED HITL AUTORESEARCH SCOPE" in autoresearch_prompt
    assert autoresearch_benchmark_prompt == autoresearch_prompt
    assert "selected direction" in autoresearch_prompt.lower()
    assert "FOCUSED MANAGED ORDINARY RESEARCH" not in autoresearch_prompt
    assert "FOCUSED MANAGED ORDINARY RESEARCH" not in ordinary_prompt
    assert "DIRECTION BUDGET" in ordinary_prompt
    for prompt in (autoresearch_prompt, ordinary_prompt):
        assert "When the task requires an answer" not in prompt


def test_resource_finder_uses_distinct_bootstrap_and_additional_contracts():
    generator = PromptGenerator(ROOT / "templates")
    bootstrap = generator.generate_resource_finder_prompt(
        IDEA,
        hitl_runtime_completion=True,
        hitl_phase="plan",
        focused_managed_ordinary=True,
    )
    additional = generator.generate_resource_finder_prompt(
        IDEA,
        hitl_runtime_completion=True,
        hitl_phase="plan",
        objective="Investigate whether the current approach should be replaced.",
        invocation_mode="additive",
        focused_managed_ordinary=True,
    )

    assert "Recommend the\napproach you judge most likely" in bootstrap
    assert "not as a prescribed solution" not in bootstrap
    assert "Gather the\nevidence and resources needed to address that objective" in additional
    assert "Do not reopen the workspace's direction-selection decision" not in additional
    assert "established managed research workspace" in additional
    assert "DIRECTION BUDGET" not in bootstrap
    assert "DIRECTION BUDGET" not in additional
    for prompt in (bootstrap, additional):
        assert "When the task requires an answer" not in prompt


@pytest.mark.parametrize("focused", [False, True])
def test_additive_collaborative_discussion_keeps_planning_constraints(focused):
    prompt = PromptGenerator(ROOT / "templates").generate_resource_finder_prompt(
        IDEA,
        hitl_runtime_completion=True,
        hitl_phase="discussion",
        invocation_mode="additive",
        focused_autoresearch=focused,
    )
    assert "ADDITIVE INVOCATION — PLANNING CONSTRAINTS" in prompt
    assert "RESOURCE-FINDER DIRECTION LIMIT" in prompt
    assert "ADDITIVE INVOCATION — EXISTING WORKSPACE IS AUTHORITATIVE" not in prompt
    assert "FOCUSED MANAGED ORDINARY RESEARCH" not in prompt
    assert ("FOCUSED HITL AUTORESEARCH SCOPE" in prompt) == focused


@pytest.mark.parametrize("phase", ["plan", "execution", "review"])
def test_resource_description_is_scoped_and_preserves_existing_context(phase):
    generator = PromptGenerator(ROOT / "templates")
    idea = deepcopy(IDEA)
    idea["idea"]["background"] = {"context": "Existing background context."}
    kwargs = {"hitl_runtime_completion": True, "hitl_phase": phase}
    without_description = generator.generate_resource_finder_prompt(
        idea, focused_managed_ordinary=True, **kwargs
    )
    assert "User-Provided Instructions and Context" not in without_description

    idea["idea"]["background"]["description"] = ""
    assert generator.generate_resource_finder_prompt(
        idea, focused_managed_ordinary=True, **kwargs
    ) == without_description
    legacy_prompts = {
        focused: generator.generate_resource_finder_prompt(
            idea, focused_autoresearch=focused, **kwargs
        )
        for focused in (False, True)
    }
    idea["idea"]["background"]["description"] = "Full task instructions."
    prompt = generator.generate_resource_finder_prompt(
        idea, focused_managed_ordinary=True, **kwargs
    )
    assert "Full task instructions." in prompt
    assert "Existing background context." in prompt
    for focused, legacy_prompt in legacy_prompts.items():
        assert generator.generate_resource_finder_prompt(
            idea, focused_autoresearch=focused, **kwargs
        ) == legacy_prompt


@pytest.mark.parametrize("phase", ["plan", "execution", "review"])
def test_resource_finder_receives_complete_description_with_short_hypothesis(phase):
    generator = PromptGenerator(ROOT / "templates")
    idea = deepcopy(IDEA)
    instruction = (
        "Investigate the supplied data.\n\n"
        + "Check the assumptions and validate the analysis. " * 40
        + "\nRequired output: /app/final.json\n  Preserve this indentation.\n"
    )
    idea["idea"]["hypothesis"] = instruction[:200]
    idea["idea"]["background"] = {"description": instruction}
    prompt = generator.generate_resource_finder_prompt(
        idea,
        provider="codex",
        hitl_runtime_completion=True,
        hitl_phase=phase,
        focused_managed_ordinary=True,
    )
    assert "Required output" not in idea["idea"]["hypothesis"]
    assert prompt.count(instruction) == 1
    assert generator._extract_user_instructions(prompt) == instruction.strip()


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("phase", ["plan", "execution", "review"])
@pytest.mark.parametrize("stage", ["resource_finder", "experiment_runner"])
def test_manager_phase_review_receives_focused_ordinary_context(
    tmp_path, focused, phase, stage
):
    _ordinary(tmp_path, focused)
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.request_worker_resolution = lambda **kwargs: kwargs["prompt"]

    prompt = manager.review_phase_finish(
        pipeline_stage=stage,
        hitl_stage=phase,
        plan_text="Plan",
        finish_summary="Ready",
        related_artifacts=[],
        request_key="request-key",
        requires_human_approval=False,
        hitl_mode="auto",
    )

    assert ("deliver the best solution\npossible" in prompt) is focused
    assert ("Do not\nrequire novelty, competing implementations" in prompt) is focused
    expected = focused and stage == "experiment_runner" and phase != "plan"
    assert prompt.count("When the task requires an answer") == int(expected)
    if expected:
        assert "documented separately but does not replace the required answer" in prompt
        assert "best-supported judgment satisfies the task's requirements" in prompt
    if stage == "resource_finder":
        assert "`literature_review.md` and `resources.md` are mandatory" in prompt
    assert "AutoResearch candidate" not in prompt


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("autoresearch", [False, True])
@pytest.mark.parametrize("phase", ["execution", "review"])
@pytest.mark.parametrize("stage", ["resource_finder", "experiment_runner"])
def test_manager_raised_idea_submission_guidance_is_scoped(
    tmp_path, focused, autoresearch, phase, stage
):
    ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=ROOT / "templates",
        managed_initial_run=True,
        hitl_autoresearch=autoresearch,
        focused_autoresearch=focused,
    )
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.request_worker_resolution = lambda **kwargs: kwargs["prompt"]
    prompt = manager.review_raised_idea(
        pipeline_stage=stage,
        raised_idea={
            "actor": stage,
            "hitl_stage": phase,
            "question": "Evidence is ambiguous.",
        },
        plan_text="Preserve the required output format.",
        hitl_mode="auto",
        request_context=(
            {"parent_node_id": "parent", "attempt_id": "attempt", "proposal_idea_id": "idea"}
            if autoresearch else None
        ),
    )
    assert "Evidence is ambiguous." in prompt
    assert "Preserve the required output format." in prompt
    expected = focused and not autoresearch and stage == "experiment_runner"
    assert prompt.count("When the task requires an answer") == int(expected)
    assert ("deliver the best solution\npossible" in prompt) is (
        focused and not autoresearch
    )


def test_detached_worker_accepts_focused_ordinary_request(tmp_path, monkeypatch):
    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        hitl_worker,
        "ConfigLoader",
        lambda: type("Config", (), {"get_workspace_parent_dir": lambda self: tmp_path})(),
    )
    monkeypatch.setattr(
        hitl_worker,
        "workspace_for_idea",
        lambda _root, _idea_id: work_dir,
    )
    request_path = tmp_path / f"request.task.{'a' * 32}.json.claimed"
    request_path.write_text(
        json.dumps(
            {
                "version": 5,
                "request_id": "a" * 32,
                "idea_id": "task",
                "work_dir": str(work_dir),
                "project_root": str(ROOT),
                "provider": "codex",
                "mode": "fresh",
                "interface": "cli",
                "workflow": "ordinary",
                "operation": "research",
                "hitl_mode": "auto",
                "proposal_mode": "single",
                "focused_autoresearch": True,
            }
        ),
        encoding="utf-8",
    )

    request = hitl_worker._load_request(request_path)

    assert request["workflow"] == "ordinary"
    assert request["focused_autoresearch"] is True
    assert request["time_limit_seconds"] is None


def test_launcher_emits_focus_for_fresh_ordinary_run(tmp_path, monkeypatch):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.setattr(
        hitl_launcher,
        "ConfigLoader",
        lambda: type("Config", (), {"get_workspace_parent_dir": lambda self: tmp_path})(),
    )
    monkeypatch.setattr(
        hitl_launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(wait=lambda: 0),
    )
    launcher = hitl_launcher.HitlRunController(
        idea_id="task",
        work_dir=work_dir,
        project_root=ROOT,
        host=SimpleNamespace(),
        interface="cli",
    )

    result = launcher.launch(
        {
            "provider": "codex",
            "operation": "research",
            "workflow": "ordinary",
            "hitl_mode": "auto",
            "focused_autoresearch": True,
        }
    )

    request_path = next(
        (tmp_path / ".neurico" / "hitl-launch-requests").glob("request.*.json")
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert result["focused_autoresearch"] is True
    assert request["workflow"] == "ordinary"
    assert request["focused_autoresearch"] is True
    assert "iterations" not in request
    assert "time_limit_seconds" not in request


def test_launcher_omission_inherits_focused_ordinary_state(tmp_path, monkeypatch):
    work_dir = tmp_path / "work"
    _ordinary(work_dir, True)
    monkeypatch.setattr(
        hitl_launcher,
        "ConfigLoader",
        lambda: type("Config", (), {"get_workspace_parent_dir": lambda self: tmp_path})(),
    )
    monkeypatch.setattr(
        hitl_launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(wait=lambda: 0),
    )
    launcher = hitl_launcher.HitlRunController(
        idea_id="task",
        work_dir=work_dir,
        project_root=ROOT,
        host=SimpleNamespace(),
        interface="cli",
    )

    result = launcher.launch(
        {
            "provider": "codex",
            "operation": "research",
            "workflow": "ordinary",
            "hitl_mode": "auto",
        }
    )

    assert result["focused_autoresearch"] is True

    with pytest.raises(RuntimeError, match="different focused-mode setting"):
        launcher.launch(
            {
                "provider": "codex",
                "operation": "research",
                "workflow": "ordinary",
                "hitl_mode": "auto",
                "focused_autoresearch": False,
            }
        )


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize(
    "workflow,planning_mode",
    [("ordinary", "single"), ("autoresearch", "single"), ("autoresearch", "collaborative")],
)
def test_resource_stage_preserves_focus_and_planning_routing(
    tmp_path, monkeypatch, workflow, planning_mode, focused
):
    from core import pipeline_orchestrator as pipeline
    from core.hitl_planning_mode import normalize_planning_mode_config

    planning = normalize_planning_mode_config(planning_mode)
    orchestrator = ResearchPipelineOrchestrator(
        work_dir=tmp_path,
        templates_dir=ROOT / "templates",
        managed_initial_run=True,
        hitl_autoresearch=workflow == "autoresearch",
        focused_autoresearch=focused,
        planning_mode_config=planning,
    )
    rollback = SimpleNamespace(
        hitl_snapshot=SimpleNamespace(ref="refs/neurico/hitl-rollback/resource-test")
    )
    monkeypatch.setattr(orchestrator, "_initial_stage_request", lambda _stage: None)
    monkeypatch.setattr(
        orchestrator,
        "_create_hitl_runtime",
        lambda _stage: SimpleNamespace(clear_idea_tool_context=lambda: None),
    )
    monkeypatch.setattr(orchestrator, "_stage_rollback", lambda *_args: rollback)
    captured = {}

    def capture_stage(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(pipeline, "run_resource_finder_hitl", capture_stage)
    result = orchestrator._run_resource_finder_hitl(IDEA, "codex", None, False)

    assert result["success"] is True
    assert captured["focused_managed_ordinary"] is (focused and workflow == "ordinary")
    assert captured["focused_autoresearch"] is (focused and workflow == "autoresearch")
    assert captured["planning_mode_config"] == planning
    if planning_mode == "collaborative":
        assert captured["planning_meeting_owner"] == {
            "kind": "initial_stage",
            "pipeline_stage": "resource_finder",
            "rollback_ref": rollback.hitl_snapshot.ref,
        }
        assert captured["planning_meeting_record_root"] == (
            tmp_path / "logs/hitl/planning_discussions/resource_finder/resource-test"
        )
    else:
        assert captured["planning_meeting_owner"] is None
        assert captured["planning_meeting_record_root"] is None


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("phase", ["discussion", "plan", "execution", "review"])
def test_additive_autoresearch_prompt_preserves_discussion_boundary(phase, focused):
    prompt = PromptGenerator(ROOT / "templates").generate_resource_finder_prompt(
        IDEA,
        hitl_runtime_completion=True,
        hitl_phase=phase,
        invocation_mode="additive",
        objective="Resolve a missing piece of evidence.",
        focused_autoresearch=focused,
    )

    assert ("FOCUSED HITL AUTORESEARCH SCOPE" in prompt) is focused
    assert "FOCUSED MANAGED ORDINARY" not in prompt
    assert "{workspace_label}" not in prompt
    if phase == "discussion":
        assert "ADDITIVE INVOCATION — PLANNING CONSTRAINTS" in prompt
        assert "RESOURCE-FINDER DIRECTION LIMIT" in prompt
        assert "EXISTING WORKSPACE IS AUTHORITATIVE" not in prompt
    else:
        assert "established AutoResearch workspace" in prompt
        assert "ADDITIVE INVOCATION — PLANNING CONSTRAINTS" not in prompt
