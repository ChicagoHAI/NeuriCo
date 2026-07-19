from pathlib import Path
import sys
import inspect
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import HitlIdeaLog, HitlValidationError
from core.autoresearch import (
    AutoResearchController,
    AutoResearchIterationResult,
    CheckpointManager,
    ScoreSummary,
)
from core.hitl_autoresearch import (
    HitlAutoResearchController,
    _initial_frontier_acceptance_reason,
    continue_hitl_autoresearch,
    run_fresh_hitl_autoresearch_initial_node,
)
from core.hitl_frontier import HitlFrontierStore


def test_ordinary_autoresearch_controller_has_no_hitl_mode_switch() -> None:
    """HITL AutoResearch is a separate controller, not an ordinary-mode flag."""
    parameters = inspect.signature(AutoResearchController).parameters
    assert "hitl_enabled" not in parameters
    assert "hitl_runtime" not in parameters


def test_frontier_records_accepted_exploration_and_rejected_attempt(tmp_path: Path) -> None:
    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha="root",
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    store.finalize_attempt(
        parent_node_sha="root",
        candidate_node_sha="explore",
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploration",
        objective_score={"results": {"score": 2}},
        accepted=True,
        reason="This is a structurally distinct direction worth retaining.",
        plan_text="exploration plan",
    )
    store.finalize_attempt(
        parent_node_sha="explore",
        candidate_node_sha="rejected",
        attempt_id="attempt_1",
        proposal_idea_id="I2",
        proposal_type="exploitation",
        objective_score={"results": {"score": 1.5}},
        accepted=False,
        reason="The attempted change did not improve the retained direction.",
        plan_text="unused rejected plan",
    )

    assert store.state() == {
        "selected_frontier_node_sha": "explore",
        "active_frontier_node_shas": ["root", "explore"],
    }
    root = store.node("root")
    assert root["attempt_history"][0]["proposal_idea_id"] == "I1"
    explore = store.node("explore")
    assert explore["attempt_history"][0]["accepted"] is False
    assert not store.paths.node_dir("rejected").exists()


def test_current_frontier_worker_view_includes_selected_node_identity(tmp_path: Path) -> None:
    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha="root",
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )

    current = store.current_for_worker()

    assert current["node_sha"] == "root"
    assert "plan" not in current


