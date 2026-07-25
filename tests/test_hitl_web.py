import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli import hitl_web
from interactive.hitl_web_server import HitlWebServer


def test_workspace_for_new_idea_creates_and_persists_local_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    idea_id = "fresh-idea"
    idea_path = tmp_path / "ideas" / "submitted" / f"{idea_id}.yaml"
    idea_path.parent.mkdir(parents=True)
    idea_path.write_text(
        yaml.safe_dump({"idea": {"title": "Fresh idea", "metadata": {"idea_id": idea_id}}}),
        encoding="utf-8",
    )
    workspace_root = tmp_path / "workspaces"
    monkeypatch.setattr(
        hitl_web.ConfigLoader,
        "get_workspace_parent_dir",
        lambda _self: workspace_root,
    )

    workspace = hitl_web._workspace_for_idea(tmp_path, idea_id)

    assert workspace == (workspace_root / idea_id).resolve()
    persisted = yaml.safe_load(idea_path.read_text(encoding="utf-8"))
    assert persisted["idea"]["metadata"]["local_workspace"] == str(workspace)


def test_command_owned_web_host_is_not_launchable_by_default(tmp_path: Path) -> None:
    server = HitlWebServer(
        channel=object(),
        workspace=tmp_path,
        project_root=tmp_path,
        title="test",
    )

    assert server._run_status() == {"status": "unavailable"}
