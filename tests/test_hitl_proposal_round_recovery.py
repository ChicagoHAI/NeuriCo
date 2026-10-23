from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.autoresearch import AttemptHistoryManager, CheckpointManager  # noqa: E402
from core.hitl import HitlIdeaLog, HitlRuntime, HitlValidationError  # noqa: E402
from core.hitl_autoresearch import (  # noqa: E402
    HitlAutoResearchController,
    _begin_hitl_autoresearch_attempt_state,
    _restore_prepared_checkpoint,
    recover_interrupted_hitl_attempt_if_needed,
)
from core.hitl_frontier import HitlFrontierStore  # noqa: E402
from core.hitl_git_state import HitlGitStateStore  # noqa: E402
from core.hitl_proposal_round import (  # noqa: E402
    ProposalModeConfig,
    aggregate_proposal_round_reviews,
    proposal_round_results,
)
from core.hitl_runtime_state import HitlRuntimeState  # noqa: E402
from core.hitl_run_control import HitlRunStopRequested  # noqa: E402
from core.hitl_whiteboard import (  # noqa: E402
    hitl_whiteboard_path,
    read_hitl_current_attempt_marker,
)
from core.hitl_workspace_guard import HitlWorkspaceWriteGuard  # noqa: E402


@pytest.fixture
def fake_hitl_tool_servers(monkeypatch):
    class FakeToolServer:
        next_port = 42000

        def __init__(self, _address, _handler):
            self.server_address = ("127.0.0.1", type(self).next_port)
            type(self).next_port += 1

        def serve_forever(self):
            return None

        def shutdown(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr("core.hitl.http.server.ThreadingHTTPServer", FakeToolServer)
    return FakeToolServer


def _base_idea(work_dir: Path) -> dict:
    return HitlIdeaLog(work_dir).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "evidence",
            "idea_category": "experiment_result",
            "level": "C",
            "actor": "experiment_runner",
            "premises": [],
            "context": "The selected parent has a finalized baseline result.",
            "related_artifacts": [],
            "evidence": "The baseline is available for proposal recovery tests.",
            "raised": False,
        }
    )


def _resolved_preparation(
    work_dir: Path,
    *,
    parent_sha: str,
    preparation_attempt_id: str,
    proposal_base_sha: str,
) -> HitlRuntimeState:
    state = HitlRuntimeState(work_dir)
    scope = state.workspace_guard_scope()
    state.begin_next_autoresearch_action(
        {
            "kind": "prepare_proposal",
            "parent_node_sha": parent_sha,
            "attempt_id": preparation_attempt_id,
            "additional_agent_ordinal": 1,
            "workspace_fingerprint": HitlWorkspaceWriteGuard.public_fingerprint(
                work_dir,
                scope=scope,
            ),
            "workspace_fingerprint_scope": scope,
            "proposal_base_sha": proposal_base_sha,
        }
    )
    state.record_next_autoresearch_action_decision(
        "prepare_proposal",
        {"choice": "proceed"},
    )
    state.complete_next_autoresearch_action(
        "prepare_proposal",
        {"choice": "proceed", "proposal_base_sha": proposal_base_sha},
    )
    return state


def _durable_ranked_attempt(
    work_dir: Path,
    *,
    proposal_base_sha: str | None = None,
):
    (work_dir / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    checkpoint = CheckpointManager(work_dir).create_checkpoint("ranked recovery root")
    frontier = HitlFrontierStore(work_dir)
    frontier.initialize_root(
        node_sha=checkpoint.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )
    history_root = work_dir / "logs" / "experiment-autoresearch"
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=checkpoint.sha,
        last_iteration=0,
    )
    whiteboard = hitl_whiteboard_path(work_dir)
    whiteboard.parent.mkdir(parents=True, exist_ok=True)
    whiteboard.write_text('{"tips": []}\n', encoding="utf-8")
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(
        checkpoint.sha
    )
    state = _resolved_preparation(
        work_dir,
        parent_sha=checkpoint.sha,
        preparation_attempt_id="attempt_3",
        proposal_base_sha=proposal_base_sha or checkpoint.sha,
    )
    marker = _begin_hitl_autoresearch_attempt_state(work_dir, attempt_dir)
    round_state = state.begin_proposal_round(
        parent_node_sha=checkpoint.sha,
        preparation_attempt_id="attempt_3",
        candidate_attempt_id=attempt_dir.name,
        workspace_fingerprint=HitlWorkspaceWriteGuard.public_fingerprint(work_dir),
        base_idea_number=0,
        proposer_count=2,
        reviewer_count=2,
    )
    return checkpoint, state, attempt_dir, marker, round_state, whiteboard


