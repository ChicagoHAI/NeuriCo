"""Unit tests for continue-research mode (idea.continuation + sealed staging).

Covers the schema/validation layer for continuation ideas (source_repo, goal,
invariants of kind protected_path / check / statement) and the sealed staging
branch that places sealed: true datasets under data/.test/ where the existing
sealed-groundtruth machinery hides them.

Run: python -m pytest tests/test_continuation.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    SEALED_STAGING_DIR,
    stage_local_resources,
    validate_continuation,
)


def _idea(**overrides):
    idea = {
        'title': 'A sufficiently long test title',
        'domain': 'machine_learning',
        'hypothesis': 'A sufficiently long test hypothesis for validation',
    }
    idea.update(overrides)
    return idea


def _continuation(**overrides):
    continuation = {
        'source_repo': 'https://github.com/user/project',
        'goal': 'Reduce inference latency without hurting F1',
    }
    continuation.update(overrides)
    return continuation


# ---------------------------------------------------------------- continuation

def test_idea_without_continuation_passes():
    errors, warnings = validate_continuation(_idea())
    assert errors == [] and warnings == []


def test_valid_continuation_passes():
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'},
        {'kind': 'check', 'command': 'pytest tests/', 'reason': 'tests must pass'},
        {'kind': 'statement', 'text': 'keep ONNX exportable', 'reason': 'deploy target'},
    ]))
    errors, warnings = validate_continuation(idea)
    assert errors == [] and warnings == []


def test_missing_source_repo_is_error():
    idea = _idea(continuation={'goal': 'Reduce inference latency without hurting F1'})
    errors, _ = validate_continuation(idea)
    assert any('source_repo' in e for e in errors)


def test_missing_goal_is_error():
    idea = _idea(continuation={'source_repo': '/repo'})
    errors, _ = validate_continuation(idea)
    assert any('goal' in e for e in errors)


def test_short_goal_is_warning():
    idea = _idea(continuation=_continuation(goal='faster'))
    errors, warnings = validate_continuation(idea)
    assert errors == []
    assert any('goal' in w for w in warnings)


def test_unknown_invariant_kind_is_error():
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'promise', 'text': 'be nice'}]))
    errors, _ = validate_continuation(idea)
    assert any("unknown kind 'promise'" in e for e in errors)


def test_invariant_missing_kind_field_is_error():
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'check', 'reason': 'tests'}]))
    errors, _ = validate_continuation(idea)
    assert any("requires 'command'" in e for e in errors)


def test_absolute_protected_path_is_warning():
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'protected_path', 'path': '/etc/passwd', 'reason': 'why not'}]))
    errors, warnings = validate_continuation(idea)
    assert errors == []
    assert any('workspace-relative' in w for w in warnings)


def test_invariant_without_reason_is_warning():
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'check', 'command': 'pytest tests/'}]))
    errors, warnings = validate_continuation(idea)
    assert errors == []
    assert any('reason' in w for w in warnings)


def test_validate_idea_surfaces_continuation_errors():
    from core.idea_manager import IdeaManager
    manager = IdeaManager()
    idea_spec = {'idea': _idea(continuation={'source_repo': '/repo'})}
    result = manager.validate_idea(idea_spec)
    assert not result['valid']
    assert any('goal' in e for e in result['errors'])


# ---------------------------------------------------------------- intake CLI

def test_enforce_source_repo_pins_cli_argument():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "cli"))
    from continue_research import enforce_source_repo
    result = {'parsed': {'idea': _idea(continuation={
        'source_repo': 'https://github.com/wrong/repo',
        'goal': 'Reduce latency without hurting F1'})},
        'yaml_string': 'stale'}
    result = enforce_source_repo(result, '/actual/repo')
    assert result['parsed']['idea']['continuation']['source_repo'] == '/actual/repo'
    assert '/actual/repo' in result['yaml_string']


def test_enforce_source_repo_requires_goal():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "cli"))
    from continue_research import enforce_source_repo
    result = {'parsed': {'idea': _idea()}, 'yaml_string': ''}
    with pytest.raises(SystemExit):
        enforce_source_repo(result, '/repo')


# ---------------------------------------------------------------- sealed staging

def _dataset_fixture(tmp_path):
    src = tmp_path / "host"
    src.mkdir()
    bench = src / "benchmark"
    bench.mkdir()
    (bench / "eval.csv").write_text("x,y\n1,0\n")
    train = src / "train.csv"
    train.write_text("x,y\n2,1\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    return work_dir, bench, train


def test_sealed_dataset_stages_into_test_dir(tmp_path):
    work_dir, bench, train = _dataset_fixture(tmp_path)
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': str(train), 'usage': 'training data'},
        {'path': str(bench), 'usage': 'held-out benchmark', 'sealed': True},
    ]})}
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 2
    datasets = idea_spec['idea']['local_resources']['datasets']
    assert datasets[0]['path'] == "datasets/local/train.csv"
    assert datasets[1]['path'] == f"{SEALED_STAGING_DIR}/benchmark"
    assert (work_dir / SEALED_STAGING_DIR / "benchmark" / "eval.csv").exists()


def test_sealed_dir_is_gitignored(tmp_path):
    work_dir, bench, _train = _dataset_fixture(tmp_path)
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': str(bench), 'usage': 'held-out benchmark', 'sealed': True},
    ]})}
    stage_local_resources(work_dir, idea_spec)
    gitignore = (work_dir / ".gitignore").read_text()
    assert f"{SEALED_STAGING_DIR}/" in gitignore


def test_sealed_dataset_gets_sealed_role_treatment(tmp_path):
    """The staged location must match the manifest's sealed_groundtruth rules
    and scoring_seal's SEALED_PATHS, so hiding needs no new machinery."""
    from core.scoring_seal import SEALED_PATHS
    assert any(p.rstrip('/') == SEALED_STAGING_DIR for p in SEALED_PATHS)