def test_frontier_retains_root_and_attempt_commits_with_private_git_refs(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["git", "config", "user.name", "NeuriCo Test"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "root"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    root = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    tracked.write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "candidate"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha=root,
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    store.finalize_attempt(
        parent_node_sha=root,
        candidate_node_sha=candidate,
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploration",
        objective_score={"results": {"score": 2}},
        accepted=True,
        reason="This is a distinct direction worth retaining.",
        plan_text="candidate plan",
    )

    assert subprocess.check_output(
        ["git", "rev-parse", "refs/neurico/hitl/frontiers/" + root], cwd=tmp_path, text=True
    ).strip() == root
    assert subprocess.check_output(
        ["git", "rev-parse", "refs/neurico/hitl/frontiers/" + candidate], cwd=tmp_path, text=True
    ).strip() == candidate
    assert subprocess.check_output(
        ["git", "rev-parse", f"refs/neurico/hitl/attempts/{root}-attempt_1"],
        cwd=tmp_path,
        text=True,
    ).strip() == candidate


def test_pruning_removes_only_active_membership_and_keeps_audit_node(tmp_path: Path) -> None:
    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha="root",
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    store.finalize_attempt(
        parent_node_sha="root",
        candidate_node_sha="explore",
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploration",
        objective_score={"results": {"score": 2}},
        accepted=True,
        reason="The distinct direction deserves retention.",
        plan_text="explore plan",
    )

    state = store.prune("root")

    assert state["active_frontier_node_shas"] == ["explore"]
    assert store.paths.node_json("root").is_file()
    with pytest.raises(Exception, match="final active frontier node"):
        store.prune("explore")


def test_public_frontier_audit_is_an_exact_nodes_tree_mirror(tmp_path: Path) -> None:
    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha="root",
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    store.finalize_attempt(
        parent_node_sha="root",
        candidate_node_sha="candidate",
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploration",
        objective_score={"results": {"score": 2}},
        accepted=True,
        reason="This is a distinct retained direction.",
        plan_text="candidate plan",
    )

    audit_nodes = tmp_path / "logs" / "experiment-autoresearch" / "nodes"
    store.mirror_nodes_to(audit_nodes)

    source_files = sorted(
        path.relative_to(store.paths.nodes)
        for path in store.paths.nodes.rglob("*")
        if path.is_file()
    )
    audit_files = sorted(
        path.relative_to(audit_nodes) for path in audit_nodes.rglob("*") if path.is_file()
    )
    assert audit_files == source_files
    for relative_path in source_files:
        assert (audit_nodes / relative_path).read_bytes() == (
            store.paths.nodes / relative_path
        ).read_bytes()


def test_accepted_exploitation_inherits_direction_attempt_history_without_copying_it(
    tmp_path: Path,
) -> None:
    store = HitlFrontierStore(tmp_path)
    store.initialize_root(
        node_sha="root",
        plan_text="root plan",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    store.finalize_attempt(
        parent_node_sha="root",
        candidate_node_sha="rejected",
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploitation",
        objective_score={"results": {"score": 0.9}},
        accepted=False,
        reason="The change did not improve the retained direction.",
        plan_text="unused rejected plan",
    )
    store.finalize_attempt(
        parent_node_sha="root",
        candidate_node_sha="replacement",
        attempt_id="attempt_2",
        proposal_idea_id="I2",
        proposal_type="exploitation",
        objective_score={"results": {"score": 1.1}},
        accepted=True,
        reason="The change improved the retained direction.",
        plan_text="replacement plan",
    )

    replacement = store.node("replacement")

    assert [attempt["proposal_idea_id"] for attempt in replacement["attempt_history"]] == [
        "I1",
        "I2",
    ]
    assert not (store.paths.node_dir("replacement") / "attempts").exists()


def test_non_evidence_ideas_require_finalized_premises(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    with pytest.raises(HitlValidationError, match="requires at least one finalized premise"):
        log.append(
            {
                "pipeline_stage": "experiment_runner",
                "hitl_stage": "proposal",
                "level": "C",
                "actor": "experiment_runner",
                "idea_type": "proposal",
                "proposal_type": "exploitation",
                "context": "The proposer submitted a candidate experiment.",
                "proposal": "# AutoResearch Proposal",
                "raised": False,
            }
        )

    evidence = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "context": "A public baseline scoring result is available.",
            "evidence": "The baseline result identifies one remaining bottleneck.",
            "raised": False,
        }
    )
    proposal = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "premises": [evidence["idea_id"]],
            "context": "The proposer submitted a candidate experiment.",
            "proposal": "# AutoResearch Proposal\n\n## Proposed modification\nTarget the bottleneck.",
            "raised": False,
        }
    )
    assert proposal["proposal_type"] == "exploitation"
    assert "basis" not in proposal


def test_agent_idea_view_hides_runtime_provenance(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    record = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "level": "C",
            "actor": "experiment_runner",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "context": "The completed evaluation exposed an error pattern.",
            "evidence": "The errors concentrate in one documented input class.",
            "raised": False,
            "parent_node_id": "runtime-parent-sha",
            "attempt_id": "runtime-attempt-id",
        }
    )

    text = log.render_for_agent(idea_id=record["idea_id"])

    assert "The errors concentrate" in text
    assert "runtime-parent-sha" not in text
    assert "runtime-attempt-id" not in text
    assert "parent_node_id" not in text
    assert "attempt_id" not in text