def test_ranked_recovery_accepts_distinct_preparation_and_candidate_attempts(tmp_path):
    checkpoint, _state, attempt_dir, marker, _round, _whiteboard = (
        _durable_ranked_attempt(tmp_path)
    )

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "proposal_preparation_transition"
    assert recovered.restored_checkpoint_sha == checkpoint.sha
    assert recovered.removed_attempt_dir == attempt_dir
    assert recovered.preparation_action["attempt_id"] == "attempt_3"
    assert recovered.preparation_action["proposal_round"]["candidate_attempt_id"] == (
        attempt_dir.name
    )
    assert read_hitl_current_attempt_marker(tmp_path) == marker


def test_ranked_recovery_rejects_changed_frozen_whiteboard_without_mutating_from_log(
    tmp_path,
):
    checkpoint, state, _attempt_dir, marker, _round, whiteboard = (
        _durable_ranked_attempt(tmp_path)
    )
    store = HitlGitStateStore(tmp_path)
    assert store.hitl_autoresearch_whiteboard_matches_attempt_boundary(marker)
    whiteboard.write_text('{"tips": [{"id": "T1"}]}\n', encoding="utf-8")
    assert not store.hitl_autoresearch_whiteboard_matches_attempt_boundary(marker)

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "complete"
    assert CheckpointManager(tmp_path).current_sha() == checkpoint.sha
    assert read_hitl_current_attempt_marker(tmp_path) == ""
    assert "proposal_round" not in state.snapshot()["next_autoresearch_action"]


def test_ranked_recovery_rolls_back_changed_public_workspace(tmp_path):
    checkpoint, _state, _attempt_dir, _marker, _round, _whiteboard = (
        _durable_ranked_attempt(tmp_path)
    )
    (tmp_path / "baseline.txt").write_text("unauthorized change\n", encoding="utf-8")

    recovered = recover_interrupted_hitl_attempt_if_needed(tmp_path)

    assert recovered is not None
    assert recovered.recovery_classification == "complete"
    assert CheckpointManager(tmp_path).current_sha() == checkpoint.sha
    assert (tmp_path / "baseline.txt").read_text(encoding="utf-8") == "baseline\n"


def test_ranked_recovery_fails_closed_for_missing_prepared_checkpoint(tmp_path):
    _durable_ranked_attempt(tmp_path, proposal_base_sha="f" * 40)

    with pytest.raises(RuntimeError, match="missing prepared workspace checkpoint"):
        recover_interrupted_hitl_attempt_if_needed(tmp_path)


