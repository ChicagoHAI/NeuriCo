"""
Security utilities for API key protection.

This module provides:
1. Environment variable filtering for subprocess calls
2. Log content sanitization for real-time and batch processing
3. API key pattern detection and redaction
"""

import os
import re
from typing import Dict, Set, Optional
from pathlib import Path



# These are sensitive credentials that could be echoed in logs
SENSITIVE_ENV_VARS: Set[str] = {
    # OpenAI
    'OPENAI_API_KEY',
    'OPENAI_ORG_ID',
    # Anthropic
    'ANTHROPIC_API_KEY',
    'CLAUDE_API_KEY',
    # Google/Gemini
    'GOOGLE_API_KEY',
    'GEMINI_API_KEY',
    'GOOGLE_APPLICATION_CREDENTIALS',
    # GitHub
    'GITHUB_TOKEN',
    'GH_TOKEN',
    'GITHUB_PAT',
    # OpenRouter
    'OPENROUTER_KEY',
    'OPENROUTER_API_KEY',
    # Axiom AXLE (Lean verification API for the mathematics_lean domain)
    'AXLE_API_KEY',
    # AWS
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_SESSION_TOKEN',
    # Azure
    'AZURE_API_KEY',
    'AZURE_OPENAI_API_KEY',
    # Other common API keys
    'HUGGINGFACE_TOKEN',
    'HF_TOKEN',
    'WANDB_API_KEY',
    'COMET_API_KEY',
    'REPLICATE_API_TOKEN',
}

# Regex patterns for detecting API keys in text
# Each tuple is (pattern, replacement)
API_KEY_PATTERNS = [
    # OpenAI keys (various formats)
    (r'sk-proj-[A-Za-z0-9_-]{20,}', '[REDACTED_OPENAI_PROJECT_KEY]'),
    (r'sk-or-v1-[A-Za-z0-9_-]{20,}', '[REDACTED_OPENROUTER_KEY]'),
    (r'pk_[A-Za-z0-9_-]{20,}', '[REDACTED_AXLE_KEY]'),
    (r'sk-or-[A-Za-z0-9_-]{20,}', '[REDACTED_OPENAI_ORG_KEY]'),
    (r'sk-[A-Za-z0-9]{48,}', '[REDACTED_OPENAI_KEY]'),

    # Anthropic keys
    (r'sk-ant-[A-Za-z0-9_-]{20,}', '[REDACTED_ANTHROPIC_KEY]'),

    # GitHub tokens
    (r'ghp_[A-Za-z0-9]{36,}', '[REDACTED_GITHUB_PAT]'),
    (r'gho_[A-Za-z0-9]{36,}', '[REDACTED_GITHUB_OAUTH]'),
    (r'ghs_[A-Za-z0-9]{36,}', '[REDACTED_GITHUB_APP]'),
    (r'ghr_[A-Za-z0-9]{36,}', '[REDACTED_GITHUB_REFRESH]'),
    (r'github_pat_[A-Za-z0-9_]{20,}', '[REDACTED_GITHUB_FINE_GRAINED]'),

    # Google/Gemini API keys
    (r'AIza[A-Za-z0-9_-]{35,}', '[REDACTED_GOOGLE_KEY]'),
    (r'ya29\.[A-Za-z0-9_-]{20,}', '[REDACTED_GOOGLE_OAUTH_ACCESS]'),
    (r'1//0[A-Za-z0-9_-]{20,}', '[REDACTED_GOOGLE_OAUTH_REFRESH]'),

    # AWS keys
    (r'AKIA[A-Z0-9]{16}', '[REDACTED_AWS_ACCESS_KEY]'),

    # Generic patterns for env var assignments (catches echoed env vars)
    (r'(OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_KEY)=[^\s\n"\']+',
     r'\1=[REDACTED]'),
    (r'(export\s+)(OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|GEMINI_API_KEY|GOOGLE_API_KEY|OPENROUTER_KEY)=[^\s\n"\']+',
     r'\1\2=[REDACTED]'),
]

# Compile patterns once for performance
_COMPILED_PATTERNS = [(re.compile(pattern), replacement)
                       for pattern, replacement in API_KEY_PATTERNS]


class SanitizationError(RuntimeError):
    """Raised when a security-boundary file cannot be safely inspected."""


def sanitize_text(text: str) -> str:
    """
    Sanitize text by redacting API keys and sensitive values.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text with API keys redacted
    """
    result = text
    for pattern, replacement in _COMPILED_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def contains_sensitive_data(text: str) -> bool:
    """Return True if text contains a recognized sensitive credential."""
    return any(pattern.search(text) for pattern, _ in _COMPILED_PATTERNS)


def _is_within_git_dir(file_path: Path) -> bool:
    return ".git" in file_path.parts


def sanitize_file(file_path: Path, *, strict: bool = False) -> bool:
    """
    Sanitize an arbitrary text file in-place by redacting API keys.

    Binary or non-UTF-8 files are skipped without modification. Missing files
    are skipped to support deleted staged paths.
    """
    file_path = Path(file_path)

    if _is_within_git_dir(file_path) or not file_path.exists() or not file_path.is_file():
        return False

    try:
        raw_content = file_path.read_bytes()
    except Exception as e:
        if strict:
            raise SanitizationError(f"Could not read {file_path}: {e}") from e
        print(f"Warning: Could not sanitize {file_path}: {e}")
        return False

    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        return False

    sanitized = sanitize_text(content)
    if sanitized == content:
        return False

    try:
        file_path.write_text(sanitized, encoding="utf-8")
    except Exception as e:
        if strict:
            raise SanitizationError(f"Could not write sanitized {file_path}: {e}") from e
        print(f"Warning: Could not sanitize {file_path}: {e}")
        return False

    return True


def sanitize_log_file(file_path: Path) -> bool:
    """
    Sanitize a log file in-place by redacting API keys.

    Args:
        file_path: Path to log file

    Returns:
        True if file was modified, False otherwise
    """
    try:
        return sanitize_file(file_path, strict=False)

    except Exception as e:
        print(f"Warning: Could not sanitize {file_path}: {e}")
        return False


def sanitize_logs_directory(logs_dir: Path) -> int:
    """
    Sanitize all log files in a directory.

    Args:
        logs_dir: Path to logs directory

    Returns:
        Number of files modified
    """
    if not logs_dir.exists():
        return 0

    modified_count = 0
    log_patterns = ['*.log', '*.jsonl', '*.txt']

    for pattern in log_patterns:
        for log_file in logs_dir.glob(pattern):
            if sanitize_log_file(log_file):
                modified_count += 1

    return modified_count
