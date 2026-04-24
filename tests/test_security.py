"""Tests for core.security module."""

from core.security import get_safe_env, sanitize_text, sanitize_log_file, sanitize_logs_directory

class TestSanitizeText:
    # Verify all OpenAI key formats (project, org, OpenRouter, bare) are redacted
    def test_redacts_openai_keys(self):
        cases = [
            ("sk-proj-abc123DEF456ghi789JKL012", "[REDACTED_OPENAI_PROJECT_KEY]"),
            ("sk-or-v1-abc123DEF456ghi789JKL012", "[REDACTED_OPENROUTER_KEY]"),
            ("sk-or-abc123DEF456ghi789JKL012mno", "[REDACTED_OPENAI_ORG_KEY]"),
            ("sk-" + "A" * 48, "[REDACTED_OPENAI_KEY]"),
        ]
        for key, expected_redaction in cases:
            result = sanitize_text(f"key is {key}")
            assert key not in result, f"Key {key[:15]}... was not redacted"
            assert expected_redaction in result, f"Expected {expected_redaction} for {key[:15]}..."

    # Verify Anthropic sk-ant- prefix keys are redacted
    def test_redacts_anthropic_key(self):
        text = "key is sk-ant-abc123DEF456ghi789JKL012"
        result = sanitize_text(text)
        assert "sk-ant-" not in result
        assert "[REDACTED_ANTHROPIC_KEY]" in result

    # Verify all GitHub token formats (PAT, OAuth, App, Refresh, fine-grained) are redacted
    def test_redacts_github_tokens(self):
        suffix = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"
        cases = [
            (f"ghp_{suffix}", "[REDACTED_GITHUB_PAT]"),
            (f"gho_{suffix}", "[REDACTED_GITHUB_OAUTH]"),
            (f"ghs_{suffix}", "[REDACTED_GITHUB_APP]"),
            (f"ghr_{suffix}", "[REDACTED_GITHUB_REFRESH]"),
            ("github_pat_ABCDEFGHIJ0123456789ab", "[REDACTED_GITHUB_FINE_GRAINED]"),
        ]
        for key, expected_redaction in cases:
            result = sanitize_text(f"token is {key}")
            assert key not in result, f"Token {key[:15]}... was not redacted"
            assert expected_redaction in result, f"Expected {expected_redaction} for {key[:15]}..."

    # Verify AWS access key IDs (AKIA prefix) are redacted
    def test_redacts_aws_access_key(self):
        text = "key is AKIAIOSFODNN7EXAMPLE"
        result = sanitize_text(text)
        assert "AKIA" not in result
        assert "[REDACTED_AWS_ACCESS_KEY]" in result

    # Verify Google/Gemini API keys (AIza prefix) are redacted
    def test_redacts_google_api_key(self):
        text = "key is AIzaSyD-example-key-that-is-long-enough-00"
        result = sanitize_text(text)
        assert "AIza" not in result
        assert "[REDACTED_GOOGLE_KEY]" in result

    # Verify KEY=value assignments are redacted for all tracked env var names
    def test_redacts_env_var_assignments(self):
        env_vars = [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_KEY",
        ]
        for var in env_vars:
            result = sanitize_text(f"{var}=some-secret-value")
            assert "some-secret-value" not in result, f"{var} assignment value not redacted"
            assert f"{var}=[REDACTED]" in result, f"{var} not replaced with [REDACTED]"

    # Verify export KEY=value assignments are also caught
    def test_redacts_export_env_assignments(self):
        env_vars = [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_KEY",
        ]
        for var in env_vars:
            result = sanitize_text(f"export {var}=some-secret-value")
            assert "some-secret-value" not in result, f"export {var} value not redacted"

    # Verify normal text without secrets passes through unchanged
    def test_preserves_normal_text(self):
        text = "This is a normal log line with no secrets."
        assert sanitize_text(text) == text

    # Verify short strings starting with "sk" aren't false-positived
    def test_preserves_short_sk_prefix(self):
        text = "the sketch is ready"
        assert sanitize_text(text) == text