def test_ranked_round_binds_live_fingerprint_after_prepared_restore(
    tmp_path,
    fake_hitl_tool_servers,
):
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("baseline\n", encoding="utf-8")
    checkpoint = CheckpointManager(tmp_path).create_checkpoint("ranked restored root")
    frontier = HitlFrontierStore(tmp_path)
    frontier.initialize_root(
        node_sha=checkpoint.sha,
        plan_text="plan\n",
        objective_score={"results": {}},
        reason_for_acceptance="root",
    )
    history_root = tmp_path / "logs" / "experiment-autoresearch"
    frontier.configure_autoresearch_run(
        history_root=history_root,
        lineage_source_sha=checkpoint.sha,
        last_iteration=0,
    )
    whiteboard = hitl_whiteboard_path(tmp_path)
    whiteboard.parent.mkdir(parents=True, exist_ok=True)
    whiteboard.write_text('{"tips": []}\n', encoding="utf-8")
    attempt_dir = AttemptHistoryManager(history_root, "idea").next_attempt_dir(
        checkpoint.sha
    )
    state = _resolved_preparation(
        tmp_path,
        parent_sha=checkpoint.sha,
        preparation_attempt_id="attempt_3",
        proposal_base_sha=checkpoint.sha,
    )
    preparation_fingerprint = state.snapshot()["next_autoresearch_action"][
        "workspace_fingerprint"
    ]

    baseline.write_text("temporary change\n", encoding="utf-8")
    assert _restore_prepared_checkpoint(
        tmp_path,
        parent_sha=checkpoint.sha,
        prepared_sha=checkpoint.sha,
    ) == checkpoint.sha
    assert baseline.read_text(encoding="utf-8") == "baseline\n"
    _begin_hitl_autoresearch_attempt_state(tmp_path, attempt_dir)
    runtime = HitlRuntime(
        tmp_path,
        "experiment_runner",
        channel=object(),
        manager=object(),
        use_hitl_autoresearch_whiteboard=True,
    )
    controller = HitlAutoResearchController(
        idea={"idea": {"title": "Ranked restored boundary"}},
        idea_id="idea",
        work_dir=tmp_path,
        history_root=history_root,
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {},
        checkpoint_manager=object(),
        history_manager=object(),
        hitl_runtime=runtime,
        proposal_mode_config=ProposalModeConfig(
            mode="independent_ranked",
            proposer_count=2,
            reviewer_count=2,
        ),
    )
    restored_fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(
        tmp_path,
        scope=state.workspace_guard_scope(),
    )
    assert restored_fingerprint != preparation_fingerprint

    round_state = controller._begin_or_resume_ranked_proposal_round(
        parent_sha=checkpoint.sha,
        attempt_dir=attempt_dir,
    )

    assert round_state["stage"] == "proposing"
    action = state.snapshot()["next_autoresearch_action"]
    assert action["workspace_fingerprint"] == restored_fingerprint
    assert action["workspace_fingerprint"] != preparation_fingerprint
    assert controller._capture_ranked_proposal_boundary(
        parent_sha=checkpoint.sha,
        preparation_attempt_id="attempt_3",
    )()["valid"] is True

    baseline.write_text("late mutation\n", encoding="utf-8")
    resumed = controller._begin_or_resume_ranked_proposal_round(
        parent_sha=checkpoint.sha,
        attempt_dir=attempt_dir,
    )
    assert resumed == round_state
    assert state.snapshot()["next_autoresearch_action"][
        "workspace_fingerprint"
    ] == restored_fingerprint
    with pytest.raises(
        RuntimeError,
        match="workspace no longer matches its approved boundary",
    ):
        controller._capture_ranked_proposal_boundary(
            parent_sha=checkpoint.sha,
            preparation_attempt_id="attempt_3",
        )


class _SelectionManager:
    def __init__(self, state: HitlRuntimeState):
        self.state = state
        self.calls = 0

    def begin_proposal_selection(
        self,
        _prompt,
        *,
        boundary_validator,
        on_decision,
        **identity,
    ):
        self.calls += 1
        assert boundary_validator()["valid"] is True
        current = self.state.proposal_round_snapshot(**identity)
        if current.get("selection") is None:
            self.state.record_proposal_selection_choice(
                **identity,
                choice="select",
                proposal_idea_id=current["tasks"]["r1-p1"]["result_idea_id"],
                reason="Candidate one has the strongest expected research value.",
            )
            current = self.state.proposal_round_snapshot(**identity)
        return on_decision(dict(current["selection"]))


