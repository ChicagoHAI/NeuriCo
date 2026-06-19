from __future__ import annotations
from core.trajectory_data.raw.scanner import (
    discover_repositories,
    iter_repository_files,
)

def test_discover_repositories_and_files(tmp_path):
    repos_root = tmp_path / "repos"
    repo = repos_root / "example-run"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# Hello\n", encoding="utf-8")
    (repo / "state.json").write_text('{"ok": true}', encoding="utf-8")
    hidden = repo / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("ignore me", encoding="utf-8")
    repositories = discover_repositories(repos_root)
    assert len(repositories) == 1
    assert repositories[0].repo_name == "example-run"
    files = list(iter_repository_files(repositories[0]))
    relative_paths = {file.relative_path for file in files}
    assert "README.md" in relative_paths
    assert "state.json" in relative_paths
    assert ".git/config" not in relative_paths
    state_file = next(file for file in files if file.relative_path == "state.json")
    readme_file = next(file for file in files if file.relative_path == "README.md")
    assert state_file.is_structured is True
    assert readme_file.is_structured is False




                                