"""Regression tests for scorer result-file validation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import agent_runner  # noqa: E402
from core.scorer import load_scoring_results, run_scorer  # noqa: E402


def _run_scorer_with_output(tmp_path, monkeypatch, write_output):
    scoring_dir = tmp_path / "scoring"
    scoring_dir.mkdir(exist_ok=True)
    (scoring_dir / "eval.py").write_text("# mocked by the test\n", encoding="utf-8")
    results_path = scoring_dir / "results.json"

    def fake_run_prebuilt_cli_agent(**_kwargs):
        write_output(results_path)
        return {"return_code": 0, "stopped": False, "timed_out": False}

    monkeypatch.setattr(
        agent_runner,
        "run_prebuilt_cli_agent",
        fake_run_prebuilt_cli_agent,
    )
    return run_scorer(tmp_path, timeout=10, idea={"idea": {}})


def test_run_scorer_returns_structured_failure_for_results_directory(
    tmp_path,
    monkeypatch,
):
    result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda results_path: results_path.mkdir(),
    )

    assert result["success"] is False
    assert result["return_code"] == 0
    assert result["results"] is None
    assert "results.json could not be read" in result["error"]


def test_run_scorer_returns_structured_failure_when_stale_directory_remains(
    tmp_path,
    monkeypatch,
):
    first_result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda results_path: results_path.mkdir(),
    )

    second_result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda results_path: results_path.mkdir(),
    )

    assert first_result["success"] is False
    assert "results.json could not be read" in first_result["error"]
    assert second_result["success"] is False
    assert second_result["return_code"] is None
    assert second_result["results"] is None
    assert "could not clear stale results.json" in second_result["error"]


def test_run_scorer_returns_structured_failure_for_invalid_utf8(
    tmp_path,
    monkeypatch,
):
    result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda results_path: results_path.write_bytes(b"\xff"),
    )

    assert result["success"] is False
    assert result["return_code"] == 0
    assert result["results"] is None
    assert "results.json is not valid UTF-8" in result["error"]


def test_run_scorer_returns_structured_failure_for_read_error(
    tmp_path,
    monkeypatch,
):
    original_read_text = Path.read_text
    results_path = tmp_path / "scoring" / "results.json"

    def unreadable_result(path, *args, **kwargs):
        if path == results_path:
            raise PermissionError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable_result)
    result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda path: path.write_text("{}", encoding="utf-8"),
    )

    assert result["success"] is False
    assert result["return_code"] == 0
    assert result["results"] is None
    assert "results.json could not be read" in result["error"]


@pytest.mark.parametrize(
    ("payload", "success", "error_text"),
    [
        (b'{"score": 1}', True, None),
        (b"{", False, "results.json is not valid JSON"),
        (b"[]", False, "results.json must contain a JSON object"),
    ],
)
def test_run_scorer_preserves_existing_result_validation(
    tmp_path,
    monkeypatch,
    payload,
    success,
    error_text,
):
    result = _run_scorer_with_output(
        tmp_path,
        monkeypatch,
        lambda results_path: results_path.write_bytes(payload),
    )

    assert result["success"] is success
    if error_text is None:
        assert result["results"] == {"score": 1}
        assert result["error"] is None
    else:
        assert result["results"] is None
        assert error_text in result["error"]


@pytest.mark.parametrize("malformed_output", ["directory", "invalid-utf8"])
def test_load_scoring_results_returns_none_for_malformed_output(
    tmp_path,
    malformed_output,
):
    scoring_dir = tmp_path / "scoring"
    scoring_dir.mkdir()
    results_path = scoring_dir / "results.json"
    if malformed_output == "directory":
        results_path.mkdir()
    else:
        results_path.write_bytes(b"\xff")

    assert load_scoring_results(tmp_path) is None


def test_load_scoring_results_returns_none_for_read_error(tmp_path, monkeypatch):
    scoring_dir = tmp_path / "scoring"
    scoring_dir.mkdir()
    results_path = scoring_dir / "results.json"
    results_path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable_result(path, *args, **kwargs):
        if path == results_path:
            raise PermissionError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable_result)

    assert load_scoring_results(tmp_path) is None
