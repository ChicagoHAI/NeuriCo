"""Tests for HITL experiment-runner artifact contracts."""

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl import (  # noqa: E402
    HitlValidationError,
    load_hitl_required_artifact_contract,
    parse_required_artifacts,
    persist_hitl_required_artifact_contract,
    validate_required_artifact_contract,
    verify_required_artifacts,
)
from core.hitl_paths import hitl_artifact_contract_path  # noqa: E402


ANY_OF_ROWS = (
    "| `normal_samples.txt` | Normal samples | any-of:sample-output |\n"
    "| `exponential_samples.txt` | Exponential samples | any-of:sample-output |\n"
)


def _write_interface(work_dir: Path, rows: str = ANY_OF_ROWS) -> Path:
    scoring = work_dir / "scoring"
    scoring.mkdir(parents=True, exist_ok=True)
    interface = scoring / "interface.md"
    interface.write_text(
        "# Artifact Protocol\n\n"
        "## Files to produce\n\n"
        "| Path | Purpose | Required |\n"
        "|---|---|---|\n"
        f"{rows}",
        encoding="utf-8",
    )
    return interface


@pytest.mark.parametrize("required_row", ["| `ars.R` | Sampler | yes |\n", ""])
def test_parse_any_of_group_with_or_without_individual_requirement(tmp_path, required_row):
    artifacts = parse_required_artifacts(_write_interface(tmp_path, required_row + ANY_OF_ROWS))
    by_path = {artifact.path: (artifact.required, artifact.any_of_group) for artifact in artifacts}

    assert by_path["normal_samples.txt"] == (False, "sample-output")
    assert by_path["exponential_samples.txt"] == (False, "sample-output")
    assert ("ars.R" in by_path) is bool(required_row)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            "| `ars.R` | Sampler | yes |\n" "| `normal_samples.txt` | Samples | any-of: |\n",
            "Any-of artifact group names",
        ),
        (
            "| `ars.R` | Sampler | yes |\n"
            "| `normal_samples.txt` | Samples | any-of:Sample Output |\n",
            "Any-of artifact group names",
        ),
        (
            "| `ars.R` | Sampler | yes |\n"
            "| `normal_samples.txt` | Samples | one-of:sample-output |\n",
            "Unknown Required value",
        ),
        (
            "| `normal_samples.txt` | Samples | any-of:sample-output |\n",
            "must contain at least two paths",
        ),
    ],
)
def test_parse_rejects_invalid_any_of_contract(tmp_path, rows, message):
    with pytest.raises(HitlValidationError, match=message):
        parse_required_artifacts(_write_interface(tmp_path, rows))


@pytest.mark.parametrize(
    ("outputs", "valid"),
    [
        ({"normal_samples.txt": "0.1\n"}, True),
        ({"exponential_samples.txt": "0.2\n"}, True),
        ({"normal_samples.txt": "0.1\n", "exponential_samples.txt": "0.2\n"}, True),
        ({"normal_samples.txt": "", "exponential_samples.txt": "0.2\n"}, True),
        ({}, False),
        ({"normal_samples.txt": ""}, False),
    ],
)
def test_verify_any_of_group(tmp_path, outputs, valid):
    artifacts = parse_required_artifacts(_write_interface(tmp_path))
    for name, contents in outputs.items():
        (tmp_path / name).write_text(contents, encoding="utf-8")

    if valid:
        verify_required_artifacts(tmp_path, artifacts)
    else:
        with pytest.raises(HitlValidationError, match="group 'sample-output' is unsatisfied"):
            verify_required_artifacts(tmp_path, artifacts)


def test_any_of_group_skips_invalid_csv_candidate(tmp_path):
    artifacts = parse_required_artifacts(
        _write_interface(
            tmp_path,
            "| `invalid.csv` | CSV samples | any-of:sample-output |\n"
            "| `fallback.txt` | Text samples | any-of:sample-output |\n",
        )
    )
    (tmp_path / "invalid.csv").write_text(
        "x" * (csv.field_size_limit() + 1), encoding="utf-8"
    )
    (tmp_path / "fallback.txt").write_text("valid fallback\n", encoding="utf-8")

    verify_required_artifacts(tmp_path, artifacts)


def test_invalid_required_csv_is_worker_retryable(tmp_path):
    _write_interface(tmp_path, "| `samples.csv` | CSV samples | yes |\n")
    persist_hitl_required_artifact_contract(tmp_path)
    (tmp_path / "samples.csv").write_text(
        "x" * (csv.field_size_limit() + 1), encoding="utf-8"
    )

    result = validate_required_artifact_contract(tmp_path)

    assert result["valid"] is False
    assert "Required artifact contains invalid CSV: samples.csv" in result["issues"][0]


def test_v2_contract_round_trip_and_runtime_validation(tmp_path):
    _write_interface(tmp_path)
    persisted = persist_hitl_required_artifact_contract(tmp_path)
    payload = json.loads(hitl_artifact_contract_path(tmp_path).read_text(encoding="utf-8"))
    (tmp_path / "exponential_samples.txt").write_text("0.1\n", encoding="utf-8")

    assert payload["version"] == 2
    assert load_hitl_required_artifact_contract(tmp_path) == persisted
    assert persisted[0].any_of_group == "sample-output"
    assert validate_required_artifact_contract(tmp_path) == {"valid": True, "issues": []}


def test_loader_remains_compatible_with_v1_contracts(tmp_path):
    interface = _write_interface(
        tmp_path,
        "| `ars.R` | Sampler implementation | yes |\n"
        "| `notes.txt` | Optional notes | recommended |\n",
    )
    contract_path = hitl_artifact_contract_path(tmp_path)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(
            {
                "version": 1,
                "interface_sha256": hashlib.sha256(interface.read_bytes()).hexdigest(),
                "artifacts": [
                    {"path": "ars.R", "purpose": "Sampler", "required": True},
                    {"path": "notes.txt", "purpose": "Notes", "required": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    artifacts = load_hitl_required_artifact_contract(tmp_path)

    assert [(item.path, item.required, item.any_of_group) for item in artifacts] == [
        ("ars.R", True, None),
        ("notes.txt", False, None),
    ]
