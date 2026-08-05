"""Tests for staging sealed held-out data.

Sealed datasets are staged as PLAINTEXT into the workspace at data/.test and
then protected by the standard scoring seal (scoring_seal.py lists
"data/.test/" in SEALED_PATHS): relocated out of the workspace while any agent
runs, and copied into the frozen scorer worktree only for the scorer's
lifetime. There is no encryption store and no key.

Run: python -m pytest tests/test_sealed_staging.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    SEALED_STAGING_DIR,
    stage_local_resources,
    sealed_dataset_entries,
    staging_only_host_paths,
)

SENTINEL = "GROUND_TRUTH_ANSWER_C_D_A_B_42"


def _sealed_idea(src_path):
    return {"idea": {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
        "local_resources": {"datasets": [
            {"path": str(src_path), "name": "heldout", "sealed": True},
        ]},
    }}


def _staged_files(work_dir):
    root = Path(work_dir) / SEALED_STAGING_DIR
    return ([p for p in root.rglob("*") if p.is_file()]
            if root.exists() else [])


def test_sealed_dataset_staged_as_plaintext_source_removed(tmp_path):
    # A sealed dataset inside the workspace is copied to data/.test as
    # plaintext and the readable source is removed (move semantics).
    work = tmp_path / "work"
    (work / "raw").mkdir(parents=True)
    src = work / "raw" / "bench.csv"
    src.write_text(SENTINEL)
    idea = {"idea": {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
        "local_resources": {"datasets": [
            {"path": "raw/bench.csv", "name": "heldout", "sealed": True}]},
    }}
    assert stage_local_resources(work, idea) == 1
    staged = work / SEALED_STAGING_DIR / "heldout"
    assert staged.read_text() == SENTINEL
    assert not src.exists()               # readable source moved out
    entry = idea["idea"]["local_resources"]["datasets"][0]
    assert entry["path"] == f"{SEALED_STAGING_DIR}/heldout"


def test_sealed_directory_dereferences_symlinks(tmp_path):
    # The staged copy is self-contained: symlinked files and symlinked
    # subdirectories are dereferenced into data/.test.
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "linked.csv").write_text(SENTINEL)
    subdir = tmp_path / "shared_subdir"
    subdir.mkdir()
    (subdir / "big.bin").write_text(SENTINEL)

    src = tmp_path / "heldout_dir"
    src.mkdir()
    (src / "real.csv").write_text(SENTINEL)
    (src / "linked.csv").symlink_to(blobs / "linked.csv")
    (src / "subdir_link").symlink_to(subdir, target_is_directory=True)

    work = tmp_path / "work"
    work.mkdir()
    assert stage_local_resources(work, _sealed_idea(src)) == 1
    staged = _staged_files(work)
    assert {p.name for p in staged} == {"big.bin", "linked.csv", "real.csv"}
    assert all(not p.is_symlink() for p in staged)
    assert all(p.read_text() == SENTINEL for p in staged)


def test_sealed_staging_preserves_symlink_aliases(tmp_path):
    # Two legitimate symlinks to the same directory are both staged; only a
    # genuine cycle (a link to an ancestor) is skipped.
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "table.csv").write_text(SENTINEL)
    src = tmp_path / "heldout_dir"
    src.mkdir()
    (src / "alias_one").symlink_to(shared, target_is_directory=True)
    (src / "alias_two").symlink_to(shared, target_is_directory=True)

    work = tmp_path / "work"
    work.mkdir()
    assert stage_local_resources(work, _sealed_idea(src)) == 1
    root = work / SEALED_STAGING_DIR / "heldout"
    staged = sorted(p.relative_to(root).as_posix()
                    for p in root.rglob("*") if p.is_file())
    assert staged == ["alias_one/table.csv", "alias_two/table.csv"]


def test_sealed_staging_survives_symlink_cycles(tmp_path):
    src = tmp_path / "heldout_dir"
    (src / "nested").mkdir(parents=True)
    (src / "nested" / "real.csv").write_text(SENTINEL)
    (src / "nested" / "loop").symlink_to(src, target_is_directory=True)

    work = tmp_path / "work"
    work.mkdir()
    assert stage_local_resources(work, _sealed_idea(src)) == 1
    files = _staged_files(work)
    assert len(files) == 1 and files[0].name == "real.csv"


def test_sealed_staging_broken_symlink_is_hard_error(tmp_path):
    src = tmp_path / "heldout_dir"
    src.mkdir()
    (src / "real.csv").write_text(SENTINEL)
    (src / "gone.csv").symlink_to(tmp_path / "does_not_exist.csv")

    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(FileNotFoundError, match="broken symlink"):
        stage_local_resources(work, _sealed_idea(src))
    # No partial staged copy published for the failed dataset.
    assert not _staged_files(work)


def test_interrupted_directory_staging_leaves_no_partial(tmp_path, monkeypatch):
    # A crash mid-directory must not leave a partial data/.test the retry keeps.
    import core.local_resources as lr

    src = tmp_path / "heldout_dir"
    src.mkdir()
    (src / "a.json").write_text(SENTINEL)
    (src / "b.json").write_text(SENTINEL)
    work = tmp_path / "work"
    work.mkdir()

    real_copy = lr.shutil.copy2
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash mid-directory")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(lr.shutil, "copy2", flaky)
    with pytest.raises(RuntimeError, match="simulated crash"):
        stage_local_resources(work, _sealed_idea(src))
    assert not _staged_files(work), "crash left a partial staged dataset"

    # A retry stages the full dataset.
    monkeypatch.setattr(lr.shutil, "copy2", real_copy)
    assert stage_local_resources(work, _sealed_idea(src)) == 1
    assert len(_staged_files(work)) == 2


def test_resume_after_seal_is_idempotent(tmp_path):
    # After staging, the scoring seal relocates data/.test to .scoring_sealed.
    # Re-running staging (resume) must NOT error even though neither the
    # workspace copy nor the removed source is present.
    from core.scoring_seal import seal_scoring_files, sealed_dir_for

    work = tmp_path / "workspaces" / "ws"
    (work / "raw").mkdir(parents=True)
    (work / "raw" / "bench.csv").write_text(SENTINEL)
    idea = {"idea": {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
        "local_resources": {"datasets": [
            {"path": "raw/bench.csv", "name": "heldout", "sealed": True}]},
    }}
    assert stage_local_resources(work, idea) == 1
    # Reload the ORIGINAL contract shape (path already rewritten on resume).
    resumed = {"idea": {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
        "local_resources": {"datasets": [
            {"path": f"{SEALED_STAGING_DIR}/heldout", "name": "heldout",
             "sealed": True}]},
    }}
    # Seal it away, as the first iteration would.
    (work / "scoring").mkdir(exist_ok=True)
    (work / "scoring" / "eval.py").write_text("print('x')\n")
    (work / "scoring" / "targets.json").write_text("{}")
    seal_scoring_files(work)
    assert not (work / SEALED_STAGING_DIR).exists()
    assert (sealed_dir_for(work) / SEALED_STAGING_DIR / "heldout").exists()

    # Resume staging: no error, no re-copy, path preserved.
    assert stage_local_resources(work, resumed) == 0
    assert resumed["idea"]["local_resources"]["datasets"][0]["path"] == \
        f"{SEALED_STAGING_DIR}/heldout"


def test_sealed_dataset_entries_detects_sealed(tmp_path):
    idea = _sealed_idea(tmp_path / "x")
    assert len(sealed_dataset_entries(idea)) == 1
    idea["idea"]["local_resources"]["datasets"][0]["sealed"] = False
    assert sealed_dataset_entries(idea) == []


def _git(cwd, *args):
    import subprocess
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    return subprocess.run(["git", "-C", str(cwd), *args], env=env,
                          capture_output=True, text=True)


def test_adopt_repository_keeps_sealed_bytes_out_of_git(tmp_path):
    from core.repo_adoption import adopt_repository

    # A source repo whose git history contains an in-repo held-out dataset.
    src = tmp_path / "source"
    (src / "data").mkdir(parents=True)
    (src / "data" / "heldout.json").write_text(f'{{"answer": "{SENTINEL}"}}')
    (src / "README.md").write_text("public\n")
    _git(src, "init")
    _git(src, "add", "-A")
    _git(src, "commit", "-m", "initial with heldout")

    idea = {"idea": {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
        "continuation": {"source_repo": str(src)},
        "local_resources": {"datasets": [
            {"path": "data/heldout.json", "name": "heldout", "sealed": True},
        ]},
    }}
    work = tmp_path / "work"
    adopt_repository(idea, "adopt_test_id", work, github_manager=None)

    # The held-out bytes are nowhere in the adopted repo's git history...
    logp = _git(work, "log", "-p", "--all").stdout
    assert SENTINEL not in logp, "held-out data leaked into adopted git history"
    # ...nor at the readable in-repo path...
    assert not (work / "data" / "heldout.json").exists()
    # ...but present, plaintext, staged at data/.test (which is gitignored).
    staged = _staged_files(work)
    assert staged and any(SENTINEL in p.read_text() for p in staged)


def test_force_fresh_moves_scoring_seal_dir_aside(tmp_path):
    from core.runner import _move_stale_workspace
    from core.scoring_seal import sealed_dir_for

    work = tmp_path / "workspaces" / "my_idea"
    work.mkdir(parents=True)
    (work / "file.txt").write_text("x")
    sealed = sealed_dir_for(work)
    (sealed / "data" / ".test").mkdir(parents=True)
    (sealed / "data" / ".test" / "heldout.json").write_text("STALE")

    stale = _move_stale_workspace(work)

    assert stale is not None and stale.exists() and not work.exists()
    # The sealed dir is cleared so staging re-stages, not reuse stale data.
    assert not sealed.exists(), "stale sealed data left in place for fresh run"
    moved = list((tmp_path / "workspaces" / ".scoring_sealed").glob(
        "my_idea.stale-*"))
    assert moved, "sealed scoring dir was not moved aside"


# ---- Two-phase Docker gate: staging_only_host_paths must be TIGHT -----------
# The Docker two-phase split fires iff the mounts sidecar has a `sealed:` line,
# which is written iff staging_only_host_paths is non-empty. These tests pin
# that it fires ONLY for genuine sealed host sources that need mounting, so a
# future edit cannot loosen it into mounting held-out data where agents run.

def _idea(**local_resources_and_continuation):
    inner = {
        "title": "A sufficiently long continuation title",
        "domain": "machine_learning",
    }
    inner.update(local_resources_and_continuation)
    return {"idea": inner}


def test_no_sealed_data_no_staging_only_paths(tmp_path):
    # A plain / non-sealed run must never trip the two-phase gate.
    src = tmp_path / "public.csv"
    src.write_text("x,y\n1,2\n")
    idea = _idea(local_resources={"datasets": [
        {"path": str(src), "name": "train", "usage": "training data"}]})
    assert staging_only_host_paths(idea) == []


def test_no_local_resources_no_staging_only_paths():
    assert staging_only_host_paths(_idea()) == []


def test_external_sealed_host_path_is_staging_only(tmp_path):
    # A sealed dataset at an absolute host path needs the mount boundary.
    src = tmp_path / "heldout.csv"
    src.write_text(SENTINEL)
    idea = _idea(local_resources={"datasets": [
        {"path": str(src), "name": "heldout", "usage": "held-out", "sealed": True}]})
    assert str(src) in staging_only_host_paths(idea)


def test_in_repo_sealed_with_remote_repo_has_no_host_mount(tmp_path):
    # Held-out data inside a repo cloned from a URL produces no host path to
    # mount, so the two-phase gate must NOT fire (single container clone+stage).
    idea = _idea(
        continuation={"source_repo": "https://github.com/user/project",
                      "goal": "improve the held-out score meaningfully"},
        local_resources={"datasets": [
            {"path": "data/heldout.csv", "name": "heldout",
             "usage": "held-out", "sealed": True}]})
    assert staging_only_host_paths(idea) == []


def test_in_repo_sealed_with_local_repo_marks_the_repo(tmp_path):
    # Held-out data inside a LOCAL source repo: the repo mount would re-expose
    # it, so the repo is marked staging-only and the gate fires.
    repo = tmp_path / "local_repo"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "heldout.csv").write_text(SENTINEL)
    idea = _idea(
        continuation={"source_repo": str(repo),
                      "goal": "improve the held-out score meaningfully"},
        local_resources={"datasets": [
            {"path": "data/heldout.csv", "name": "heldout",
             "usage": "held-out", "sealed": True}]})
    marked = staging_only_host_paths(idea)
    assert str(repo) in marked
