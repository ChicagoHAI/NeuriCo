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

def _staged_workspace(tmp_path):
    src = tmp_path / "host"
    src.mkdir()
    fn = src / "protocol_eval.py"
    fn.write_text("def evaluate_protocol(p, l):\n    return 0.5\n")
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    idea_spec = _idea(local_resources={'functions': [
        {'path': str(fn), 'entrypoint': 'evaluate_protocol', 'usage': 'all evaluation',
         'required_for_evaluation': True}]})
    stage_local_resources(work_dir, idea_spec)
    return work_dir


def test_intact_staged_function_passes(tmp_path):
    work_dir = _staged_workspace(tmp_path)
    assert staged_function_mismatches(work_dir) == []


def test_modified_staged_function_is_detected(tmp_path):
    work_dir = _staged_workspace(tmp_path)
    (work_dir / "code/local/protocol_eval.py").write_text(
        "def evaluate_protocol(p, l):\n    return 1.0\n")
    mismatches = staged_function_mismatches(work_dir)
    assert len(mismatches) == 1
    assert "modified after staging" in mismatches[0]


def test_workspace_without_resources_passes(tmp_path):
    assert staged_function_mismatches(tmp_path) == []


def test_scorer_refuses_tampered_function(tmp_path):
    from core.scorer import run_scorer
    work_dir = _staged_workspace(tmp_path)
    (work_dir / "scoring").mkdir()
    (work_dir / "scoring" / "eval.py").write_text("print('never runs')\n")
    (work_dir / "code/local/protocol_eval.py").write_text("def evaluate_protocol(p, l):\n    return 1.0\n")
    result = run_scorer(work_dir, timeout=10)
    assert not result['success']
    assert "integrity" in result['error']


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
