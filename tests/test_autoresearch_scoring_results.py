"""External evaluator examples and AutoResearch result-schema diagnostics."""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from core.autoresearch import ScoringResultComparator  # noqa: E402


@pytest.fixture
def documented_payload():
    guide = (REPO_ROOT / "docs" / "AUTORESEARCH.md").read_text(encoding="utf-8")
    return json.loads(re.search(r"```json\n(.*?)\n```", guide, re.DOTALL).group(1))


def test_documented_result_loads_from_scoring_results(tmp_path, documented_payload):
    results = tmp_path / "scoring" / "results.json"
    results.parent.mkdir()
    results.write_text(json.dumps(documented_payload), encoding="utf-8")

    summary = ScoringResultComparator().load_summary(results)

    assert summary.valid, summary.error
    metric = summary.properties["benchmark_score"]
    assert metric["value"] == 0.72
    assert metric["target"] == 0.8
    assert metric["direction"] == "max"
    assert metric["satisfied"] is False
    assert metric["margin"] == pytest.approx(-0.08)


@pytest.mark.parametrize(
    ("direction", "score", "target", "satisfied"),
    [
        ("max", 0.72, 0.8, False),
        ("max", 0.8, 0.8, True),
        ("min", 0.3, 0.2, False),
        ("min", 0.2, 0.2, True),
    ],
)
def test_documented_adapter_writes_comparable_results(
    tmp_path, documented_payload, direction, score, target, satisfied
):
    scoring = tmp_path / "scoring"
    scoring.mkdir()
    spec = {"properties": {"benchmark_score": {"target": target, "direction": direction}}}
    (scoring / "targets.json").write_text(json.dumps(spec), encoding="utf-8")
    guide = (REPO_ROOT / "docs" / "AUTORESEARCH.md").read_text(encoding="utf-8")
    adapter = re.search(r"```python\n(.*?)\n```", guide, re.DOTALL).group(1)

    exec(
        compile(adapter, "documented_eval.py", "exec"),
        {
            "__file__": str(scoring / "eval.py"),
            "score": score,
        },
    )

    result_path = scoring / "results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result == {
        "properties": {
            "benchmark_score": {
                "value": score,
                "target": target,
                "direction": direction,
                "satisfied": satisfied,
            }
        },
        "overall_satisfied": satisfied,
    }
    if direction == "max" and score == 0.72:
        assert result == documented_payload
    summary = ScoringResultComparator().load_summary(result_path)
    assert summary.valid, summary.error


@pytest.mark.parametrize(
    ("direction", "parent_value", "candidate_value", "accepted"),
    [
        ("max", 0.72, 0.75, True),
        ("max", 0.72, 0.70, False),
        ("max", 0.72, 0.72, False),
        ("max", 0.72, 0.8, True),
        ("max", 0.85, 0.9, True),
        ("max", 0.85, 0.82, False),
        ("max", 0.85, 0.72, False),
        ("min", 0.9, 0.85, True),
        ("min", 0.9, 0.95, False),
        ("min", 0.9, 0.9, False),
        ("min", 0.9, 0.8, True),
        ("min", 0.72, 0.70, True),
        ("min", 0.72, 0.75, False),
        ("min", 0.72, 0.9, False),
    ],
)
def test_single_score_comparison(
    documented_payload, direction, parent_value, candidate_value, accepted
):
    comparator = ScoringResultComparator()

    def summary(value):
        payload = json.loads(json.dumps(documented_payload))
        metric = payload["properties"]["benchmark_score"]
        metric.update(value=value, direction=direction)
        metric["satisfied"] = value >= 0.8 if direction == "max" else value <= 0.8
        payload["overall_satisfied"] = metric["satisfied"]
        return comparator.summarize(payload)

    parent = summary(parent_value)
    candidate = summary(candidate_value)
    assert parent.valid and candidate.valid
    assert comparator.compare(parent, candidate).accepted is accepted


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ([], "results payload must be a JSON object"),
        ({"score": 0.72}, "missing required top-level 'properties' object"),
        ({"properties": None}, "'properties' must be a JSON object"),
        ({"properties": []}, "'properties' must be a JSON object"),
        ({"properties": {}}, "'properties' must contain at least one metric"),
        (
            {"properties": {"benchmark_score": 0.72}},
            "properties['benchmark_score'] must be a JSON object",
        ),
    ],
)
def test_invalid_result_structure_has_actionable_diagnostic(payload, error):
    summary = ScoringResultComparator().summarize(payload, source="external")

    assert not summary.valid
    assert summary.source == "external"
    assert error in summary.error
    assert "docs/AUTORESEARCH.md#integrating-an-external-evaluator" in summary.error


@pytest.mark.parametrize("field", ["value", "target", "direction", "satisfied"])
def test_missing_metric_field_names_metric_and_field(documented_payload, field):
    del documented_payload["properties"]["benchmark_score"][field]

    summary = ScoringResultComparator().summarize(documented_payload)

    assert not summary.valid
    assert f"properties['benchmark_score']: missing required field '{field}'" in summary.error
    assert "docs/AUTORESEARCH.md#integrating-an-external-evaluator" in summary.error


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("value", True, "value is not numeric"),
        ("value", "bad score", "value is not numeric"),
        ("value", None, "value is not numeric"),
        ("value", float("nan"), "value is not finite"),
        ("value", float("inf"), "value is not finite"),
        ("value", 10**400, "value is not numeric"),
        ("target", False, "target is not numeric"),
        ("target", [], "target is not numeric"),
        ("target", float("-inf"), "target is not finite"),
        ("direction", "higher", "direction must be 'max'"),
        ("direction", [], "direction must be 'max'"),
        ("satisfied", "false", "satisfied must be a JSON boolean"),
        ("satisfied", 0, "satisfied must be a JSON boolean"),
    ],
)
def test_malformed_metric_field_has_actionable_diagnostic(documented_payload, field, value, error):
    documented_payload["properties"]["benchmark_score"][field] = value

    summary = ScoringResultComparator().summarize(documented_payload)

    assert not summary.valid
    assert f"properties['benchmark_score']: {error}" in summary.error
    assert "docs/AUTORESEARCH.md#integrating-an-external-evaluator" in summary.error


@pytest.mark.parametrize("invalid_source", ["parent", "candidate"])
def test_comparison_surfaces_invalid_result_diagnostic(documented_payload, invalid_source):
    comparator = ScoringResultComparator()
    valid = comparator.summarize(documented_payload)
    invalid = comparator.summarize({"score": 0.72})

    decision = comparator.compare(
        invalid if invalid_source == "parent" else valid,
        invalid if invalid_source == "candidate" else valid,
    )

    assert not decision.accepted
    assert f"{invalid_source.title()} scoring result is invalid" in decision.reason
    assert "missing required top-level 'properties' object" in decision.reason
    assert "docs/AUTORESEARCH.md#integrating-an-external-evaluator" in decision.reason


@pytest.mark.parametrize(("field", "value"), [("target", 0.9), ("direction", "min")])
def test_benchmark_target_and_direction_must_stay_consistent(documented_payload, field, value):
    comparator = ScoringResultComparator()
    parent = comparator.summarize(documented_payload)
    documented_payload["properties"]["benchmark_score"][field] = value

    decision = comparator.compare(parent, comparator.summarize(documented_payload))

    assert not decision.accepted
    assert f"Scoring property {field} changed for benchmark_score" in decision.reason
