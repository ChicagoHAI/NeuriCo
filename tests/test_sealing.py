"""Unit tests for encryption-at-rest of sealed held-out data.

The sealed store holds ciphertext so an agent that can see it (it rides the
workspaces mount into the research container) reads only encrypted bytes. The
scorer decrypts transiently. The key is a launch secret that is popped from the
environment before any agent subprocess is spawned.

Run: python -m pytest tests/test_sealing.py
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.sealing as sealing  # noqa: E402
from core.local_resources import (  # noqa: E402
    _encrypt_sealed_store_path,
    materialized_sealed_data,
)

SENTINEL = "GROUND_TRUTH_ANSWER_C_D_A_B_42"


@pytest.fixture
def fresh_sealing(monkeypatch):
    """Reset the one-shot key cache and supply a fresh key in the environment."""
    key = sealing.generate_key()
    monkeypatch.setenv(sealing.SEAL_KEY_ENV, key)
    importlib.reload(sealing)
    yield sealing
    importlib.reload(sealing)


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv(sealing.SEAL_KEY_ENV, raising=False)
    importlib.reload(sealing)
    yield sealing
    importlib.reload(sealing)


def test_round_trip_and_ciphertext_hides_plaintext(fresh_sealing):
    token = fresh_sealing.encrypt(SENTINEL.encode())
    assert fresh_sealing.decrypt(token) == SENTINEL.encode()
    assert SENTINEL.encode() not in token


def test_key_is_stripped_from_environment(fresh_sealing, monkeypatch):
    import os

    # First access pops the key; every later os.environ.copy() (used to spawn an
    # agent) must therefore be keyless.
    assert fresh_sealing.seal_key_available() is True
    assert sealing.SEAL_KEY_ENV not in os.environ
    assert sealing.SEAL_KEY_ENV not in os.environ.copy()


def test_no_key_encrypt_raises_with_guidance(no_key):
    # A context that needs the key but has none (e.g. a Docker research
    # container launched without one) fails loudly rather than silently.
    with pytest.raises(no_key.SealKeyMissing) as exc:
        no_key.encrypt(b"x")
    assert no_key.SEAL_KEY_ENV in str(exc.value)


def test_require_provisions_key_to_env(no_key, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_KEY=abc\n")
    # No sealed data: nothing is provisioned.
    assert no_key.require_key_for_sealed(False, env_path=env) is None
    assert no_key.SEAL_KEY_ENV not in env.read_text()
    # Sealed data and no key: a random key is generated and persisted to .env,
    # and becomes usable this process (but not via os.environ -> agents stay
    # keyless).
    import os

    no_key.require_key_for_sealed(True, env_path=env)
    assert no_key.seal_key_available() is True
    assert f"{no_key.SEAL_KEY_ENV}=" in env.read_text()
    assert no_key.SEAL_KEY_ENV not in os.environ
    # Idempotent: a second call neither regenerates nor duplicates the line.
    before = env.read_text()
    no_key.require_key_for_sealed(True, env_path=env)
    assert env.read_text() == before


def test_store_is_ciphertext_and_scorer_sees_plaintext(fresh_sealing, tmp_path):
    store = tmp_path / "store"
    tree = tmp_path / "tree"
    testdir = store / "data" / ".test"
    testdir.mkdir(parents=True)
    (testdir / "answers.json").write_text(f'{{"key": "{SENTINEL}"}}')

    # Staging encrypts the store in place.
    _encrypt_sealed_store_path(testdir)
    raw = (testdir / "answers.json").read_bytes()
    assert SENTINEL.encode() not in raw, "held-out answer left in plaintext in the store"

    # Scoring materializes plaintext only inside the context.
    with materialized_sealed_data(tree, store):
        got = (tree / "data" / ".test" / "answers.json").read_text()
        assert SENTINEL in got
    assert not (tree / "data" / ".test").exists(), "plaintext survived past the scorer"


def test_materialize_is_noop_without_sealed_data(fresh_sealing, tmp_path):
    store = tmp_path / "store"
    (store).mkdir()
    tree = tmp_path / "tree"
    tree.mkdir()
    with materialized_sealed_data(tree, store):
        assert not (tree / "data" / ".test").exists()


def _git(cwd, *args):
    import subprocess

    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    return subprocess.run(["git", "-C", str(cwd), *args], env=env,
                          capture_output=True, text=True)


def test_adopt_repository_keeps_sealed_bytes_out_of_git(fresh_sealing, tmp_path):
    from core.repo_adoption import adopt_repository
    from core.local_resources import sealed_store_for

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

    # The held-out bytes must be nowhere in the adopted repo's git history...
    logp = _git(work, "log", "-p", "--all").stdout
    assert SENTINEL not in logp, "held-out data leaked into adopted git history"
    # ...nor in the working tree...
    assert not (work / "data" / "heldout.json").exists()
    # ...but present, encrypted, in the store.
    store_blobs = [p.read_bytes() for p in sealed_store_for(work).rglob("*")
                   if p.is_file()]
    assert store_blobs, "sealed data was not extracted to the store"
    assert all(SENTINEL.encode() not in b for b in store_blobs), \
        "store holds plaintext held-out data"


def test_force_fresh_moves_sealed_store_aside(fresh_sealing, tmp_path):
    from core.runner import _move_stale_workspace
    from core.local_resources import sealed_store_for

    work = tmp_path / "workspaces" / "my_idea"
    work.mkdir(parents=True)
    (work / "file.txt").write_text("x")
    store = sealed_store_for(work)
    (store / "data" / ".test").mkdir(parents=True)
    (store / "data" / ".test" / "heldout.json").write_bytes(b"STALE_CIPHERTEXT")
    assert store.exists()

    stale = _move_stale_workspace(work)

    assert stale is not None and stale.exists() and not work.exists()
    # The fresh store path must be clear so staging re-extracts, not reuse stale.
    assert not store.exists(), "stale sealed store left in place for the fresh run"
    # ...and preserved under a stale sibling for recovery.
    stale_stores = list((tmp_path / "workspaces" / ".sealed_store").glob("my_idea.stale-*"))
    assert stale_stores, "sealed store was not moved aside"
