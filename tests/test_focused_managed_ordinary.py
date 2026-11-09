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


def test_focused_ordinary_experiment_prompts_are_solution_oriented_and_unscored(tmp_path):
    orchestrator = _ordinary(tmp_path, True)

    prompts = {
        phase: orchestrator._hitl_experiment_runner_source_prompt(
            idea=IDEA,
            provider="codex",
            use_scribe=False,
            scoring_enabled=False,
            hitl_phase=phase,
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
    for prompt in prompts.values():
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
    ordinary_prompt = _ordinary(tmp_path / "ordinary", False)._hitl_experiment_runner_source_prompt(
        idea=IDEA,
        provider="codex",
        use_scribe=False,
        scoring_enabled=False,
        hitl_phase="execution",
    )

    assert "FOCUSED HITL AUTORESEARCH SCOPE" in autoresearch_prompt
    assert "selected direction" in autoresearch_prompt.lower()
    assert "FOCUSED MANAGED ORDINARY RESEARCH" not in autoresearch_prompt
    assert "FOCUSED MANAGED ORDINARY RESEARCH" not in ordinary_prompt
    assert "DIRECTION BUDGET" in ordinary_prompt


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


def test_manager_phase_review_receives_focused_ordinary_context(tmp_path):
    _ordinary(tmp_path, True)
    manager = HitlManager.__new__(HitlManager)
    manager.work_dir = tmp_path
    manager.request_worker_resolution = lambda **kwargs: kwargs["prompt"]

    prompt = manager.review_phase_finish(
        pipeline_stage="experiment_runner",
        hitl_stage="plan",
        plan_text="Plan",
        finish_summary="Ready",
        related_artifacts=[],
        request_key="request-key",
        requires_human_approval=False,
        hitl_mode="auto",
    )

    assert "deliver the best solution\npossible" in prompt
    assert "Do not\nrequire novelty, competing implementations" in prompt
    assert "AutoResearch candidate" not in prompt


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
