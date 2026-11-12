from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.hitl_manager_context import HitlManagerTranscript
from core.hitl_manager_react import HitlManager
from core.hitl_mode import HitlMode
from core.hitl_paths import hitl_manager_dir
from core.hitl_runtime_state import HitlRuntimeState


def idea():
    return {
        "idea": {
            "title": "Task",
            "hypothesis": "A shortened task...",
            "background": {
                "description": "Investigate.\n" * 1000 + "Preserve the final required output."
            },
            "constraints": {"custom": "Keep this constraint"},
            "metadata": {"source_path": "/host/private/input.yaml"},
            "local_resources": {
                "datasets": [{"path": "datasets/local/data", "source_path": "/host/data"}]
            },
        }
    }


def manager(workspace, mode="full", tokens=300_000):
    value = HitlManager.__new__(HitlManager)
    value.runtime_state = HitlRuntimeState(workspace)
    value.work_dir = workspace
    value.world_model = SimpleNamespace(reconcile=lambda research: None)
    value.research = SimpleNamespace(
        digest_section=lambda: "Worker incorrectly says output is optional."
    )
    value.conversation = HitlManagerTranscript(hitl_manager_dir(workspace), context_tokens=tokens)
    value._current_hitl_mode = lambda: HitlMode(mode)
    value._runtime_tool_boundary_instruction = lambda tools: "Existing tool boundary"
    value._summarize = Mock(return_value="Earlier conversation summary")
    return value


def task_from(messages):
    message = next(m for m in messages if m["content"].startswith("User-provided research task"))
    assert message["role"] == "user"
    return yaml.safe_load(message["content"].split("\n\n", 1)[1])


def test_binding_preserves_full_task_and_caller(tmp_path):
    source = idea()
    original = deepcopy(source)
    state = HitlRuntimeState(tmp_path)
    bound = state.bind_task_context(source)
    assert source == original
    assert bound["idea"]["background"] == source["idea"]["background"]
    assert bound["idea"]["constraints"] == source["idea"]["constraints"]
    assert "source_path" not in bound["idea"]["metadata"]
    assert bound["idea"]["local_resources"]["datasets"] == [{"path": "datasets/local/data"}]
    bound["idea"]["title"] = "mutated returned copy"
    assert state.task_context()["idea"]["title"] == "Task"
    assert state.bind_task_context({"idea": {"title": "Candidate"}}) == state.task_context()
    assert HitlRuntimeState(tmp_path).task_context() == state.task_context()


def test_binding_preserves_yaml_dates_without_mutating_idea(tmp_path):
    source = yaml.safe_load("""
idea:
  constraints:
    deadline: 2026-11-09
    milestones:
      - at: 2026-11-09T12:30:00Z
        required: true
        count: 2
""")
    original = deepcopy(source)
    bound = HitlRuntimeState(tmp_path).bind_task_context(source)
    assert bound == original
    assert HitlRuntimeState(tmp_path).task_context() == bound
    assert source == original


def test_binding_rejects_unknown_objects(tmp_path):
    state = HitlRuntimeState(tmp_path)
    with pytest.raises(yaml.representer.RepresenterError):
        state.bind_task_context({"idea": {"constraints": {"custom": object()}}})
    assert HitlRuntimeState(tmp_path).task_context() is None


@pytest.mark.parametrize("custom_yaml", [
    "2026-11-09",
    "2026-11-09T12:30:00Z",
    "!!set {alpha: null, beta: null}",
    "!!binary aGVsbG8=",
    "{2026-11-09: due, 2: two, null: empty}",
    "[{tags: !!set {alpha: null}, payload: !!binary aGVsbG8=}]",
])
def test_valid_yaml_idea_initializes_hitl_and_survives_restart(tmp_path, monkeypatch, custom_yaml):
    from cli.hitl_launcher import initialize_manager_task
    from core.idea_manager import IdeaManager

    registry = tmp_path / "ideas"
    monkeypatch.setenv("NEURICO_IDEAS", str(registry))
    source = yaml.safe_load(
        "idea:\n  title: YAML context test\n  domain: machine_learning\n"
        "  hypothesis: A concrete hypothesis long enough for validation.\n"
        "  constraints:\n    custom: " + custom_yaml
    )
    ideas = IdeaManager(registry)
    assert ideas.validate_idea(source)["valid"]
    idea_id = ideas.submit_idea(source)
    submitted = deepcopy(ideas.get_idea(idea_id))
    work_dir = tmp_path / "workspace"
    initialize_manager_task(ROOT, idea_id, work_dir)
    state = HitlRuntimeState(work_dir)
    assert state.task_context() == submitted
    assert isinstance(json.loads(state.path.read_text())["task_context"], str)
    assert ideas.get_idea(idea_id) == submitted
    assert task_from(manager(work_dir)._messages(0, [])) == submitted
    # Initialization on reopen must retain the original binding.
    initialize_manager_task(ROOT, idea_id, work_dir)
    assert HitlRuntimeState(work_dir).task_context() == submitted
    returned = state.task_context()
    returned["idea"]["constraints"].clear()
    assert state.task_context() == submitted


