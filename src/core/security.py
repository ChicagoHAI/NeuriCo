"""
Security utilities for API key protection.

This module provides:
1. Environment variable filtering for subprocess calls
2. Log content sanitization for real-time and batch processing
3. API key pattern detection and redaction
"""

import re
import os
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


def sanitize_log_file(file_path: Path) -> bool:
    """
    Sanitize a log file in-place by redacting API keys.

    Args:
        file_path: Path to log file

    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        sanitized = sanitize_text(content)

        if sanitized != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sanitized)
            return True
        return False

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
