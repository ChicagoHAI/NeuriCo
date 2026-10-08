"""The real submit CLI keeps each provider's persisted submission independent."""

from datetime import datetime
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from src.cli import submit
from core import idea_manager
from core.idea_manager import IdeaManager


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 2, 3, 4, 5, tzinfo=tz)


def test_cli_same_title_across_providers_preserves_content_mounts_and_repo_metadata(
    tmp_path, monkeypatch
):
    ideas_dir = tmp_path / "ideas"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("NEURICO_IDEAS", str(ideas_dir))
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setattr(idea_manager, "datetime", FrozenDateTime)

    class FakeGitHubManager:
        """Only the external repository service is replaced; idea storage is real."""

        def __init__(self, org_name=None):
            self.org_name = org_name

        def create_research_repo(
            self, *, idea_id, title, description, private, domain, provider, no_hash, hypothesis
        ):
            name = f"research-{provider}"
            return {
                "repo_name": name,
                "repo_url": f"https://github.example/test/{name}",
                "clone_url": f"https://github.example/test/{name}.git",
                "ssh_url": f"git@github.example:test/{name}.git",
                "local_path": workspace / name,
                "repo_object": None,
                "private": private,
            }

        def clone_repo(self, clone_url, local_path):
            local_path.mkdir(parents=True)

        def add_research_metadata(self, local_path, idea):
            (local_path / "research.yaml").write_text(yaml.safe_dump(idea), encoding="utf-8")

        def commit_and_push(self, local_path, message):
            pass

    monkeypatch.setattr(submit, "GitHubManager", FakeGitHubManager, raising=False)
    monkeypatch.setattr(submit, "GITHUB_AVAILABLE", True)
    expected = {}
    for provider in ("claude", "gemini", "codex"):
        resource = tmp_path / f"{provider}.csv"
        resource.write_text("value\n1\n", encoding="utf-8")
        spec = {
            "idea": {
                "title": "Identical title across providers",
                "domain": "machine_learning",
                "hypothesis": f"The {provider} experiment retains its independent content.",
                "local_resources": {
                    "datasets": [{"path": str(resource), "usage": "Evaluation data"}]
                },
            }
        }
        source = tmp_path / f"{provider}.yaml"
        source.write_text(yaml.safe_dump(spec), encoding="utf-8")
        monkeypatch.setattr(
            sys, "argv", ["submit", str(source), "--provider", provider, "--private"]
        )

        submit.main()

        persisted = yaml.safe_load(
            (workspace / f"research-{provider}" / "research.yaml").read_text()
        )
        expected[provider] = (persisted["idea"]["metadata"]["idea_id"], spec, resource)

    assert len({idea_id for idea_id, _, _ in expected.values()}) == 3
    manager = IdeaManager(ideas_dir)
    assert len(manager.list_ideas()) == 3
    for provider, (idea_id, original, resource) in expected.items():
        stored = manager.get_idea(idea_id)["idea"]
        assert stored["hypothesis"] == original["idea"]["hypothesis"]
        assert stored["local_resources"] == original["idea"]["local_resources"]
        assert stored["metadata"]["idea_id"] == idea_id
        assert stored["metadata"]["github_repo_name"] == f"research-{provider}"
        assert (
            stored["metadata"]["github_repo_url"]
            == f"https://github.example/test/research-{provider}"
        )
        assert stored["metadata"]["github_repo_private"] is True
        assert (ideas_dir / "mounts" / f"{idea_id}.txt").read_text().splitlines() == [str(resource)]