def test_legacy_dictionary_context_remains_readable_and_preserved(tmp_path):
    state = HitlRuntimeState(tmp_path)
    legacy = {"idea": {"title": "Existing task", "constraints": {"deadline": "2026-11-09"}}}
    with state._locked():
        state._state["task_context"] = legacy
        state._save_unlocked()
    assert HitlRuntimeState(tmp_path).task_context() == legacy
    bound = state.bind_task_context({"idea": {"title": "Replacement"}})
    assert bound == legacy
    bound["idea"]["title"] = "Mutated copy"
    assert task_from(manager(tmp_path)._messages(0, [])) == legacy
    assert state.bind_task_context(legacy, prepare_run=True) == legacy
    assert isinstance(state.snapshot()["task_context"], str)


@pytest.mark.parametrize("mode", ["full", "auto"])
def test_manager_receives_task_outside_history_after_compaction_and_restart(tmp_path, mode):
    value = manager(tmp_path, mode, tokens=4000)
    source = idea()
    source["idea"]["constraints"] = yaml.safe_load(
        "deadline: 2026-11-09\ntags: !!set {alpha: null, beta: null}\npayload: !!binary aGVsbG8="
    )
    bound = value.runtime_state.bind_task_context(source)
    for i in range(16):
        value.conversation.append("human", f"Discussion {i}: " + "history " * 400)
    prepare = value.conversation.prepare
    value.conversation.prepare = Mock(wraps=prepare)
    messages = value._messages(0, [])
    assert task_from(messages) == bound
    assert value._summarize.called
    assert value.conversation.prepare.call_args.kwargs["fixed_context_tokens"] > 3000
    assert "Preserve the final required output" not in messages[-1]["content"]
    assert task_from(manager(tmp_path, mode)._messages(0, [])) == bound


def test_preparation_refreshes_but_preserves_held_review(tmp_path):
    state = HitlRuntimeState(tmp_path)
    state.bind_task_context({"idea": {"title": "Pre-start"}})
    prepared = state.bind_task_context(idea(), prepare_run=True)
    with state._locked():
        state._state["pending_worker_command"] = {"status": "pending"}
        state._save_unlocked()
    assert state.bind_task_context({"idea": {"title": "Changed"}}, prepare_run=True) == prepared


def test_legacy_manager_can_open_without_task(tmp_path):
    messages = manager(tmp_path)._messages(0, [])
    assert any("no saved user-provided task context" in m["content"] for m in messages)


@pytest.mark.parametrize("mode", ["full", "auto"])
@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize(
    "autoresearch,planning", [(False, "single"), (True, "single"), (True, "collaborative")]
)
def test_pipeline_binds_before_workers(tmp_path, monkeypatch, mode, focused, autoresearch, planning):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator
    from core.hitl_planning_mode import normalize_planning_mode_config

    owner = ResearchPipelineOrchestrator(
        tmp_path,
        managed_initial_run=True,
        hitl_autoresearch=autoresearch,
        focused_autoresearch=focused,
        hitl_mode=mode,
        planning_mode_config=normalize_planning_mode_config(planning),
    )
    observed = []

    def resource(**kwargs):
        observed.append(task_from(manager(tmp_path, mode)._messages(0, [])))
        return {"success": False, "hitl_terminal_failure": True}

    monkeypatch.setattr(owner, "_run_resource_finder_hitl", resource)
    owner.run_pipeline(idea(), hitl_enabled=True, scoring_enabled=autoresearch)
    assert observed == [HitlRuntimeState(tmp_path).task_context()]
    assert observed[0]["idea"]["background"] == idea()["idea"]["background"]


def test_unmanaged_pipeline_does_not_bind_task(tmp_path, monkeypatch):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    owner = ResearchPipelineOrchestrator(tmp_path)
    monkeypatch.setattr(owner, "_run_resource_finder", lambda **kwargs: {"success": False})
    owner.run_pipeline(idea())
    assert not (tmp_path / ".neurico/hitl/runtime.json").exists()


