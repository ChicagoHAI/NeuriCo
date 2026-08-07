"""Unit tests for the round-4 review fixes on continue-research.

Covers the three behaviors added after the 2026-08-05 review:
- P2: replacing a sealed dataset under the same name refreshes the staged copy
  and changes the materials fingerprint (content hash, not just name).
- P3: a validated scoring protocol persists to the durable .protocol_store and
  read_prior_scoring_protocol falls back to it once the transient seal is gone.
- P1 (partial): data/.test is sealed away from the bootstrap setup agents and
  restored for the scorer; staging recognizes the sealed location on resume.

Run: python -m pytest tests/test_review_round4_fixes.py
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.local_resources import (  # noqa: E402
    _sealed_copy_already_staged,
    read_sealed_content_shas,
    scoring_materials_fingerprint,
    stage_local_resources,
)
from core.scoring_seal import (  # noqa: E402
    persist_validated_protocol,
    protocol_store_dir_for,
    sealed_dir_for,
)
from agents.rule_maker_bootstrap import read_prior_scoring_protocol  # noqa: E402


def _sealed_idea(source_dir):
    return {'idea': {
        'title': 'A sufficiently long test title',
        'domain': 'machine_learning',
        'hypothesis': 'Sealed data handling works.',
        'local_resources': {
            'datasets': [{'path': str(source_dir), 'usage': 'held-out eval',
                          'sealed': True}],
        },
    }}


def _sealed_fixture(tmp_path):
    """External sealed source (outside the workspace, so staging keeps it)."""
    source = tmp_path / "holdout_src"
    source.mkdir()
    (source / "test.jsonl").write_text('{"id": 1}\n')
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    return work_dir, source


# ── P2: same-name replacement ──


def test_sealed_restage_is_idempotent_when_unchanged(tmp_path):
    work_dir, source = _sealed_fixture(tmp_path)
    idea = _sealed_idea(source)
    stage_local_resources(work_dir, idea)
    dst = work_dir / "data" / ".test" / "holdout_src"
    assert (dst / "test.jsonl").read_text() == '{"id": 1}\n'
    # Unchanged source: re-staging keeps the copy (no error, no churn).
    idea2 = _sealed_idea(source)
    stage_local_resources(work_dir, idea2)
    assert (dst / "test.jsonl").read_text() == '{"id": 1}\n'


def test_sealed_replacement_same_name_restages(tmp_path):
    work_dir, source = _sealed_fixture(tmp_path)
    stage_local_resources(work_dir, _sealed_idea(source))
    dst = work_dir / "data" / ".test" / "holdout_src"
    old_sha = read_sealed_content_shas(work_dir)['holdout_src']

    # Replace the dataset content, same name and declared path.
    (source / "test.jsonl").write_text('{"id": 2}\n{"id": 3}\n')
    stage_local_resources(work_dir, _sealed_idea(source))

    assert (dst / "test.jsonl").read_text() == '{"id": 2}\n{"id": 3}\n'
    assert read_sealed_content_shas(work_dir)['holdout_src'] != old_sha


def test_replacement_clears_seal_relocated_copy(tmp_path):
    work_dir, source = _sealed_fixture(tmp_path)
    stage_local_resources(work_dir, _sealed_idea(source))
    dst = work_dir / "data" / ".test" / "holdout_src"
    # Simulate the scoring seal having relocated the staged copy.
    sealed_copy = sealed_dir_for(work_dir) / "data" / ".test" / "holdout_src"
    sealed_copy.parent.mkdir(parents=True)
    dst.rename(sealed_copy)

    (source / "test.jsonl").write_text('{"id": 9}\n')
    stage_local_resources(work_dir, _sealed_idea(source))

    # Fresh bytes staged in the workspace; the stale sealed copy is gone.
    assert (dst / "test.jsonl").read_text() == '{"id": 9}\n'
    assert not sealed_copy.exists()


def test_fingerprint_tracks_content_and_survives_source_removal(tmp_path):
    work_dir, source = _sealed_fixture(tmp_path)
    stage_local_resources(work_dir, _sealed_idea(source))
    fp_original = scoring_materials_fingerprint(_sealed_idea(source), work_dir)

    # Same declaration, same name, different content -> different fingerprint.
    (source / "test.jsonl").write_text('{"id": 2}\n')
    stage_local_resources(work_dir, _sealed_idea(source))
    fp_replaced = scoring_materials_fingerprint(_sealed_idea(source), work_dir)
    assert fp_replaced != fp_original

    # Source removed (move semantics / later resume): the recorded hash keeps
    # the fingerprint stable, so no spurious regeneration fires.
    import shutil
    shutil.rmtree(source)
    fp_resumed = scoring_materials_fingerprint(_sealed_idea(source), work_dir)
    assert fp_resumed == fp_replaced


# ── P3: durable prior-protocol store ──


def _write_protocol(work_dir, marker):
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True, exist_ok=True)
    (scoring / "eval.py").write_text(f"# eval {marker}\n")
    (scoring / "targets.json").write_text(json.dumps(
        {"properties": {"m": {"target": 1.0, "direction": "max"}}}))
    (scoring / "interface.md").write_text(f"interface {marker}\n")


def test_persisted_protocol_survives_workspace_wipe(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    _write_protocol(work_dir, "v1")
    persist_validated_protocol(work_dir)

    # Completed-run lifecycle: seal removed, workspace scoring wiped.
    import shutil
    shutil.rmtree(work_dir / "scoring")
    assert not sealed_dir_for(work_dir).exists()

    prior = read_prior_scoring_protocol(work_dir)
    assert prior is not None
    assert "eval v1" in prior["eval"]
    assert "interface v1" in prior["interface"]


def test_sealed_copy_takes_precedence_over_store(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    _write_protocol(work_dir, "stale")
    persist_validated_protocol(work_dir)

    sealed_scoring = sealed_dir_for(work_dir) / "scoring"
    sealed_scoring.mkdir(parents=True)
    (sealed_scoring / "eval.py").write_text("# eval fresh\n")
    (sealed_scoring / "targets.json").write_text("{}")

    prior = read_prior_scoring_protocol(work_dir)
    assert "eval fresh" in prior["eval"]


def test_persist_overwrites_previous_store(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    _write_protocol(work_dir, "v1")
    persist_validated_protocol(work_dir)
    _write_protocol(work_dir, "v2")
    persist_validated_protocol(work_dir)
    store = protocol_store_dir_for(work_dir) / "scoring"
    assert "eval v2" in (store / "eval.py").read_text()


# ── P1 (partial): holdout sealed away from setup agents ──


def _orchestrator(work_dir):
    from core.pipeline_orchestrator import ResearchPipelineOrchestrator
    return ResearchPipelineOrchestrator(work_dir=work_dir)


def test_holdout_seal_roundtrip(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    holdout = work_dir / "data" / ".test"
    holdout.mkdir(parents=True)
    (holdout / "test.jsonl").write_text('{"id": 1}\n')

    orch = _orchestrator(work_dir)
    sealed = orch._seal_holdout_data()
    assert sealed is not None
    assert not holdout.exists()
    assert (sealed / "data" / ".test" / "test.jsonl").exists()

    orch._unseal_holdout_data(sealed)
    assert (holdout / "test.jsonl").read_text() == '{"id": 1}\n'
    assert not (sealed / "data" / ".test").exists()


def test_holdout_seal_recovers_stranded_copy(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    (work_dir / "data").mkdir(parents=True)
    orch = _orchestrator(work_dir)
    stranded = orch._bootstrap_sealed_dir_for() / "data" / ".test"
    stranded.mkdir(parents=True)
    (stranded / "test.jsonl").write_text('{"id": 1}\n')

    # No workspace copy, stranded sealed copy from a crashed window: sealing
    # adopts it so the restore points bring it back.
    sealed = orch._seal_holdout_data()
    assert sealed is not None
    orch._unseal_holdout_data(sealed)
    assert (work_dir / "data" / ".test" / "test.jsonl").exists()


def test_holdout_seal_none_when_no_data(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    orch = _orchestrator(work_dir)
    assert orch._seal_holdout_data() is None
    orch._unseal_holdout_data(None)  # no-op, no raise


def test_staging_counts_bootstrap_sealed_copy_as_staged(tmp_path):
    work_dir = tmp_path / "workspaces" / "ws"
    work_dir.mkdir(parents=True)
    dst = work_dir / "data" / ".test" / "holdout_src"
    parked = (work_dir.parent / ".bootstrap_sealed" / work_dir.name
              / "data" / ".test" / "holdout_src")
    parked.mkdir(parents=True)
    (parked / "test.jsonl").write_text('{"id": 1}\n')
    assert _sealed_copy_already_staged(work_dir, dst)