def _serial_controller(work_dir: Path):
    attempt_dir = work_dir / "logs/experiment-autoresearch/parent/attempt_4"
    attempt_dir.mkdir(parents=True)
    whiteboard = hitl_whiteboard_path(work_dir)
    whiteboard.parent.mkdir(parents=True, exist_ok=True)
    whiteboard.write_text('{"tips": []}\n', encoding="utf-8")
    base = _base_idea(work_dir)
    state = _resolved_preparation(
        work_dir,
        parent_sha="parent",
        preparation_attempt_id="attempt_3",
        proposal_base_sha="prepared",
    )
    manager = _SelectionManager(state)
    runtime = HitlRuntime(
        work_dir,
        "experiment_runner",
        channel=object(),
        manager=manager,
        use_hitl_autoresearch_whiteboard=True,
    )
    controller = HitlAutoResearchController(
        idea={"idea": {"title": "Ranked recovery"}},
        idea_id="idea",
        work_dir=work_dir,
        history_root=work_dir / "logs/experiment-autoresearch",
        proposal_generator=lambda *_args, **_kwargs: {},
        scorer=lambda *_args, **_kwargs: {},
        checkpoint_manager=object(),
        history_manager=object(),
        hitl_runtime=runtime,
        proposal_mode_config=ProposalModeConfig(
            mode="independent_ranked",
            proposer_count=2,
            reviewer_count=2,
        ),
    )
    round_state = state.begin_proposal_round(
        parent_node_sha="parent",
        preparation_attempt_id="attempt_3",
        candidate_attempt_id="attempt_4",
        workspace_fingerprint=HitlWorkspaceWriteGuard.public_fingerprint(work_dir),
        base_idea_number=1,
        proposer_count=2,
        reviewer_count=2,
    )
    identity = {
        "parent_node_sha": "parent",
        "preparation_attempt_id": "attempt_3",
        "candidate_attempt_id": "attempt_4",
        "round_ordinal": 1,
    }
    return controller, state, manager, attempt_dir, base, round_state, identity


def _finish_task(controller, state, identity, base, *, role: str, task_id: str):
    round_state = state.proposal_round_snapshot(**identity)
    runtime, _pairs = controller._prepare_ranked_task_runtime(
        task_id=task_id,
        role=role,
        round_state=round_state,
        parent_sha="parent",
        preparation_attempt_id="attempt_3",
        candidate_attempt_id="attempt_4",
        boundary_validator=lambda: {"valid": True, "issues": []},
    )
    try:
        if role == "proposer":
            payload = {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": f"Run the controlled experiment from {task_id}.",
            }
        elif role == "verifier":
            payload = {
                "premises": [base["idea_id"]],
                "assessment": f"{task_id} finds the proposal attributable and feasible.",
            }
        else:
            candidates = proposal_round_results(round_state)["candidate_ids"]
            payload = {
                "ranking": candidates,
                "premises": [base["idea_id"]],
                "assessment": f"{task_id} ranks the complete candidate set.",
            }
        return runtime.finish_ranked_proposal_task(payload)
    finally:
        runtime.clear_idea_tool_context()


def _seed_stage(controller, state, identity, base, target: str):
    if target == "pending_finalization":
        state.begin_proposal_task_finalization(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            normalized_output={
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": "Replay this state-owned proposal finalization.",
            },
        )
        return

    for ordinal in range(1, 3):
        _finish_task(
            controller,
            state,
            identity,
            base,
            role="proposer",
            task_id=f"r1-p{ordinal}",
        )
    state.advance_proposal_round(**identity, expected_stage="proposing")
    if target == "verifying":
        return

    for ordinal in range(1, 3):
        _finish_task(
            controller,
            state,
            identity,
            base,
            role="verifier",
            task_id=f"r1-v{ordinal}",
        )
    state.advance_proposal_round(**identity, expected_stage="verifying")
    if target == "reviewing":
        return

    for ordinal in range(1, 3):
        _finish_task(
            controller,
            state,
            identity,
            base,
            role="reviewer",
            task_id=f"r1-r{ordinal}",
        )
    round_state = state.advance_proposal_round(**identity, expected_stage="reviewing")
    state.record_proposal_selection_choice(
        **identity,
        choice="select",
        proposal_idea_id=round_state["tasks"]["r1-p1"]["result_idea_id"],
        reason="Candidate one has the strongest expected research value.",
    )
    if target == "manager_choice":
        return
    aggregate = aggregate_proposal_round_reviews(
        state.proposal_round_snapshot(**identity),
        HitlIdeaLog(controller.work_dir).records(),
    )
    controller._apply_ranked_proposal_selection(
        identity=identity,
        aggregate=aggregate,
        selection=state.proposal_round_snapshot(**identity)["selection"],
    )