def test_in_repo_relative_resource_needs_no_staging(tmp_path):
    work_dir = tmp_path / "workspace"
    (work_dir / "data").mkdir(parents=True)
    (work_dir / "data" / "train.csv").write_text("x,y\n1,0\n")
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': 'data/train.csv', 'usage': 'training data'}]})}
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 0
    assert idea_spec['idea']['local_resources']['datasets'][0]['path'] == 'data/train.csv'


def test_in_repo_mandated_function_verifies_and_fails_closed(tmp_path):
    # Reviewer scenario: an adopted repo declares an in-repo evaluation
    # function. Staging fingerprints it in place, and the integrity guard
    # verifies it at its own path (not a derived code/local location), even
    # when the trusted contract is the reloaded pre-staging idea.
    import copy
    from core.local_resources import staged_function_mismatches
    work_dir = tmp_path / "workspace"
    (work_dir / "src").mkdir(parents=True)
    fn = work_dir / "src" / "score.py"
    fn.write_text("def score(p, l):\n    return 0.5\n")
    idea_spec = {'idea': _idea(local_resources={'functions': [
        {'path': 'src/score.py', 'entrypoint': 'score', 'usage': 'all evaluation',
         'required_for_evaluation': True}]})}
    trusted = copy.deepcopy(idea_spec)  # as a continuation reload sees it
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 0  # fingerprinted in place, nothing copied
    assert idea_spec['idea']['local_resources']['functions'][0]['sha256']
    assert idea_spec['idea']['local_resources']['functions'][0]['path'] == 'src/score.py'
    assert staged_function_mismatches(work_dir, idea=trusted) == []
    # Tampering after staging is refused
    fn.write_text("def score(p, l):\n    return 1.0\n")
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert mismatches
    assert "modified after staging" in mismatches[0]


def test_workspace_copy_redacts_local_source_repo():
    from core.local_resources import workspace_contract_copy
    local = {'idea': _idea(continuation=_continuation(source_repo='/home/u/proj'))}
    assert workspace_contract_copy(local)['idea']['continuation']['source_repo'] == 'proj'
    # Remote URLs are provenance, not host detail; they stay verbatim
    url = 'https://github.com/u/proj'
    remote = {'idea': _idea(continuation=_continuation(source_repo=url))}
    assert workspace_contract_copy(remote)['idea']['continuation']['source_repo'] == url


def test_relative_traversal_is_not_treated_as_in_repo(tmp_path):
    # A relative path escaping the workspace is NOT an in-repo resource; it
    # falls through to normal staging, which contains it under datasets/local
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    outside = tmp_path / "secret.csv"
    outside.write_text("x,y\n1,0\n")
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': '../secret.csv', 'usage': 'training data'}]})}
    staged = stage_local_resources(work_dir, idea_spec, base_dir=work_dir)
    assert staged == 1
    assert idea_spec['idea']['local_resources']['datasets'][0]['path'] == \
        'datasets/local/secret.csv'
    assert (work_dir / 'datasets/local/secret.csv').exists()


