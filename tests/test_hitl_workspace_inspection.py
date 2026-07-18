import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_workspace_inspection import HitlWorkspaceInspectionError, HitlWorkspaceInspector


def _inspector_with_workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text(
        "first line\nneedle = True\nthird line\n", encoding="utf-8"
    )
    (tmp_path / "notes.md").write_text("Needle is case-sensitive.\n", encoding="utf-8")
    (tmp_path / ".neurico" / "hitl").mkdir(parents=True)
    (tmp_path / ".neurico" / "hitl" / "idea.jsonl").write_text("hidden\n", encoding="utf-8")
    return HitlWorkspaceInspector(tmp_path)


def test_workspace_inspection_lists_finds_searches_and_reads_public_files(tmp_path):
    inspector = _inspector_with_workspace(tmp_path)

    listed = json.loads(inspector.list_workspace())
    assert [entry["name"] for entry in listed["entries"]] == ["src/", "notes.md"]

    found = json.loads(inspector.find_workspace_files("**/*.py"))
    assert found["matches"] == ["src/sample.py"]

    matches = json.loads(inspector.search_workspace("needle", path="src"))
    assert matches["matches"] == [
        {"path": "src/sample.py", "line_number": 2, "line": "needle = True"}
    ]

    content = json.loads(inspector.read_workspace_file("src/sample.py", offset=2, limit=1))
    assert content["line_start"] == 2
    assert content["line_count"] == 1
    assert content["content"] == "     2\tneedle = True"
    assert content["truncated"] is True


@pytest.mark.parametrize("path", [".neurico/hitl/idea.jsonl", "../outside.txt"])
def test_workspace_inspection_rejects_hidden_or_escaping_paths(tmp_path, path):
    inspector = _inspector_with_workspace(tmp_path)

    with pytest.raises(HitlWorkspaceInspectionError):
        inspector.read_workspace_file(path)