def test_initial_frontier_objective_score_reads_runtime_scorer_result(tmp_path: Path) -> None:
    work_dir = tmp_path
    (work_dir / "scoring").mkdir()
    (work_dir / "scoring" / "results.json").write_text(
        '{"overall_satisfied": true, "score": 0.81}',
        encoding="utf-8",
    )
    (work_dir / ".neurico").mkdir()
    (work_dir / ".neurico" / "pipeline_results.json").write_text(
        '{"stages": {"scorer": {"success": true, "elapsed_time": 4.2}}}',
        encoding="utf-8",
    )

    controller = HitlAutoResearchController.__new__(HitlAutoResearchController)
    controller.work_dir = work_dir

    assert controller._complete_objective_score() == {
        "scorer_result": {"success": True, "elapsed_time": 4.2},
        "results": {"overall_satisfied": True, "score": 0.81},
    }


def test_fresh_hitl_initial_node_uses_the_initial_checkpoint_as_the_frontier_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOrchestrator:
        def __init__(self, **_kwargs) -> None:
            pass

        def run_pipeline(self, **_kwargs):
            (tmp_path / "plans").mkdir()
            (tmp_path / "plans" / "experiment_runner_plan.md").write_text(
                "# Initial plan\n", encoding="utf-8"
            )
            (tmp_path / "scoring").mkdir()
            (tmp_path / "scoring" / "results.json").write_text(
                '{"overall_satisfied": true}', encoding="utf-8"
            )
            return {
                "success": True,
                "stages": {"scorer": {"success": True, "elapsed_time": 1.0}},
            }

    monkeypatch.setattr("core.pipeline_orchestrator.ResearchPipelineOrchestrator", FakeOrchestrator)

    result = run_fresh_hitl_autoresearch_initial_node(
        idea={"idea": {"title": "Test"}},
        work_dir=tmp_path,
        templates_dir=tmp_path,
        provider="claude",
        pause_after_resources=False,
        skip_resource_finder=False,
        resource_finder_timeout=1,
        experiment_runner_timeout=1,
        full_permissions=True,
        use_scribe=False,
        rule_maker_timeout=1,
        scorer_timeout=1,
        manifest_trimmer_timeout=1,
        autoresearch_history_dir=None,
    )

    assert result.success
    assert result.initial_sha == result.current_best_sha
    frontier = HitlFrontierStore(tmp_path)
    assert frontier.state()["selected_frontier_node_sha"] == result.initial_sha
    assert CheckpointManager(tmp_path).current_sha() == result.initial_sha


def test_initial_frontier_reason_uses_manager_score_review(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    premise = log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "execution",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "context": "The initial experiment produced a scoring result.",
            "evidence": "The runtime recorded a complete scoring output.",
            "premises": [],
            "raised": False,
        }
    )
    log.append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "evaluation_choice",
            "level": "B",
            "actor": "manager",
            "context": "The initial score is valid and the workspace is ready.",
            "premises": [premise["idea_id"]],
            "decision_needed": "Is the scored initial experiment ready to become the AutoResearch root node?",
            "options": ["Accept the error-free scored initial experiment as the root node."],
            "decision": "O1",
            "manager_feedback": "The initial evaluation completed without errors.",
            "raised": False,
        }
    )

    assert _initial_frontier_acceptance_reason(tmp_path) == (
        "The initial evaluation completed without errors."
    )


def test_hitl_controller_uses_saved_initial_checkpoint_without_creating_another(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("initial\n", encoding="utf-8")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "experiment_runner_plan.md").write_text(
        "# Initial plan\n", encoding="utf-8"
    )
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "results.json").write_text(
        '{"overall_satisfied": true}', encoding="utf-8"
    )
    checkpoints = CheckpointManager(tmp_path)
    initial = checkpoints.create_checkpoint("initial")
    controller = HitlAutoResearchController(
        idea={},
        idea_id="idea",
        work_dir=tmp_path,
        history_root=tmp_path / "history",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {"success": True},
        checkpoint_manager=checkpoints,
    )

    result = controller.run(iterations=0)

    assert result.initial_sha == initial.sha
    assert result.current_best_sha == initial.sha
    assert HitlFrontierStore(tmp_path).state()["selected_frontier_node_sha"] == initial.sha
    assert checkpoints.current_sha() == initial.sha