class TestGetSafeEnv:
    # Verify known sensitive keys (OPENAI, ANTHROPIC, etc.) are stripped from env
    def test_removes_sensitive_keys(self):
        env = {
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "sk-secret",
            "HOME": "/home/user",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
        }
        safe = get_safe_env(env)
        assert "OPENAI_API_KEY" not in safe
        assert "ANTHROPIC_API_KEY" not in safe

    # Verify non-sensitive keys are preserved untouched
    def test_keeps_non_sensitive_keys(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "LANG": "en_US.UTF-8",
        }
        safe = get_safe_env(env)
        assert safe == env

    # Verify empty env dict returns empty dict without error
    def test_empty_env(self):
        assert get_safe_env({}) == {}


class TestSanitizeLogFile:
    # Verify a log file containing secrets from all key patterns is fully redacted
    def test_sanitizes_file_with_secrets(self, tmp_path):
        github_suffix = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "OpenAI project: sk-proj-abc123DEF456ghi789JKL012\n"
            "OpenRouter: sk-or-v1-abc123DEF456ghi789JKL012\n"
            "OpenAI org: sk-or-abc123DEF456ghi789JKL012mno\n"
            f"OpenAI bare: sk-{'A' * 48}\n"
            "Anthropic: sk-ant-abc123DEF456ghi789JKL012\n"
            f"GitHub PAT: ghp_{github_suffix}\n"
            f"GitHub OAuth: gho_{github_suffix}\n"
            f"GitHub App: ghs_{github_suffix}\n"
            f"GitHub Refresh: ghr_{github_suffix}\n"
            "GitHub fine-grained: github_pat_ABCDEFGHIJ0123456789ab\n"
            "Google: AIzaSyD-example-key-that-is-long-enough-00\n"
            "AWS: AKIAIOSFODNN7EXAMPLE\n"
        )

        modified = sanitize_log_file(log_file)
        assert modified is True

        content = log_file.read_text()
        expected_redactions = [
            "[REDACTED_OPENAI_PROJECT_KEY]",
            "[REDACTED_OPENROUTER_KEY]",
            "[REDACTED_OPENAI_ORG_KEY]",
            "[REDACTED_OPENAI_KEY]",
            "[REDACTED_ANTHROPIC_KEY]",
            "[REDACTED_GITHUB_PAT]",
            "[REDACTED_GITHUB_OAUTH]",
            "[REDACTED_GITHUB_APP]",
            "[REDACTED_GITHUB_REFRESH]",
            "[REDACTED_GITHUB_FINE_GRAINED]",
            "[REDACTED_GOOGLE_KEY]",
            "[REDACTED_AWS_ACCESS_KEY]",
        ]
        for redaction in expected_redactions:
            assert redaction in content, f"{redaction} not found in sanitized file"

    # Verify clean files are not rewritten (returns False)
    def test_no_modification_when_clean(self, tmp_path):
        log_file = tmp_path / "clean.log"
        log_file.write_text("Nothing sensitive here.\n")

        modified = sanitize_log_file(log_file)
        assert modified is False

    # Verify missing files are handled gracefully (returns False)
    def test_nonexistent_file_returns_false(self, tmp_path):
        modified = sanitize_log_file(tmp_path / "missing.log")
        assert modified is False


class TestSanitizeLogsDirectory:
    # Verify .log, .jsonl, and .txt files are sanitized but other extensions are ignored
    def test_sanitizes_multiple_file_types(self, tmp_path):
        (tmp_path / "run.log").write_text("key: sk-proj-abc123DEF456ghi789JKL012\n")
        (tmp_path / "transcript.jsonl").write_text('{"key": "sk-ant-abc123DEF456ghi789JKL012"}\n')
        (tmp_path / "notes.txt").write_text("OPENAI_API_KEY=mysecret\n")
        # .py file should be ignored (not a log pattern)
        (tmp_path / "script.py").write_text("sk-proj-abc123DEF456ghi789JKL012\n")

        count = sanitize_logs_directory(tmp_path)
        assert count == 3
        assert "sk-proj-" in (tmp_path / "script.py").read_text()

    # Verify directory with only clean log files returns zero modifications
    def test_returns_zero_for_clean_directory(self, tmp_path):
        (tmp_path / "clean.log").write_text("No secrets here.\n")
        assert sanitize_logs_directory(tmp_path) == 0

    # Verify nonexistent directory is handled gracefully
    def test_returns_zero_for_nonexistent_directory(self, tmp_path):
        assert sanitize_logs_directory(tmp_path / "nope") == 0

    # Verify empty directory returns zero without error
    def test_returns_zero_for_empty_directory(self, tmp_path):
        assert sanitize_logs_directory(tmp_path) == 0
