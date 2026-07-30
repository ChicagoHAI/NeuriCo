"""Unit tests for the eval_verifier agent plumbing and integrity guards.

Covers the non-agent parts of the verification loop: contract detection,
prompt assembly, verdict reading, retry-prompt formatting, the staged-function
fingerprint check, and sealing of verification.json. The LLM verdict itself is
exercised in live pipeline runs, not here.

Run: python -m pytest tests/test_eval_verifier.py
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.eval_verifier import (  # noqa: E402
    extract_eval_contract,
    format_violations_for_retry,
    generate_eval_verifier_prompt,
    has_user_eval_contract,
    interpret_verdict,
    read_verdict,
)
from core.local_resources import (  # noqa: E402
    stage_local_resources,
    staged_function_mismatches,
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def _idea(**overrides):
    idea = {
        'title': 'A sufficiently long test title',
        'domain': 'machine_learning',
        'hypothesis': 'A sufficiently long test hypothesis for validation',
    }
    idea.update(overrides)
    return {'idea': idea}


def _contract_idea():
    return _idea(
        local_resources={'functions': [
            {'path': 'code/local/protocol_eval.py', 'entrypoint': 'evaluate_protocol',
             'usage': 'all evaluation', 'required_for_evaluation': True},
            {'path': 'code/local/helper.py', 'entrypoint': 'prep',
             'usage': 'preprocessing only'},
        ]},
        evaluation={'metrics': [
            {'name': 'test_accuracy', 'definition': 'mean over 3 seeds', 'target': '>= 0.915'}
        ]},
    )


# ---------------------------------------------------------------- contract

def test_plain_idea_has_no_contract():
    assert not has_user_eval_contract(_idea())


def test_metrics_alone_are_a_contract():
    assert has_user_eval_contract(_idea(evaluation={'metrics': [
        {'name': 'accuracy', 'definition': 'fraction correct'}]}))


def test_mandated_function_alone_is_a_contract():
    assert has_user_eval_contract(_idea(local_resources={'functions': [
        {'path': 'code/local/e.py', 'entrypoint': 'f', 'usage': 'eval',
         'required_for_evaluation': True}]}))


def test_non_mandated_function_is_not_a_contract():
    assert not has_user_eval_contract(_idea(local_resources={'functions': [
        {'path': 'code/local/e.py', 'entrypoint': 'f', 'usage': 'helper'}]}))


def test_extract_contract_keeps_only_mandated_functions():
    contract = extract_eval_contract(_contract_idea())
    assert len(contract['mandated_functions']) == 1
    assert contract['mandated_functions'][0]['entrypoint'] == 'evaluate_protocol'
    assert contract['evaluation']['metrics'][0]['name'] == 'test_accuracy'


# ---------------------------------------------------------------- prompt

def test_prompt_substitutes_all_placeholders(tmp_path):
    prompt = generate_eval_verifier_prompt(_contract_idea(), tmp_path, TEMPLATES_DIR)
    assert '{eval_contract}' not in prompt
    assert '{workspace}' not in prompt
    assert '{scoring_dir}' not in prompt
    assert '{verdict_file}' not in prompt
    assert 'evaluate_protocol' in prompt
    assert str(tmp_path / "scoring" / "verification.json") in prompt


# ---------------------------------------------------------------- verdict

def test_read_verdict_missing_returns_none(tmp_path):
    assert read_verdict(tmp_path) is None


def test_read_verdict_invalid_json_returns_none(tmp_path):
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "verification.json").write_text("not json")
    assert read_verdict(tmp_path) is None


def test_read_verdict_parses_valid_verdict(tmp_path):
    (tmp_path / "scoring").mkdir()
    (tmp_path / "scoring" / "verification.json").write_text(
        json.dumps({'pass': False, 'violations': [{'check': 'routing', 'detail': 'x'}]}))
    verdict = read_verdict(tmp_path)
    assert verdict['pass'] is False


def test_format_violations_renders_check_and_evidence():
    block = format_violations_for_retry([
        {'check': 'routing', 'detail': 'metric reimplemented',
         'evidence': 'def accuracy(...) in scoring/eval.py'},
        'free-form violation',
    ])
    assert 'MUST FIX' in block
    assert '[routing] metric reimplemented' in block
    assert 'Evidence: def accuracy' in block
    assert '- free-form violation' in block


# ---------------------------------------------------------------- integrity

def _staged_workspace_full(tmp_path):
    import copy
    src = tmp_path / "host"
    src.mkdir()
    fn = src / "protocol_eval.py"
    fn.write_text("def evaluate_protocol(p, l):\n    return 0.5\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    idea_spec = _idea(local_resources={'functions': [
        {'path': str(fn), 'entrypoint': 'evaluate_protocol', 'usage': 'all evaluation',
         'required_for_evaluation': True}]})
    trusted = copy.deepcopy(idea_spec)  # as the orchestrator holds it (pre-staging)
    stage_local_resources(work_dir, idea_spec)
    return work_dir, trusted, fn


def test_intact_staged_function_passes(tmp_path):
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    assert staged_function_mismatches(work_dir, idea=trusted) == []


def test_modified_staged_function_is_detected(tmp_path):
    work_dir, trusted, fn = _staged_workspace_full(tmp_path)
    fn.unlink()  # source unreachable -> falls back to recorded fingerprint
    (work_dir / "code/local/protocol_eval.py").write_text(
        "def evaluate_protocol(p, l):\n    return 1.0\n")
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert len(mismatches) == 1
    assert "modified after staging" in mismatches[0]


def test_workspace_without_resources_passes(tmp_path):
    assert staged_function_mismatches(tmp_path, idea=_idea()) == []


def test_missing_trusted_idea_is_refused(tmp_path):
    # The trusted contract is not optional: verifying against the
    # worker-writable workspace record alone would fail open
    with pytest.raises(ValueError, match="trusted"):
        staged_function_mismatches(tmp_path, idea=None)


def test_scorer_refuses_tampered_function(tmp_path):
    from core.scorer import run_scorer
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    (work_dir / "scoring").mkdir()
    (work_dir / "scoring" / "eval.py").write_text("print('never runs')\n")
    (work_dir / "code/local/protocol_eval.py").write_text("def evaluate_protocol(p, l):\n    return 1.0\n")
    result = run_scorer(work_dir, timeout=10, idea=trusted)
    assert not result['success']
    assert "integrity" in result['error']


# ------------------------------------------- integrity: fail-closed (trusted)

def test_trusted_intact_passes(tmp_path):
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    assert staged_function_mismatches(work_dir, idea=trusted) == []


def test_trusted_deleted_metadata_does_not_silence_guard(tmp_path):
    # A worker deleting .neurico/idea.yaml must not silence the guard:
    # tampering is still caught via the read-only source file
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    (work_dir / ".neurico" / "idea.yaml").unlink()
    (work_dir / "code/local/protocol_eval.py").write_text(
        "def evaluate_protocol(p, l):\n    return 1.0\n")
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert mismatches
    assert "differs from its source" in mismatches[0]


def test_trusted_blanked_resources_does_not_silence_guard(tmp_path):
    import yaml
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    contract_path = work_dir / ".neurico" / "idea.yaml"
    spec = yaml.safe_load(contract_path.read_text())
    spec['idea'].pop('local_resources')
    contract_path.write_text(yaml.dump(spec))
    (work_dir / "code/local/protocol_eval.py").write_text(
        "def evaluate_protocol(p, l):\n    return 1.0\n")
    assert staged_function_mismatches(work_dir, idea=trusted)


def test_trusted_record_redirect_is_defeated(tmp_path):
    # Redirect bypass: copy pristine bytes to a decoy, point the workspace
    # record at the decoy, tamper the real staged file. The guard must
    # verify the CONTRACT's canonical path, not the worker-chosen one.
    import shutil
    import yaml
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    real = work_dir / "code/local/protocol_eval.py"
    decoy = work_dir / "code/local/decoy.py"
    shutil.copy2(real, decoy)
    real.write_text("def evaluate_protocol(p, l):\n    return 1.0\n")
    contract_path = work_dir / ".neurico" / "idea.yaml"
    spec = yaml.safe_load(contract_path.read_text())
    spec['idea']['local_resources']['functions'][0]['path'] = "code/local/decoy.py"
    contract_path.write_text(yaml.dump(spec))
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert mismatches
    assert "protocol_eval.py" in mismatches[0]


def test_trusted_forged_sha_is_defeated_by_source(tmp_path):
    # Tamper the staged function AND rewrite the recorded sha to match —
    # the reachable source file must still expose the mismatch
    import hashlib
    import yaml
    work_dir, trusted, _fn = _staged_workspace_full(tmp_path)
    staged = work_dir / "code/local/protocol_eval.py"
    staged.write_text("def evaluate_protocol(p, l):\n    return 1.0\n")
    contract_path = work_dir / ".neurico" / "idea.yaml"
    spec = yaml.safe_load(contract_path.read_text())
    spec['idea']['local_resources']['functions'][0]['sha256'] = \
        hashlib.sha256(staged.read_bytes()).hexdigest()
    contract_path.write_text(yaml.dump(spec))
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert mismatches
    assert "differs from its source" in mismatches[0]


def test_trusted_missing_entry_sha_fails_closed(tmp_path):
    # Source gone AND no recorded fingerprint -> cannot verify -> mismatch
    import yaml
    work_dir, trusted, fn = _staged_workspace_full(tmp_path)
    fn.unlink()  # source unreachable
    contract_path = work_dir / ".neurico" / "idea.yaml"
    spec = yaml.safe_load(contract_path.read_text())
    spec['idea']['local_resources']['functions'][0].pop('sha256')
    contract_path.write_text(yaml.dump(spec))
    mismatches = staged_function_mismatches(work_dir, idea=trusted)
    assert mismatches
    assert "cannot be verified" in mismatches[0]


# ---------------------------------------------------------------- verdict strictness

def _valid_verdict(**overrides):
    verdict = {
        'pass': True,
        'checks': {'routing': 'pass', 'transcription': 'pass', 'format': 'not_applicable'},
        'violations': [],
    }
    verdict.update(overrides)
    return verdict


def _contract():
    """Contract matching _valid_verdict's applicability: the mandated function
    and declared metrics make routing/transcription applicable; there is no
    results_format, so format may be not_applicable."""
    return extract_eval_contract(_contract_idea())


@pytest.mark.parametrize("mutation, expected_fragment", [
    # `pass` must be a JSON boolean; a string — even "false" — or an int
    # must never count as a pass
    ({'pass': 'false'}, 'JSON boolean'),
    ({'pass': 'true'}, 'JSON boolean'),
    ({'pass': 1}, 'JSON boolean'),
    # checks must be a non-empty mapping of known names to known values
    ({'checks': None}, "'checks' mapping"),
    ({'checks': {'routing': 'maybe'}}, 'invalid value'),
    ({'checks': {'mystery': 'pass'}}, 'unknown check'),
    # every mandated check must be reported explicitly; omission is a
    # silent skip, not a pass
    ({'checks': {'routing': 'pass'}}, 'missing'),
    ({'checks': {'routing': 'pass', 'transcription': 'pass'}}, 'missing'),
    # pass=true contradicts a failing check
    ({'checks': {'routing': 'fail', 'transcription': 'pass',
                 'format': 'not_applicable'}}, 'checks failed'),
    # a failing verdict must justify itself with well-formed violations
    ({'pass': False}, 'no violations'),
    ({'pass': False, 'violations': [{'check': 'routing'}]}, 'malformed violation'),
    # the violations container must be an array, not a scalar or mapping
    ({'violations': 1}, 'must be an array'),
    ({'violations': 'nothing to report'}, 'must be an array'),
    # a check the contract makes applicable cannot be waved off — an
    # all-not_applicable verdict verifies nothing
    ({'checks': {'routing': 'not_applicable', 'transcription': 'not_applicable',
                 'format': 'not_applicable'}}, "reported 'not_applicable'"),
    ({'checks': {'routing': 'pass', 'transcription': 'not_applicable',
                 'format': 'not_applicable'}}, "reported 'not_applicable'"),
])
def test_interpret_verdict_rejects(mutation, expected_fragment):
    passed, violations = interpret_verdict(_valid_verdict(**mutation), _contract())
    assert passed is False
    assert any(expected_fragment in str(v) for v in violations)


def test_interpret_verdict_never_raises_on_malformed_container():
    # A non-array violations container must degrade to a failed verdict (the
    # retry path), never escape as a TypeError
    for bad in (1, 'oops', {'detail': 'x'}, True):
        passed, violations = interpret_verdict(
            _valid_verdict(violations=bad), _contract())
        assert passed is False
        assert any('must be an array' in str(v) for v in violations)


def test_interpret_verdict_rejects_bare_pass():
    # A bare pass=true with no checks at all is incomplete and must not pass
    passed, violations = interpret_verdict({'pass': True}, _contract())
    assert passed is False
    assert any('checks' in str(v) for v in violations)


def test_interpret_verdict_accepts_valid_verdicts():
    # The canonical verdict for the default contract passes untouched
    passed, violations = interpret_verdict(_valid_verdict(), _contract())
    assert passed is True and violations == []
    # not_applicable is fine for a check the contract does not make applicable
    metrics_only = extract_eval_contract(_idea(
        evaluation={'metrics': [{'name': 'acc', 'target': '>= 0.9'}]}))
    passed, violations = interpret_verdict(_valid_verdict(
        checks={'routing': 'not_applicable', 'transcription': 'pass',
                'format': 'not_applicable'}), metrics_only)
    assert passed is True and violations == []


def test_interpret_verdict_applicability_tracks_results_format():
    # Once the contract declares results_format, a verdict may no longer wave
    # the format check off
    full = extract_eval_contract(_idea(
        local_resources={'functions': [
            {'path': 'code/local/e.py', 'entrypoint': 'e', 'usage': 'eval',
             'required_for_evaluation': True}]},
        evaluation={'metrics': [{'name': 'acc', 'target': '>= 0.9'}],
                    'results_format': 'markdown table'},
    ))
    passed, violations = interpret_verdict(_valid_verdict(), full)
    assert passed is False
    assert any("reported 'not_applicable'" in str(v) for v in violations)
    passed, violations = interpret_verdict(_valid_verdict(
        checks={'routing': 'pass', 'transcription': 'pass', 'format': 'pass'}), full)
    assert passed is True and violations == []


# ---------------------------------------------------------------- sealing

def test_verification_json_is_sealed(tmp_path):
    from core.scoring_seal import seal_scoring_files
    work_dir = tmp_path / "workspaces" / "run1"
    (work_dir / "scoring").mkdir(parents=True)
    (work_dir / "scoring" / "eval.py").write_text("pass\n")
    (work_dir / "scoring" / "targets.json").write_text("{}")
    (work_dir / "scoring" / "verification.json").write_text('{"pass": true}')
    sealed_dir = seal_scoring_files(work_dir)
    assert not (work_dir / "scoring" / "verification.json").exists()
    assert (sealed_dir / "scoring" / "verification.json").exists()
