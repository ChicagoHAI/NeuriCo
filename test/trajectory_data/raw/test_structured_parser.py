from __future__ import annotations
from core.trajectory_data.raw.structured_parser import parse_structured_file

def test_parse_json_object(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"stage": "done", "score": 1}', encoding="utf-8")
    result = parse_structured_file(path)
    assert result.status == "ok"
    assert len(result.records) == 1
    assert result.records[0].record_format == "json"
    assert result.records[0].record_type == "object"
    assert result.records[0].payload["stage"] == "done"

def test_parse_jsonl_preserves_malformed_line(tmp_path):
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        '{"type": "event", "value": 1}\n'
        "Reading prompt from stdin...\n"
        '{"type": "event", "value": 2}\n',
        encoding="utf-8",
    )
    result = parse_structured_file(path)
    assert result.status == "partial"
    assert len(result.records) == 3
    assert len(result.errors) == 1
    assert result.errors[0].source_line == 2
    assert result.records[1].record_format == "plain_text"
    assert result.records[1].raw_text == "Reading prompt from stdin..."

def test_parse_yaml(tmp_path):
    path = tmp_path / "idea.yaml"
    path.write_text(
        "title: Test idea\n"
        "status: completed\n",
        encoding="utf-8",
    )
    result = parse_structured_file(path)
    assert result.status == "ok"
    assert len(result.records) == 1
    assert result.records[0].record_format == "yaml"
    assert result.records[0].payload["title"] == "Test idea"