@pytest.mark.parametrize(
    ("start", "expected_launches", "expected_manager_calls"),
    [
        ("pending_finalization", ["r1-p2", "r1-v1", "r1-v2", "r1-r1", "r1-r2"], 1),
        ("verifying", ["r1-v1", "r1-v2", "r1-r1", "r1-r2"], 1),
        ("reviewing", ["r1-r1", "r1-r2"], 1),
        ("manager_choice", [], 1),
        ("selected", [], 0),
    ],
)
def test_parallel_ranked_round_resumes_each_durable_stage_without_relaunching_completed_tasks(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
    start,
    expected_launches,
    expected_manager_calls,
):
    controller, state, manager, attempt_dir, base, _round, identity = _serial_controller(
        tmp_path
    )
    _seed_stage(controller, state, identity, base, start)
    task_runtimes = {}
    launches = []
    original_factory = controller._new_ranked_task_runtime

    def tracked_runtime(task_id):
        runtime = original_factory(task_id)
        task_runtimes[task_id] = runtime
        return runtime

    def proposal_generator(*_args, **kwargs):
        task_id = kwargs["output_prefix"]
        runtime = task_runtimes[task_id]
        launches.append(task_id)
        runtime.finish_ranked_proposal_task(
            {
                "proposal_type": "exploitation",
                "premises": [base["idea_id"]],
                "proposal": f"Recovered proposal from {runtime.tool_scope}.",
            }
        )
        return {
            "success": True,
            "return_code": 0,
            "timed_out": False,
            "stopped": False,
            "background_processes_terminated": False,
            "provider_process_failed": False,
        }

    def assessment_runner(**request):
        task_id = request["output_prefix"]
        runtime = task_runtimes[task_id]
        launches.append(task_id)
        if request["role"] == "verifier":
            payload = {
                "premises": [base["idea_id"]],
                "assessment": "The recovered proposal is attributable and feasible.",
            }
        else:
            current = state.proposal_round_snapshot(**identity)
            payload = {
                "ranking": proposal_round_results(current)["candidate_ids"],
                "premises": [base["idea_id"]],
                "assessment": "The recovered ranking compares every candidate.",
            }
        runtime.finish_ranked_proposal_task(payload)
        return {
            "success": True,
            "return_code": 0,
            "timed_out": False,
            "stopped": False,
            "background_processes_terminated": False,
            "provider_process_failed": False,
        }

    monkeypatch.setattr(controller, "_new_ranked_task_runtime", tracked_runtime)
    controller.proposal_generator = proposal_generator
    controller.proposal_assessment_runner = assessment_runner

    round_state, _aggregate = controller._run_independent_ranked_proposal_round(
        parent_sha="parent",
        attempt_dir=attempt_dir,
        attempt_history=[],
        boundary_validator=lambda: {"valid": True, "issues": []},
    )

    assert round_state["stage"] == "selected"
    assert sorted(launches) == sorted(expected_launches)
    assert manager.calls == expected_manager_calls
    terminal_records = [
        record
        for record in HitlIdeaLog(tmp_path).records()
        if record.get("proposal_task_id")
        and (
            record.get("idea_type") == "proposal"
            or record.get("idea_category")
            in {"proposal_verification", "proposal_review"}
        )
    ]
    assert len(terminal_records) == 6