def test_hitl_continuation_restores_runtime_selected_frontier_node(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / "README.md").write_text("root\n", encoding="utf-8")
    (work_dir / "scoring").mkdir()
    (work_dir / "scoring" / "results.json").write_text(
        '{"properties": {"score": {"value": 0.5, "target": 0.0, "direction": "maximize", "satisfied": true}}}',
        encoding="utf-8",
    )
    (work_dir / "scoring" / "interface.md").write_text("# Interface\n", encoding="utf-8")
    (work_dir / "scoring" / "eval.py").write_text("# evaluator\n", encoding="utf-8")
    checkpoints = CheckpointManager(work_dir)
    root_sha = checkpoints.create_checkpoint("root").sha

    (work_dir / "README.md").write_text("explore\n", encoding="utf-8")
    selected_sha = checkpoints.create_checkpoint("selected frontier").sha

    frontier = HitlFrontierStore(work_dir)
    frontier.initialize_root(
        node_sha=root_sha,
        plan_text="root plan",
        objective_score={"results": {"score": 0.5}},
        reason_for_acceptance="Initial state completed without scoring error.",
    )
    frontier.finalize_attempt(
        parent_node_sha=root_sha,
        candidate_node_sha=selected_sha,
        attempt_id="attempt_1",
        proposal_idea_id="I1",
        proposal_type="exploration",
        objective_score={"results": {"score": 0.6}},
        accepted=True,
        reason="The distinct direction is worth retaining.",
        plan_text="selected plan",
    )
    frontier.configure_autoresearch_run(
        history_root=work_dir / "logs" / "experiment-autoresearch",
        lineage_source_sha=root_sha,
        last_iteration=2,
    )
    checkpoints.restore_checkpoint(root_sha, clean_untracked_public=True)

    result = continue_hitl_autoresearch(
        idea={"idea": {"title": "Test"}},
        idea_id="test",
        work_dir=work_dir,
        templates_dir=Path(__file__).resolve().parents[1] / "templates",
        provider="claude",
        full_permissions=True,
        scorer_timeout=1,
        iterations=0,
        autoresearch_history_dir=None,
        proposer_timeout=1,
        comment_timeout=1,
    )

    assert result["autoresearch"]["current_best_sha"] == selected_sha
    assert checkpoints.current_sha() == selected_sha
    assert not (work_dir / ".neurico" / "autoresearch_state.json").exists()


def test_hitl_run_does_not_select_frontier_after_its_final_scored_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text("root\n", encoding="utf-8")
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "results.json").write_text(
        '{"properties":{"score":{"value":1,"target":0,"direction":"maximize","satisfied":true}}}',
        encoding="utf-8",
    )
    checkpoints = CheckpointManager(tmp_path)
    root = checkpoints.create_checkpoint("root")
    (tmp_path / "README.md").write_text("candidate\n", encoding="utf-8")
    candidate = checkpoints.create_checkpoint("candidate")

    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=root.sha,
        plan_text="# Root plan\n",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )

    controller = HitlAutoResearchController(
        idea={},
        idea_id="idea",
        work_dir=tmp_path,
        history_root=tmp_path / "history",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {"success": True},
        checkpoint_manager=checkpoints,
    )
    scored = AutoResearchIterationResult(
        iteration=1,
        parent_sha=root.sha,
        child_sha=candidate.sha,
        attempt_dir=tmp_path / "history" / root.sha / "attempt_1",
        accepted=False,
        reason="The manager rejected the candidate but must choose the next active node.",
        proposal="proposal",
        comment_result={"success": True},
        scorer_result={"success": True},
        parent_summary=ScoreSummary(valid=True, source="parent"),
        candidate_summary=ScoreSummary(valid=True, source="candidate"),
    )
    selection_calls: list[bool] = []
    monkeypatch.setattr(controller, "run_iteration", lambda *_args: scored)
    monkeypatch.setattr(
        controller,
        "_select_frontier_before_next_proposal",
        lambda: selection_calls.append(True) or root.sha,
    )

    result = controller.run(1)

    assert selection_calls == []
    assert result.current_best_sha == root.sha
    assert result.iterations == [scored]