def test_baseline_binds_before_manifest_review(tmp_path, monkeypatch):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    owner = ResearchPipelineOrchestrator(tmp_path, baseline_construction=True)
    owner.state.state.update(workflow="ordinary", completed=True)
    observed = []

    def manifest():
        observed.append(task_from(manager(tmp_path)._messages(0, [])))
        return {"success": False}

    monkeypatch.setattr(owner, "_run_managed_baseline_manifest", manifest)
    owner.run_managed_baseline_construction(
        idea=idea(),
        provider="codex",
        full_permissions=True,
        manifest_trimmer_timeout=300,
        rule_maker_timeout=None,
        scorer_timeout=None,
    )
    assert observed[0]["idea"]["background"] == idea()["idea"]["background"]


@pytest.mark.parametrize("mode", ["full", "auto"])
@pytest.mark.parametrize("proposal_mode", ["single", "independent_ranked", "collaborative"])
def test_autoresearch_task_runtimes_share_original_task(tmp_path, mode, proposal_mode):
    from core.hitl import HitlRuntime
    from core.hitl_autoresearch import HitlAutoResearchController
    from core.hitl_proposal_round import normalize_proposal_mode_config, proposal_task_id

    mgr = manager(tmp_path, mode)
    owner_runtime = HitlRuntime(tmp_path, "experiment_runner", manager=mgr, hitl_mode=mode)
    counts = (
        {"proposer_count": 2, "reviewer_count": 2} if proposal_mode == "independent_ranked" else {}
    )
    owner = HitlAutoResearchController(
        idea(),
        "task",
        tmp_path,
        tmp_path / "history",
        proposal_generator=lambda **kw: {},
        scorer=lambda **kw: {},
        hitl_runtime=owner_runtime,
        hitl_mode=mode,
        proposal_mode_config=normalize_proposal_mode_config(proposal_mode, **counts),
    )
    if proposal_mode == "independent_ranked":
        child = owner._new_ranked_task_runtime(proposal_task_id(1, "proposer", 1))
    elif proposal_mode == "collaborative":
        from core.hitl_proposal_discussion import proposal_discussion_task_id

        child = owner._new_discussion_task_runtime(
            proposal_discussion_task_id("opening", participant_ordinal=1)
        )
    else:
        child = owner._proposal_hitl_runtime()
    assert child.manager is mgr
    assert task_from(child.manager._messages(0, [])) == owner._task_context
    assert owner._task_context["idea"]["background"] == idea()["idea"]["background"]


@pytest.mark.parametrize("workflow", ["ordinary", "autoresearch"])
def test_old_snapshot_rollback_restores_saved_binding_before_manager_reload(tmp_path, workflow):
    from core.hitl import HitlRuntime
    from core.hitl_autoresearch import HitlAutoResearchController
    from core.hitl_git_state import HitlGitStateStore
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    state = HitlRuntimeState(tmp_path)
    store = HitlGitStateStore(tmp_path)
    old_snapshot = store.create_rollback_snapshot()
    bound = state.bind_task_context(idea())
    changed = {"idea": {"title": "Newly loaded input must not replace saved review"}}
    mgr = SimpleNamespace(
        reload_after_runtime_restore=lambda: observed.append(state.task_context())
    )
    observed = []
    if workflow == "ordinary":
        owner = ResearchPipelineOrchestrator(tmp_path, managed_initial_run=True, hitl_manager=mgr)
        owner._bind_task_context(changed)
        runtime = owner._create_hitl_runtime("resource_finder")
    else:
        runtime = HitlRuntime(tmp_path, "experiment_runner", manager=mgr)
        owner = HitlAutoResearchController(
            changed,
            "task",
            tmp_path,
            tmp_path / "history",
            proposal_generator=lambda **kw: {},
            scorer=lambda **kw: {},
            hitl_runtime=runtime,
        )
    store.restore(old_snapshot)
    assert state.task_context() is None
    runtime.reload_manager_after_state_restore()
    assert observed == [bound]
    assert task_from(manager(tmp_path)._messages(0, [])) == bound


def test_prestart_initializer_does_not_refresh_saved_task(tmp_path, monkeypatch):
    from cli import hitl_launcher

    monkeypatch.setattr(
        hitl_launcher, "IdeaManager", lambda path: SimpleNamespace(get_idea=lambda id: idea())
    )
    monkeypatch.setattr(hitl_launcher, "resolve_ideas_dir", lambda path: path / "ideas")
    hitl_launcher.initialize_manager_task(tmp_path, "task", tmp_path)
    state = HitlRuntimeState(tmp_path)
    assert state.task_context()["idea"]["background"] == idea()["idea"]["background"]
    saved = state.bind_task_context({"idea": {"title": "Prepared"}}, prepare_run=True)
    hitl_launcher.initialize_manager_task(tmp_path, "task", tmp_path)
    assert state.task_context() == saved