def test_ranked_recovery_rejects_unreferenced_terminal_idea_before_agent_launch(
    tmp_path,
    fake_hitl_tool_servers,
):
    controller, state, _manager, attempt_dir, base, _round, _identity = (
        _serial_controller(tmp_path)
    )
    HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "level": "C",
            "actor": "autoresearch_proposer",
            "parent_node_id": "parent",
            "attempt_id": "attempt_4",
            "proposal_task_id": "r1-p1",
            "premises": [base["idea_id"]],
            "context": "Orphaned recovery candidate.",
            "related_artifacts": [],
            "proposal": "This log record is not owned by task state.",
            "raised": False,
        }
    )

    with pytest.raises(HitlValidationError, match="unreferenced terminal idea"):
        controller._run_independent_ranked_proposal_round(
            parent_sha="parent",
            attempt_dir=attempt_dir,
            attempt_history=[],
            boundary_validator=lambda: {"valid": True, "issues": []},
        )

    assert state.snapshot()["next_autoresearch_action"]["proposal_round"]["tasks"][
        "r1-p1"
    ]["result_idea_id"] is None


def test_ranked_recovery_preserves_task_provider_failure_count(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    controller, state, _manager, attempt_dir, _base, _round, identity = (
        _serial_controller(tmp_path)
    )
    for _ in range(2):
        state.record_proposal_task_provider_result(
            **identity,
            proposal_task_id="r1-p1",
            role="proposer",
            failed=True,
        )
    launches = []
    first_failure_returned = threading.Event()

    def failed_generator(*_args, **kwargs):
        task_id = kwargs["output_prefix"]
        launches.append(task_id)
        if task_id == "r1-p1":
            first_failure_returned.set()
            return {
                "success": False,
                "return_code": 1,
                "timed_out": False,
                "stopped": False,
                "background_processes_terminated": False,
                "provider_process_failed": True,
            }
        first_failure_returned.wait(timeout=2)
        return {
            "success": False,
            "return_code": None,
            "timed_out": False,
            "stopped": True,
            "background_processes_terminated": False,
            "provider_process_failed": False,
        }

    controller.proposal_generator = failed_generator

    with pytest.raises(HitlRunStopRequested, match="stop requested|three consecutive provider"):
        controller._run_independent_ranked_proposal_round(
            parent_sha="parent",
            attempt_dir=attempt_dir,
            attempt_history=[],
            boundary_validator=lambda: {"valid": True, "issues": []},
        )

    assert launches.count("r1-p1") == 1
    assert launches.count("r1-p2") <= 1
    assert state.proposal_round_snapshot(**identity)["tasks"]["r1-p1"][
        "consecutive_provider_failures"
    ] == 3


def test_ranked_recovery_rejects_state_reference_with_wrong_task_provenance(
    tmp_path,
    fake_hitl_tool_servers,
):
    controller, state, _manager, attempt_dir, base, _round, identity = (
        _serial_controller(tmp_path)
    )
    wrong = HitlIdeaLog(tmp_path).append(
        {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "proposal",
            "idea_type": "proposal",
            "proposal_type": "exploitation",
            "level": "C",
            "actor": "autoresearch_proposer",
            "parent_node_id": "wrong-parent",
            "attempt_id": "attempt_4",
            "proposal_task_id": "r1-p1",
            "premises": [base["idea_id"]],
            "context": "Mismatched recovery candidate.",
            "related_artifacts": [],
            "proposal": "This record belongs to different provenance.",
            "raised": False,
        }
    )
    output = {
        "proposal_type": "exploitation",
        "premises": [base["idea_id"]],
        "proposal": "This record belongs to different provenance.",
    }
    state.begin_proposal_task_finalization(
        **identity,
        proposal_task_id="r1-p1",
        role="proposer",
        normalized_output=output,
    )
    state.complete_proposal_task_finalization(
        **identity,
        proposal_task_id="r1-p1",
        role="proposer",
        normalized_output=output,
        result_idea_id=wrong["idea_id"],
    )

    with pytest.raises(HitlValidationError, match="mismatched provenance"):
        controller._run_independent_ranked_proposal_round(
            parent_sha="parent",
            attempt_dir=attempt_dir,
            attempt_history=[],
            boundary_validator=lambda: {"valid": True, "issues": []},
        )


def test_serial_and_parallel_scheduling_produce_the_same_ranked_round_semantics(
    tmp_path,
    monkeypatch,
    fake_hitl_tool_servers,
):
    del fake_hitl_tool_servers

    def run_round(work_dir):
        controller, state, _manager, attempt_dir, base, _round, identity = (
            _serial_controller(work_dir)
        )
        task_runtimes = {}
        original_factory = controller._new_ranked_task_runtime

        def tracked_runtime(task_id):
            runtime = original_factory(task_id)
            task_runtimes[task_id] = runtime
            return runtime

        def proposal_generator(*_args, **kwargs):
            task_id = kwargs["output_prefix"]
            task_runtimes[task_id].finish_ranked_proposal_task(
                {
                    "proposal_type": "exploitation",
                    "premises": [base["idea_id"]],
                    "proposal": f"Run the controlled experiment proposed by {task_id}.",
                }
            )
            return {
                "success": True,
                "return_code": 0,
                "timed_out": False,
                "stopped": False,
                "background_processes_terminated": False,
                "provider_process_failed": False,
            }

        def assessment_runner(**request):
            task_id = request["output_prefix"]
            runtime = task_runtimes[task_id]
            if request["role"] == "verifier":
                payload = {
                    "premises": [base["idea_id"]],
                    "assessment": f"{task_id} finds the proposal attributable and feasible.",
                }
            else:
                candidates = proposal_round_results(
                    state.proposal_round_snapshot(**identity)
                )["candidate_ids"]
                payload = {
                    "ranking": candidates,
                    "premises": [base["idea_id"]],
                    "assessment": f"{task_id} ranks the complete candidate set.",
                }
            runtime.finish_ranked_proposal_task(payload)
            return {
                "success": True,
                "return_code": 0,
                "timed_out": False,
                "stopped": False,
                "background_processes_terminated": False,
                "provider_process_failed": False,
            }

        monkeypatch.setattr(controller, "_new_ranked_task_runtime", tracked_runtime)
        controller.proposal_generator = proposal_generator
        controller.proposal_assessment_runner = assessment_runner
        round_state, aggregate = controller._run_independent_ranked_proposal_round(
            parent_sha="parent",
            attempt_dir=attempt_dir,
            attempt_history=[],
            boundary_validator=lambda: {"valid": True, "issues": []},
        )
        result_to_task = {
            task["result_idea_id"]: task_id
            for task_id, task in round_state["tasks"].items()
        }
        selected_task = result_to_task[round_state["selection"]["proposal_idea_id"]]
        return {
            "stage": round_state["stage"],
            "task_roles": {
                task_id: task["role"] for task_id, task in round_state["tasks"].items()
            },
            "verifier_assignments": {
                task_id: result_to_task[task["assigned_proposal_idea_id"]]
                for task_id, task in round_state["tasks"].items()
                if task["role"] == "verifier"
            },
            "optimal_rankings": [
                [result_to_task[candidate_id] for candidate_id in ranking]
                for ranking in aggregate.optimal_rankings
            ],
            "selected_task": selected_task,
            "global_worker_state": (
                state.snapshot()["pending_worker_command"],
                state.snapshot()["worker_continuation"],
            ),
        }

    def serial_stage(task_ids, run_task):
        cancel_event = threading.Event()
        return {task_id: run_task(task_id, cancel_event) for task_id in task_ids}

    with monkeypatch.context() as serial_patch:
        serial_patch.setattr(
            "core.hitl_proposal_round.run_parallel_proposal_stage",
            serial_stage,
        )
        serial_result = run_round(tmp_path / "serial")
    parallel_result = run_round(tmp_path / "parallel")

    assert serial_result == parallel_result
