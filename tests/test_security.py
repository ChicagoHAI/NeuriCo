from pathlib import Path
import inspect
import subprocess
import sys

import pytest
from git import Repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core.github_manager as github_manager_module
from core.github_manager import GitHubManager
from core.security import (
    SanitizationError,
    contains_sensitive_data_bytes,
    sanitize_text,
)


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

    seed = tmp_path / "seed.txt"
    seed.write_text("seed\n", encoding="utf-8")
    repo.git.add("seed.txt")
    repo.index.commit("initial")
    return repo


def _manager() -> GitHubManager:
    manager = GitHubManager.__new__(GitHubManager)
    manager.token = "fake-token"
    return manager


def _staged_bytes(repo: Repo, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f":{path}"],
        cwd=repo.working_tree_dir,
        capture_output=True,
        check=True,
    ).stdout


def test_staged_text_is_sanitized_in_index_without_touching_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "results" / "debug.txt"
    path.parent.mkdir()
    path.write_text(f"token={secret}\n", encoding="utf-8")
    repo.git.add("results/debug.txt")

    sanitized = _manager()._sanitize_staged_files(repo, tmp_path)

    assert sanitized == ["results/debug.txt"]
    assert secret in path.read_text(encoding="utf-8")
    staged = _staged_bytes(repo, "results/debug.txt").decode("utf-8")
    assert secret not in staged
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in staged
    _manager()._verify_staged_files_sanitized(repo)


def test_text_artifact_outside_old_log_extensions_is_protected(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "generated.py"
    path.write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")
    repo.git.add("generated.py")

    _manager()._sanitize_staged_files(repo, tmp_path)

    staged = _staged_bytes(repo, "generated.py").decode("utf-8")
    assert secret not in staged
    assert "[REDACTED_OPENAI_PROJECT_KEY]" in staged


def test_staged_verification_fails_closed_when_secret_remains(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    path = tmp_path / "unsafe.txt"
    path.write_text(secret, encoding="utf-8")
    repo.git.add("unsafe.txt")

    with pytest.raises(SanitizationError):
        _manager()._verify_staged_files_sanitized(repo)


def test_non_utf8_binary_secret_is_rejected(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "artifact.bin"
    original = b"\xff\xfe\x00sk-proj-" + (b"A" * 30)
    path.write_bytes(original)
    repo.git.add("artifact.bin")

    assert contains_sensitive_data_bytes(original)
    with pytest.raises(SanitizationError):
        _manager()._sanitize_staged_files(repo, tmp_path)

    assert path.read_bytes() == original
    assert _staged_bytes(repo, "artifact.bin") == original


def test_non_utf8_binary_without_secret_is_preserved(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "artifact.bin"
    original = b"\xff\xfe\x00\x01ordinary-binary"
    path.write_bytes(original)
    repo.git.add("artifact.bin")

    assert _manager()._sanitize_staged_files(repo, tmp_path) == []
    _manager()._verify_staged_files_sanitized(repo)

    assert path.read_bytes() == original
    assert _staged_bytes(repo, "artifact.bin") == original


def test_symlink_target_outside_repo_is_not_followed_or_modified(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key()
    outside = tmp_path.parent / f"{tmp_path.name}-outside-secret.txt"
    outside.write_text(secret, encoding="utf-8")
    link = tmp_path / "external-link"

    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable in this environment")

    repo.git.add("external-link")
    assert _manager()._sanitize_staged_files(repo, tmp_path) == []
    _manager()._verify_staged_files_sanitized(repo)

    assert outside.read_text(encoding="utf-8") == secret
    mode, _ = _manager()._staged_entry(repo, "external-link")
    assert mode == "120000"


def test_credential_inside_staged_symlink_blob_is_rejected(tmp_path):
    repo = _init_repo(tmp_path)
    secret = _fake_openai_project_key().encode("ascii")
    blob_sha = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo.working_tree_dir,
        input=secret,
        capture_output=True,
        check=True,
    ).stdout.strip().decode("ascii")
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", "120000", blob_sha, "secret-link"],
        cwd=repo.working_tree_dir,
        check=True,
    )

    with pytest.raises(SanitizationError):
        _manager()._sanitize_staged_files(repo, tmp_path)


def test_oversized_blob_is_unstaged_before_sanitizer_can_read_it(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * 32)
    repo.git.add("large.bin")

    monkeypatch.setattr(github_manager_module, "MAX_FILE_SIZE", 8)
    manager = _manager()
    large_files = manager._unstage_large_files(repo, tmp_path)

    assert large_files == [("large.bin", 32)]
    assert "large.bin" not in manager._staged_paths(repo)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("sanitizer attempted to read an unstaged oversized blob")

    monkeypatch.setattr(manager, "_read_staged_blob", forbidden_read)
    assert manager._sanitize_staged_files(repo, tmp_path) == []


def test_deleted_staged_file_is_ignored_without_crash(tmp_path):
    repo = _init_repo(tmp_path)
    path = tmp_path / "old.txt"
    path.write_text("delete me\n", encoding="utf-8")
    repo.git.add("old.txt")
    repo.index.commit("add old file")

    path.unlink()
    repo.git.add(A=True)

    assert _manager()._sanitize_staged_files(repo, tmp_path) == []
    assert "D\told.txt" in repo.git.diff("--cached", "--name-status")


def test_push_if_clean_api_is_preserved_after_rebase():
    parameter = inspect.signature(GitHubManager.commit_and_push).parameters["push_if_clean"]
    assert parameter.default is False