def test_prestart_resource_paths_match_staging_without_exposing_host_paths(tmp_path, monkeypatch):
    from cli import hitl_launcher
    from core.local_resources import stage_local_resources

    host = tmp_path / "host"
    host.mkdir()
    dataset = host / "rows.csv"
    dataset.write_text("x\n1\n")
    function = host / "evaluate.py"
    function.write_text("def evaluate(): return 1\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    source = idea()
    source["idea"]["local_resources"] = {
        "datasets": [
            {"path": str(dataset), "name": "training"},
            {"path": str(dataset), "name": "training"},
        ],
        "functions": [{"path": str(function), "entrypoint": "evaluate"}],
    }
    source["idea"]["background"]["papers"] = [
        {"path": str(host / "ref.pdf"), "description": "Reference", "url": "https://example.org/ref"},
        {"path": "papers/relative.pdf"},
        {"path": str(work_dir / "papers/workspace.pdf")},
        {"path": "~/private/ref.pdf", "description": "Other reference"},
        {"path": "https://example.org/remote.pdf"},
    ]
    original = deepcopy(source)
    monkeypatch.setattr(
        hitl_launcher, "IdeaManager", lambda path: SimpleNamespace(get_idea=lambda id: source)
    )
    hitl_launcher.initialize_manager_task(tmp_path, "task", work_dir)
    bound = HitlRuntimeState(work_dir).task_context()
    messages = manager(work_dir)._messages(0, [])
    assert task_from(messages) == bound
    assert str(host) not in str(messages)
    assert "/host/private/input.yaml" not in str(messages)
    assert not (work_dir / "datasets").exists()
    assert not (work_dir / "code").exists()
    assert source == original
    assert bound["idea"]["background"]["papers"] == [
        {"description": "Reference", "url": "https://example.org/ref"},
        {"path": "papers/relative.pdf"},
        {"path": "papers/workspace.pdf"},
        {"description": "Other reference"},
        {"path": "https://example.org/remote.pdf"},
    ]
    staged = deepcopy(source)
    stage_local_resources(work_dir, staged)
    for kind in ("datasets", "functions"):
        assert [e["path"] for e in bound["idea"]["local_resources"][kind]] == [
            e["path"] for e in staged["idea"]["local_resources"][kind]
        ]


@pytest.mark.parametrize("workflow", ["ordinary", "autoresearch"])
def test_runner_supplies_prepared_task_before_starting_manager(tmp_path, monkeypatch, workflow):
    from contextlib import ExitStack
    from core.runner import ResearchRunner
    from core.hitl_run_control import HitlRunStopControl, activate_hitl_run_stop_control
    from core.hitl_lock import hitl_workspace_run_lease
    import core.hitl_manager_host as hosts

    source = idea()
    source["idea"]["local_resources"] = {}
    source["idea"]["constraints"].update(time_limit="old limit", time="old policy")
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.idea_manager = SimpleNamespace(
        get_idea=lambda id: deepcopy(source), update_status=lambda *a: None
    )
    runner.use_github = False
    runner._copy_workspace_resources = lambda *args, **kwargs: None
    observed = []

    class StopAtHostStart(Exception):
        pass

    class Host:
        def __init__(self, **kwargs):
            pass

        def start(self):
            observed.append(task_from(manager(tmp_path)._messages(0, [])))
            raise StopAtHostStart

    monkeypatch.setattr(hosts, "HitlManagerHost", Host)
    runner.project_root = tmp_path
    options = {"hitl_research" if workflow == "ordinary" else "hitl_autoresearch": "cli"}
    with ExitStack() as stack:
        stack.enter_context(
            hitl_workspace_run_lease(tmp_path, owner={"request_id": "test", "provider": "codex"})
        )
        stack.enter_context(activate_hitl_run_stop_control(HitlRunStopControl(tmp_path, "test")))
        with pytest.raises(StopAtHostStart):
            ResearchRunner.run_research.__wrapped__(
                runner,
                "task",
                provider="codex",
                hitl_work_dir=tmp_path,
                paper_style="neurips",
                write_paper=False,
                _hitl_host_scope=stack,
                **options,
            )
    bound = observed[0]["idea"]
    assert bound["background"] == source["idea"]["background"]
    assert ("time_limit" in bound["constraints"]) == (workflow == "ordinary")
    assert ("time" in bound["constraints"]) == (workflow == "ordinary")
