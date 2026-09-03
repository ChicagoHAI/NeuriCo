from pathlib import Path
import sys

import pytest
from git import Repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.github_manager import GitHubManager
from core.security import SanitizationError, sanitize_file, sanitize_text


def test_redacts_google_oauth_access_token():
    token = "ya29." + "A" * 30
    assert sanitize_text(token) == "[REDACTED_GOOGLE_OAUTH_ACCESS]"


def test_redacts_google_oauth_refresh_token():
    token = "1//0" + "A" * 30
    assert sanitize_text(token) == "[REDACTED_GOOGLE_OAUTH_REFRESH]"


def test_redacts_google_oauth_tokens_embedded_in_log_text():
    access = "ya29." + "A" * 30
    refresh = "1//0" + "B" * 30

    text = f"access_token={access} refresh_token={refresh}"

    sanitized = sanitize_text(text)

    assert access not in sanitized
    assert refresh not in sanitized
    assert "[REDACTED_GOOGLE_OAUTH_ACCESS]" in sanitized
    assert "[REDACTED_GOOGLE_OAUTH_REFRESH]" in sanitized


def test_does_not_redact_short_google_oauth_like_strings():
    text = "ya29.short 1//0short"
    assert sanitize_text(text) == text


def _fake_openai_project_key() -> str:
    return "sk-proj-" + "A" * 30


def _init_repo(tmp_path: Path) -> Repo:
    repo = Repo.init(tmp_path)
    with repo.config_writer() as git_config:
        git_config.set_value("user", "name", "Test User")
        git_config.set_value("user", "email", "test@example.com")
    return repo


def _manager() -> GitHubManager:
    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "fake-token"
    return manager


def _staged_content(repo: Repo, path: str) -> str:
    return repo.git.show(f":{path}")


def test_sanitize_file_preserves_existing_google_oauth_behavior(tmp_path):
    token = "ya29." + "A" * 30
    log_file = tmp_path / "agent.log"
    log_file.write_text(f"access_token={token}", encoding="utf-8")

    assert sanitize_file(log_file) is True

    sanitized = log_file.read_text(encoding="utf-8")
    assert token not in sanitized
    assert "[REDACTED_GOOGLE_OAUTH_ACCESS]" in sanitized


def test_staged_file_outside_logs_is_sanitized_and_restaged(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "results" / "debug.txt"
    path.parent.mkdir()
    path.write_text(f"token={secret}\n", encoding="utf-8")
    repo.git.add("results/debug.txt")

    sanitized = _manager()._sanitize_staged_files(repo, tmp_path)

    assert sanitized == ["results/debug.txt"]
    working_tree = path.read_text(encoding="utf-8")
    staged = _staged_content(repo, "results/debug.txt")
    assert secret not in working_tree
    assert secret not in staged
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in working_tree
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in staged


def test_stale_index_is_replaced_after_working_tree_sanitization(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "debug.txt"
    path.write_text(secret, encoding="utf-8")
    repo.git.add("debug.txt")
    assert secret in _staged_content(repo, "debug.txt")

    _manager()._sanitize_staged_files(repo, tmp_path)

    staged = _staged_content(repo, "debug.txt")
    assert secret not in staged
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in staged


def test_commit_boundary_sanitizes_interrupted_agent_artifact_before_commit(tmp_path):
    repo = _init_repo(tmp_path)
    bare_remote = tmp_path / "remote.git"
    Repo.init(bare_remote, bare=True)
    repo.create_remote("origin", str(bare_remote))

    secret = _fake_openai_project_key()
    artifact = tmp_path / "agent_trace.json"
    artifact.write_text(f'{{"token": "{secret}"}}', encoding="utf-8")

    assert _manager().commit_and_push(tmp_path, "commit sanitized artifact") is True

    committed = repo.git.show("HEAD:agent_trace.json")
    assert secret not in committed
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in committed


def test_text_artifact_outside_old_log_extensions_is_protected(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "generated.py"
    path.write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")
    repo.git.add("generated.py")

    _manager()._sanitize_staged_files(repo, tmp_path)

    staged = _staged_content(repo, "generated.py")
    assert secret not in staged
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in staged


def test_binary_file_is_skipped_and_unchanged(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "artifact.bin"
    original = b"\xff\xfe\x00sk-proj-" + (b"A" * 30)
    path.write_bytes(original)
    repo.git.add("artifact.bin")

    assert _manager()._sanitize_staged_files(repo, tmp_path) == []
    _manager()._verify_staged_files_sanitized(repo)

    assert path.read_bytes() == original
    assert repo.git.show(":artifact.bin", "--binary").encode("latin1", errors="ignore")


def test_normal_text_file_is_unchanged(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "README.md"
    original = "# Notes\nNo credentials here.\n"
    path.write_text(original, encoding="utf-8")
    repo.git.add("README.md")

    assert _manager()._sanitize_staged_files(repo, tmp_path) == []

    assert path.read_text(encoding="utf-8") == original
    assert _staged_content(repo, "README.md") == original.rstrip("\n")


def test_deleted_staged_file_is_ignored_without_crash(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "old.txt"
    path.write_text("delete me\n", encoding="utf-8")
    repo.git.add("old.txt")
    repo.index.commit("initial")

    path.unlink()
    repo.git.add(A=True)

    assert _manager()._sanitize_staged_files(repo, tmp_path) == []
    assert "D\told.txt" in repo.git.diff("--cached", "--name-status")


def test_staged_verification_fails_closed_when_secret_remains(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "unsafe.txt"
    path.write_text(secret, encoding="utf-8")
    repo.git.add("unsafe.txt")

    with pytest.raises(SanitizationError):
        _manager()._verify_staged_files_sanitized(repo)