# ---------------------------------------------------------------- host paths

def test_collect_host_paths_covers_repo_resources_and_papers():
    from core.local_resources import collect_host_paths
    idea = _idea(
        continuation=_continuation(source_repo='/home/user/project'),
        local_resources={'datasets': [{'path': '/data/bench', 'usage': 'eval'}],
                         'functions': [{'path': 'code/local/e.py', 'usage': 'eval',
                                        'source_path': '/tools/e.py'}]},
        background={'papers': [{'path': '/papers/ref.pdf', 'description': 'ref'}]},
    )
    paths = collect_host_paths(idea)
    assert paths == ['/home/user/project', '/data/bench', '/tools/e.py', '/papers/ref.pdf']


def test_collect_host_paths_skips_urls_and_relative():
    from core.local_resources import collect_host_paths
    idea = _idea(
        continuation=_continuation(source_repo='https://github.com/u/r'),
        local_resources={'datasets': [{'path': 'datasets/local/x', 'usage': 'staged'}]},
    )
    assert collect_host_paths(idea) == []


def test_submit_idea_writes_mounts_sidecar(tmp_path):
    from core.idea_manager import IdeaManager
    manager = IdeaManager(ideas_dir=tmp_path)
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': str(tmp_path / 'data'), 'usage': 'training data'}]})}
    (tmp_path / 'data').mkdir()
    idea_id = manager.submit_idea(idea_spec)
    sidecar = tmp_path / "mounts" / f"{idea_id}.txt"
    assert sidecar.exists()
    assert str(tmp_path / 'data') in sidecar.read_text()


# ---------------------------------------------------------------- adoption

def _source_repo(tmp_path):
    src = tmp_path / "source_repo"
    (src / "src").mkdir(parents=True)
    (src / "src" / "model.py").write_text("def predict(x):\n    return 0\n")
    (src / "README.md").write_text("# Demo repo\n")
    return src


def _continuation_idea(src):
    return {'idea': _idea(continuation=_continuation(source_repo=str(src)))}


def test_adopt_copies_and_inits_git(tmp_path):
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    work_dir = tmp_path / "workspace"
    record = adopt_repository(_continuation_idea(src), "idea1", work_dir)
    assert record['adopted'] and record['mode'] == 'copy'
    assert (work_dir / "src" / "model.py").exists()
    assert (work_dir / ".git").exists()
    assert (work_dir / ".neurico" / "adoption.json").exists()
    assert (work_dir / ".neurico" / "idea.yaml").exists()
    # Original untouched
    assert not (src / ".neurico").exists()
    # Committed state
    import subprocess
    log = subprocess.run(["git", "log", "--oneline"], cwd=work_dir,
                         capture_output=True, text=True)
    assert "Adopt" in log.stdout


def test_adopt_is_idempotent(tmp_path):
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    work_dir = tmp_path / "workspace"
    adopt_repository(_continuation_idea(src), "idea1", work_dir)
    record = adopt_repository(_continuation_idea(src), "idea1", work_dir)
    assert record['adopted'] is False


def test_adopt_refuses_source_inside_workspace(tmp_path):
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    with pytest.raises(ValueError):
        adopt_repository(_continuation_idea(src), "idea1", src)


def test_adopt_refuses_nonempty_unrecorded_workspace(tmp_path):
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / "junk.txt").write_text("existing")
    with pytest.raises(ValueError):
        adopt_repository(_continuation_idea(src), "idea1", work_dir)


def test_adopt_missing_local_source_mentions_mounts(tmp_path):
    from core.repo_adoption import adopt_repository
    idea = {'idea': _idea(continuation=_continuation(source_repo=str(tmp_path / "gone")))}
    with pytest.raises(FileNotFoundError) as excinfo:
        adopt_repository(idea, "idea1", tmp_path / "workspace")
    assert "mounts" in str(excinfo.value)


def test_check_invariant_alone_is_a_contract():
    from agents.eval_verifier import extract_eval_contract, has_user_eval_contract
    idea_spec = {'idea': _idea(continuation=_continuation(invariants=[
        {'kind': 'check', 'command': 'pytest tests/', 'reason': 'tests'}]))}
    assert has_user_eval_contract(idea_spec)
    contract = extract_eval_contract(idea_spec)
    assert contract['check_invariants'][0]['command'] == 'pytest tests/'


