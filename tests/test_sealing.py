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


def test_missing_key_fails_fast_with_guidance(no_key):
    with pytest.raises(no_key.SealKeyMissing) as exc:
        no_key.encrypt(b"x")
    assert no_key.SEAL_KEY_ENV in str(exc.value)
    # require_key_for_sealed: no-op without sealed data, raises with it
    assert no_key.require_key_for_sealed(False) is None
    with pytest.raises(no_key.SealKeyMissing):
        no_key.require_key_for_sealed(True)


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
