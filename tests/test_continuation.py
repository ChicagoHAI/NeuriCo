"""Unit tests for continue-research mode (idea.continuation + sealed staging).

Covers the schema/validation layer for continuation ideas (source_repo, goal,
invariants of kind protected_path / check / statement) and the sealed-data
path: sealed: true datasets stage into the sealed store (a workspace
sibling) and are materialized at data/.test only while the scorer runs.

Run: python -m pytest tests/test_continuation.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    SEALED_STAGING_DIR,
    sealed_store_for,
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


def test_absolute_protected_path_is_error():
    # A path the guard cannot watch must be rejected at submit, not warned
    idea = _idea(continuation=_continuation(invariants=[
        {'kind': 'protected_path', 'path': '/etc/passwd', 'reason': 'why not'}]))
    errors, _warnings = validate_continuation(idea)
    assert any('absolute' in e for e in errors)


def test_traversal_and_dot_protected_paths_are_errors():
    for bad in ('../src', '.', './'):
        idea = _idea(continuation=_continuation(invariants=[
            {'kind': 'protected_path', 'path': bad, 'reason': 'r'}]))
        errors, _warnings = validate_continuation(idea)
        assert errors, f"expected rejection for {bad!r}"


def test_protected_path_normalization_keeps_dotfiles():
    # lstrip('./') would eat the leading dot of .github/.env; the exact
    # normalization must not
    from core.local_resources import normalize_protected_path
    assert normalize_protected_path('.github/workflows') == '.github/workflows'
    assert normalize_protected_path('.env') == '.env'
    assert normalize_protected_path('./src/api/') == 'src/api'


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
    # The recorded path is the eval-facing materialization path; the bytes
    # live in the sealed store, never the workspace
    assert datasets[1]['path'] == f"{SEALED_STAGING_DIR}/benchmark"
    store = sealed_store_for(work_dir)
    assert (store / SEALED_STAGING_DIR / "benchmark" / "eval.csv").exists()
    assert not (work_dir / SEALED_STAGING_DIR).exists()


def test_sealed_in_repo_resource_is_moved_not_left_readable(tmp_path):
    # A sealed dataset already inside the adopted repo must NOT take the
    # in-repo shortcut: it moves into data/.test and the original location
    # is removed, so the research agent cannot read it where it was
    work_dir = tmp_path / "workspace"
    (work_dir / "data").mkdir(parents=True)
    (work_dir / "data" / "benchmark.csv").write_text("x,label\n1,0\n")
    idea_spec = {'idea': _idea(local_resources={'datasets': [
        {'path': 'data/benchmark.csv', 'usage': 'held-out benchmark',
         'sealed': True}]})}
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 1
    entry = idea_spec['idea']['local_resources']['datasets'][0]
    assert entry['path'] == f"{SEALED_STAGING_DIR}/benchmark.csv"
    store = sealed_store_for(work_dir)
    assert (store / SEALED_STAGING_DIR / "benchmark.csv").exists()
    assert not (work_dir / "data" / "benchmark.csv").exists()
    assert not (work_dir / SEALED_STAGING_DIR).exists()


def test_sealed_host_paths_only_covers_sealed_absolute_sources(tmp_path):
    from core.local_resources import sealed_host_paths
    idea = _idea(local_resources={'datasets': [
        {'path': '/host/bench', 'usage': 'eval', 'sealed': True},
        {'path': '/host/train', 'usage': 'training'},
        {'path': 'in/repo.csv', 'usage': 'eval', 'sealed': True},
    ]})
    assert sealed_host_paths(idea) == ['/host/bench']


def test_sidecar_marks_sealed_lines(tmp_path):
    from core.idea_manager import IdeaManager
    manager = IdeaManager(ideas_dir=tmp_path / "ideas")
    idea_spec = {'idea': _idea(
        title='Sealed sidecar test idea with a title',
        local_resources={'datasets': [
            {'path': str(tmp_path / 'bench.csv'), 'usage': 'eval', 'sealed': True},
            {'path': str(tmp_path / 'train.csv'), 'usage': 'training'},
        ]})}
    (tmp_path / 'bench.csv').write_text("x\n")
    (tmp_path / 'train.csv').write_text("x\n")
    idea_id = manager.submit_idea(idea_spec, validate=False)
    lines = (tmp_path / "ideas" / "mounts" / f"{idea_id}.txt").read_text().splitlines()
    assert f"sealed:{tmp_path / 'bench.csv'}" in lines
    assert str(tmp_path / 'train.csv') in lines


def test_staging_only_covers_ancestors_and_source_repo(tmp_path):
    # Mounts expose whole trees: a declared ancestor of a sealed source and
    # the continuation source repo must be staging-phase only too
    from core.local_resources import staging_only_host_paths
    idea = {'idea': _idea(
        continuation=_continuation(source_repo='/home/u/proj'),
        local_resources={'datasets': [
            {'path': '/data/collection/bench', 'usage': 'eval', 'sealed': True},
            {'path': '/data/collection', 'usage': 'the full collection'},
            {'path': '/data/other', 'usage': 'training'},
        ]})}
    staging_only = staging_only_host_paths(idea)
    assert '/data/collection/bench' in staging_only  # the sealed source
    assert '/data/collection' in staging_only        # its declared ancestor
    assert '/home/u/proj' in staging_only            # the source repo
    assert '/data/other' not in staging_only         # unrelated stays mounted
    # An in-repo relative sealed entry alone still marks the source repo
    idea_rel = {'idea': _idea(
        continuation=_continuation(source_repo='/home/u/proj'),
        local_resources={'datasets': [
            {'path': 'data/bench.csv', 'usage': 'eval', 'sealed': True}]})}
    assert '/home/u/proj' in staging_only_host_paths(idea_rel)
    # No sealed entries -> nothing is staging-only
    idea_open = {'idea': _idea(
        continuation=_continuation(source_repo='/home/u/proj'),
        local_resources={'datasets': [
            {'path': '/data/other', 'usage': 'training'}]})}
    assert staging_only_host_paths(idea_open) == []


def test_sealed_source_inside_source_repo_removes_adopted_copy(tmp_path):
    # Reviewer scenario: the sealed file was declared relative, canonicalized
    # to an absolute host path under the source repo, and adoption copied the
    # whole repo into the workspace. Staging must remove the adopted copy.
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "bench.csv").write_text("x,label\n1,0\n")
    work_dir = tmp_path / "workspace"
    (work_dir / "data").mkdir(parents=True)
    (work_dir / "data" / "bench.csv").write_text("x,label\n1,0\n")  # adopted copy
    idea_spec = {'idea': _idea(
        continuation=_continuation(source_repo=str(repo)),
        local_resources={'datasets': [
            {'path': str(repo / "data" / "bench.csv"),
             'usage': 'held-out benchmark', 'sealed': True}]})}
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 1
    store = sealed_store_for(work_dir)
    assert (store / SEALED_STAGING_DIR / "bench.csv").exists()
    # The host source is untouched; the adopted workspace copy is gone
    assert (repo / "data" / "bench.csv").exists()
    assert not (work_dir / "data" / "bench.csv").exists()


def test_sealing_whole_source_repo_never_deletes_workspace(tmp_path):
    # Pathological but schema-legal: the sealed dataset IS the source repo.
    # The removal maps it to the workspace root, which must never be a
    # removal target — deleting the freshly adopted workspace would be
    # catastrophic, not fail-closed
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bench.csv").write_text("x,label\n1,0\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / "solver.py").write_text("pass\n")  # adopted content
    idea_spec = {'idea': _idea(
        continuation=_continuation(source_repo=str(repo)),
        local_resources={'datasets': [
            {'path': str(repo), 'usage': 'the whole eval repo',
             'sealed': True}]})}
    staged = stage_local_resources(work_dir, idea_spec)
    assert staged == 1
    assert work_dir.exists()
    assert (work_dir / "solver.py").exists()
    assert (sealed_store_for(work_dir) / SEALED_STAGING_DIR / "repo" / "bench.csv").exists()


def test_adoption_preserves_symlinks(tmp_path):
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    outside = tmp_path / "external_secret.txt"
    outside.write_text("private\n")
    (src / "link_out").symlink_to(outside)
    (src / "link_rel").symlink_to("solver.py")
    work_dir = tmp_path / "workspace"
    adopt_repository(_continuation_idea(src), "idea-links", work_dir)
    # Both copied as LINKS: under the old dereferencing behavior link_out
    # would be a regular file whose bytes equal the external secret
    link_out = work_dir / "link_out"
    assert link_out.is_symlink()
    import os
    assert os.readlink(link_out) == str(outside)
    assert (work_dir / "link_rel").is_symlink()
    # A relative in-repo link still resolves inside the workspace copy
    assert (work_dir / "link_rel").resolve() == (work_dir / "solver.py").resolve()


def test_fallback_conversion_refuses_submit(tmp_path):
    import os
    import subprocess
    intention = tmp_path / "intention.md"
    intention.write_text("# Speed up\n\nMake it faster. Keep tests passing.\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("pass\n")
    # Blank every key make_llm_client consults (OPENROUTER_KEY included:
    # load_dotenv would otherwise fill it from a .env and the conversion
    # would silently stop being a fallback)
    env = dict(os.environ, OPENROUTER_KEY="", OPENROUTER_API_KEY="",
               OPENAI_API_KEY="", NEURICO_IDEAS=str(tmp_path / "ideas"))
    proc = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parents[1] / "src" / "cli" / "continue_research.py"),
         str(repo), str(intention), "--submit",
         "-o", str(tmp_path / "out.yaml")],
        capture_output=True, text=True, env=env)
    assert proc.returncode == 1
    assert "Refusing --submit" in proc.stdout


def test_force_fresh_moves_stale_workspace(tmp_path):
    # The runner-level reset: an existing workspace is moved aside so
    # adoption re-copies and the baseline is rebuilt (not resumed)
    from core.runner import _move_stale_workspace
    work_dir = tmp_path / "runs" / "idea1"
    (work_dir / ".neurico").mkdir(parents=True)
    (work_dir / ".neurico" / "autoresearch_state.json").write_text("{}")
    stale = _move_stale_workspace(work_dir)
    assert stale is not None and stale.exists()
    assert not work_dir.exists()  # the resume probe cannot fire now
    assert (stale / ".neurico" / "autoresearch_state.json").exists()
    # Nothing to move is not an error
    assert _move_stale_workspace(work_dir) is None


def test_protected_path_normalization_rejects_trailing_parent():
    from core.local_resources import normalize_protected_path
    for bad in ('src/..', 'a/..', 'a/../b', '..', '../x'):
        with pytest.raises(ValueError):
            normalize_protected_path(bad)
    # Component canonicalization: equivalent spellings normalize identically
    assert normalize_protected_path('src//api') == 'src/api'
    assert normalize_protected_path('a/./b/') == 'a/b'


def test_hidden_sealed_entries_synthesized_into_manifest(tmp_path):
    from core.workspace_manifest import append_hidden_sealed_entries
    sealed_root = tmp_path / "sealed"
    (sealed_root / "data" / ".test" / "bench").mkdir(parents=True)
    (sealed_root / "data" / ".test" / "bench" / "eval.csv").write_text("x,y\n")
    manifest = {"files": []}
    added = append_hidden_sealed_entries(manifest, sealed_root)
    assert added == 1
    entry = manifest["files"][0]
    assert entry["path"] == "data/.test/bench/eval.csv"
    assert entry["role"] == "sealed_groundtruth"
    assert entry["extraction"] == "withheld"
    assert entry["content_hidden"] is True


def test_materialized_sealed_data_exists_only_during_scoring(tmp_path):
    from core.local_resources import materialized_sealed_data
    store = tmp_path / "store"
    (store / SEALED_STAGING_DIR).mkdir(parents=True)
    (store / SEALED_STAGING_DIR / "bench.csv").write_text("x,label\n1,0\n")
    tree = tmp_path / "tree"
    tree.mkdir()
    with materialized_sealed_data(tree, store):
        assert (tree / SEALED_STAGING_DIR / "bench.csv").exists()
    assert not (tree / SEALED_STAGING_DIR).exists()
    # A store without sealed data is a no-op
    with materialized_sealed_data(tree, tmp_path / "empty"):
        assert not (tree / SEALED_STAGING_DIR).exists()


def test_isolated_scorer_never_exposes_sealed_data_to_workspace(tmp_path):
    # End to end through make_isolated_continuation_scorer: eval.py reads the
    # sealed benchmark from the materialized frozen copy; the live workspace
    # never contains data/.test, and only the results review copy comes back
    import json
    import subprocess
    from core.autoresearch import make_isolated_continuation_scorer

    work_dir = tmp_path / "workspace"
    (work_dir / "scoring").mkdir(parents=True)
    (work_dir / "scoring" / "eval.py").write_text(
        "import json, pathlib\n"
        "rows = pathlib.Path('data/.test/bench.csv').read_text().strip().splitlines()\n"
        "json.dump({'overall_satisfied': True, 'properties': {'rows': {\n"
        "    'value': len(rows) - 1, 'target': 1, 'direction': 'max',\n"
        "    'satisfied': True}}},\n"
        "          open('scoring/results.json', 'w'))\n")
    (work_dir / "scoring" / "targets.json").write_text(
        json.dumps({"rows": {"target": 1, "direction": "max"},
                    "success_rule": "ALL_PROPERTIES_SATISFIED"}))
    subprocess.run(["git", "init"], cwd=work_dir, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], cwd=work_dir, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "base"], cwd=work_dir, capture_output=True)
    store = sealed_store_for(work_dir)
    (store / SEALED_STAGING_DIR).mkdir(parents=True)
    (store / SEALED_STAGING_DIR / "bench.csv").write_text("x,label\n1,0\n2,1\n")

    scorer = make_isolated_continuation_scorer(
        idea={'idea': _idea()}, scorer_timeout=60)
    result = scorer(work_dir)
    assert result.get('success')
    assert result['results']['properties']['rows']['value'] == 2
    # Sealed bytes never touched the live workspace; review copy did
    assert not (work_dir / SEALED_STAGING_DIR).exists()
    review = json.loads((work_dir / "scoring" / "results.json").read_text())
    assert review['properties']['rows']['value'] == 2


def test_adoption_squashes_history_for_in_repo_sealed(tmp_path):
    import subprocess
    from core.repo_adoption import adopt_repository
    src = _source_repo(tmp_path)
    (src / "bench.csv").write_text("x,label\n1,0\n")
    subprocess.run(["git", "init"], cwd=src, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], cwd=src, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "history that contains the benchmark"],
                   cwd=src, capture_output=True)
    idea = _continuation_idea(src)
    idea['idea']['local_resources'] = {'datasets': [
        {'path': str(src / "bench.csv"), 'usage': 'held-out benchmark',
         'sealed': True}]}
    work_dir = tmp_path / "workspace"
    adopt_repository(idea, "idea-squash", work_dir)
    log = subprocess.run(["git", "log", "--oneline"], cwd=work_dir,
                         capture_output=True, text=True).stdout
    assert "history that contains the benchmark" not in log
    assert len(log.strip().splitlines()) == 1


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
    """Bind the protected-path guard to a minimal stand-in controller.

    The snapshot taken here plays the role of the iteration-start
    fingerprint; violations() compares the current tree against it, exactly
    as the pre-scoring and pre-checkpoint checks do.
    """
    from core.autoresearch import AutoResearchController

    work_dir = tmp_path / "workspace"
    (work_dir / "src" / "api").mkdir(parents=True)
    (work_dir / "src" / "api" / "handlers.py").write_text("API = 1\n")
    (work_dir / "src" / "model.py").write_text("MODEL = 1\n")

    class Stub:
        idea = {'idea': _idea(continuation=_continuation(invariants=invariants))}

    stub = Stub()
    stub.work_dir = work_dir
    stub._snapshot_protected_paths = (
        lambda: AutoResearchController._snapshot_protected_paths(stub))
    before = stub._snapshot_protected_paths()

    def violations():
        return AutoResearchController._protected_path_violations(stub, before)

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


def test_diff_guard_sees_git_ignored_files(tmp_path):
    # The guard is filesystem-based, so files git ignores (weights,
    # generated configs) are still protected
    work_dir, violations = _controller_stub(tmp_path, [
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'public API'}])
    (work_dir / ".gitignore").write_text("src/api/generated/\n")
    (work_dir / "src" / "api" / "generated").mkdir()
    (work_dir / "src" / "api" / "generated" / "cache.bin").write_text("x")
    assert violations() == ["src/api/generated/cache.bin"]


def test_diff_guard_catches_deletion_and_dotfile_paths(tmp_path):
    work_dir, violations = _controller_stub(tmp_path, [
        {'kind': 'protected_path', 'path': '.env', 'reason': 'secrets'},
        {'kind': 'protected_path', 'path': 'src/api/', 'reason': 'API'}])
    # .env did not exist at snapshot time; creating it is a change
    (work_dir / ".env").write_text("KEY=1\n")
    (work_dir / "src" / "api" / "handlers.py").unlink()
    assert violations() == [".env", "src/api/handlers.py"]


def test_unsatisfied_baseline_guardrails_gate(tmp_path):
    import json
    from core.autoresearch import ScoreSummary, unsatisfied_baseline_guardrails
    idea = {'idea': _idea(continuation=_continuation(invariants=[
        {'kind': 'check', 'command': 'pytest tests/ -q', 'reason': 'suite'}]))}
    scoring = tmp_path / "scoring"
    scoring.mkdir(parents=True)
    (scoring / "targets.json").write_text(json.dumps({
        "tests_pass": {"target": 1.0, "direction": "max", "source": "user",
                       "source_text": "pytest tests/ -q"},
        "accuracy": {"target": 0.9, "direction": "max"},
        "success_rule": "ALL_PROPERTIES_SATISFIED",
    }))
    satisfied = ScoreSummary(valid=True, source="candidate", properties={
        "tests_pass": {"satisfied": True}, "accuracy": {"satisfied": True}})
    assert unsatisfied_baseline_guardrails(tmp_path, idea, satisfied) == []
    # A failing guardrail blocks the baseline...
    failing = ScoreSummary(valid=True, source="candidate", properties={
        "tests_pass": {"satisfied": False}, "accuracy": {"satisfied": True}})
    assert unsatisfied_baseline_guardrails(tmp_path, idea, failing) == ["tests_pass"]
    # ...and so does a command transcribed nowhere (fail closed)
    (scoring / "targets.json").write_text(json.dumps({
        "accuracy": {"target": 0.9, "direction": "max"}}))
    result = unsatisfied_baseline_guardrails(tmp_path, idea, satisfied)
    assert result and "transcribes" in result[0]


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