def test_statement_invariant_alone_is_not_a_contract():
    from agents.eval_verifier import has_user_eval_contract
    idea_spec = {'idea': _idea(continuation=_continuation(invariants=[
        {'kind': 'statement', 'text': 'stay exportable', 'reason': 'deploy'}]))}
    assert not has_user_eval_contract(idea_spec)


# ---------------------------------------------------------------- prompt rendering

def test_proposer_renders_goal_and_invariants():
    from agents.autoresearch_proposer import _generate_continuation_section
    section = _generate_continuation_section(_idea(continuation=_continuation(invariants=[
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'},
        {'kind': 'check', 'command': 'pytest tests/ -x', 'reason': 'tests'},
    ])))
    assert "CONTINUE-RESEARCH GOAL" in section
    assert "Reduce inference latency" in section
    assert "do not modify src/api/" in section
    assert "`pytest tests/ -x` must keep passing" in section


def test_proposer_section_empty_without_continuation():
    from agents.autoresearch_proposer import _generate_continuation_section
    assert _generate_continuation_section(_idea()) == ""


def test_comment_prompt_renders_invariants_banner():
    from templates.prompt_generator import PromptGenerator
    idea = {'idea': _idea(continuation=_continuation(invariants=[
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'},
    ]), comments='Try a smaller model.')}
    prompt = PromptGenerator().generate_comment_prompt(idea, Path('/tmp/work'))
    assert "BINDING INVARIANTS (CONTINUE-RESEARCH)" in prompt
    assert "Do NOT modify src/api/" in prompt
    assert "The optimization goal remains: Reduce inference latency" in prompt


def test_comment_prompt_unchanged_without_continuation():
    from templates.prompt_generator import PromptGenerator
    idea = {'idea': _idea(comments='Try a smaller model.')}
    prompt = PromptGenerator().generate_comment_prompt(idea, Path('/tmp/work'))
    assert "BINDING INVARIANTS" not in prompt


# ---------------------------------------------------------------- diff guard

def _controller_stub(tmp_path, invariants):
    """Bind _protected_path_violations to a minimal stand-in controller."""
    import subprocess
    from core.autoresearch import AutoResearchController, CheckpointManager

    work_dir = tmp_path / "workspace"
    (work_dir / "src" / "api").mkdir(parents=True)
    (work_dir / "src" / "api" / "handlers.py").write_text("API = 1\n")
    (work_dir / "src" / "model.py").write_text("MODEL = 1\n")
    checkpoints = CheckpointManager(work_dir)
    parent = checkpoints.create_checkpoint("baseline")

    class Stub:
        idea = {'idea': _idea(continuation=_continuation(invariants=invariants))}

    stub = Stub()
    stub.checkpoints = checkpoints
    stub.work_dir = work_dir

    def violations():
        return AutoResearchController._protected_path_violations(stub, parent.sha)

    return work_dir, violations


def test_diff_guard_passes_untouched_protected_path(tmp_path):
    work_dir, violations = _controller_stub(tmp_path, [
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'}])
    (work_dir / "src" / "model.py").write_text("MODEL = 2\n")
    assert violations() == []


def test_diff_guard_catches_modified_protected_file(tmp_path):
    work_dir, violations = _controller_stub(tmp_path, [
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'}])
    (work_dir / "src" / "api" / "handlers.py").write_text("API = 2\n")
    assert violations() == ["src/api/handlers.py"]


def test_diff_guard_catches_new_file_under_protected_path(tmp_path):
    work_dir, violations = _controller_stub(tmp_path, [
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'}])
    (work_dir / "src" / "api" / "new_route.py").write_text("ROUTE = 1\n")
    assert violations() == ["src/api/new_route.py"]


def test_diff_guard_trivially_passes_without_invariants(tmp_path):
    work_dir, violations = _controller_stub(tmp_path, [])
    (work_dir / "src" / "api" / "handlers.py").write_text("API = 3\n")
    assert violations() == []


# ---------------------------------------------------------------- adoption (git)

def test_adopt_preserves_existing_git_history(tmp_path):
    import subprocess
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    subprocess.run(["git", "init"], cwd=src, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "original history", "--allow-empty"],
                   cwd=src, capture_output=True)
    work_dir = tmp_path / "workspace"
    adopt_repository(_continuation_idea(src), "idea1", work_dir)
    log = subprocess.run(["git", "log", "--oneline"], cwd=work_dir,
                         capture_output=True, text=True)
    assert "original history" in log.stdout