def test_hitl_run_selects_frontier_only_before_another_scored_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text("root\n", encoding="utf-8")
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "results.json").write_text(
        '{"properties":{"score":{"value":1,"target":0,"direction":"maximize","satisfied":true}}}',
        encoding="utf-8",
    )
    checkpoints = CheckpointManager(tmp_path)
    root = checkpoints.create_checkpoint("root")
    (tmp_path / "README.md").write_text("candidate\n", encoding="utf-8")
    candidate = checkpoints.create_checkpoint("candidate")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=root.sha,
        plan_text="# Root plan\n",
        objective_score={"results": {"score": 1}},
        reason_for_acceptance="Initial experiment completed without scoring error.",
    )
    controller = HitlAutoResearchController(
        idea={},
        idea_id="idea",
        work_dir=tmp_path,
        history_root=tmp_path / "history",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {"success": True},
        checkpoint_manager=checkpoints,
    )
    first = AutoResearchIterationResult(
        iteration=1,
        parent_sha=root.sha,
        child_sha=candidate.sha,
        attempt_dir=tmp_path / "history" / root.sha / "attempt_1",
        accepted=False,
        reason="The manager rejected the candidate.",
        proposal="proposal one",
        comment_result={"success": True},
        scorer_result={"success": True},
        parent_summary=ScoreSummary(valid=True, source="parent"),
        candidate_summary=ScoreSummary(valid=True, source="candidate"),
    )
    second = AutoResearchIterationResult(
        iteration=2,
        parent_sha=root.sha,
        child_sha=candidate.sha,
        attempt_dir=tmp_path / "history" / root.sha / "attempt_2",
        accepted=False,
        reason="The manager rejected the second candidate.",
        proposal="proposal two",
        comment_result={"success": True},
        scorer_result={"success": True},
        parent_summary=ScoreSummary(valid=True, source="parent"),
        candidate_summary=ScoreSummary(valid=True, source="candidate"),
    )
    results = iter([first, second])
    selection_calls: list[bool] = []
    monkeypatch.setattr(controller, "run_iteration", lambda *_args: next(results))
    monkeypatch.setattr(
        controller,
        "_select_frontier_before_next_proposal",
        lambda: selection_calls.append(True) or root.sha,
    )

    result = controller.run(2)

    assert selection_calls == [True]
    assert result.current_best_sha == root.sha
    assert result.iterations == [first, second]


def test_agent_idea_view_hides_raw_human_feedback(tmp_path: Path) -> None:
    log = HitlIdeaLog(tmp_path)
    premise = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "C",
            "actor": "resource_finder",
            "idea_type": "evidence",
            "idea_category": "dataset_property",
            "context": "Dataset A is available.",
            "evidence": "Dataset A covers the required domain.",
            "raised": False,
        }
    )
    record = log.append(
        {
            "pipeline_stage": "resource_finder",
            "hitl_stage": "execution",
            "level": "A",
            "actor": "human",
            "idea_type": "decision",
            "idea_category": "dataset_choice",
            "premises": [premise["idea_id"]],
            "context": "Dataset scope needs human direction.",
            "decision_needed": "Which dataset should be primary?",
            "options": ["Use Dataset A."],
            "decision": "O1",
            "human_feedback": "This exact raw human wording must remain internal.",
            "manager_feedback": "Use Dataset A as the primary dataset.",
            "raised": True,
        }
    )

    text = log.render_for_agent(idea_id=record["idea_id"])

    assert "Use Dataset A as the primary dataset." in text
    assert "This exact raw human wording must remain internal." not in text
