"""
Security utilities for API key protection.

This module provides:
1. Environment variable filtering for subprocess calls
2. Log content sanitization for real-time and batch processing
3. API key pattern detection and redaction
"""

import re
import os
from typing import Dict, MutableMapping, Set, Optional
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

GITHUB_CREDENTIAL_ENV_VARS = frozenset({
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_PAT",
})


def remove_github_credentials(environment: MutableMapping[str, str]) -> None:
    """Keep runtime-owned GitHub credentials out of research subprocesses."""
    for name in GITHUB_CREDENTIAL_ENV_VARS:
        environment.pop(name, None)


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

    # Hugging Face tokens
    (r'hf_[A-Za-z0-9]{30,}', '[REDACTED_HF_TOKEN]'),

    # Mapbox tokens (seen in saved third-party web pages; GitHub push protection
    # rejects pushes that contain them, public pk. tokens included)
    (r'\b[ps]k\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}', '[REDACTED_MAPBOX_TOKEN]'),

    # Other providers with a recognizable prefix
    (r'gsk_[A-Za-z0-9]{40,}', '[REDACTED_GROQ_KEY]'),
    (r'xai-[A-Za-z0-9]{40,}', '[REDACTED_XAI_KEY]'),
    (r'pplx-[A-Za-z0-9]{40,}', '[REDACTED_PERPLEXITY_KEY]'),
    (r'r8_[A-Za-z0-9]{30,}', '[REDACTED_REPLICATE_TOKEN]'),
]

# Env var assignments (catches echoed env vars, e.g. the output of `env`).
# Applied to logs only: in source files they would also rewrite harmless code
# such as `HF_TOKEN=$HF_TOKEN`.
_ASSIGNED_NAMES = (
    r'OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|GH_TOKEN|GEMINI_API_KEY|GOOGLE_API_KEY'
    r'|OPENROUTER_KEY|OPENROUTER_API_KEY|HF_TOKEN|HUGGINGFACE_TOKEN|HUGGING_FACE_HUB_TOKEN'
    r'|S2_API_KEY|COHERE_API_KEY|WANDB_API_KEY|AXLE_API_KEY'
)
ASSIGNMENT_PATTERNS = [
    (rf'\b({_ASSIGNED_NAMES})=[^\s\n"\'\\]+', r'\1=[REDACTED]'),
]

# Compile patterns once for performance
_KEY_PATTERNS = [(re.compile(pattern), replacement)
                 for pattern, replacement in API_KEY_PATTERNS]
_COMPILED_PATTERNS = _KEY_PATTERNS + [(re.compile(pattern), replacement)
                                      for pattern, replacement in ASSIGNMENT_PATTERNS]


# Environment variables whose names look like credentials are redacted by
# value as well, which covers keys with no recognizable prefix (S2, Cohere, ...).
_SECRET_NAME_PATTERN = re.compile(r'(KEY|TOKEN|SECRET|PASSWORD|PAT)$')
_MIN_SECRET_VALUE_LENGTH = 12


def sensitive_env_values(environment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return {value: name} for credential-like variables in the environment."""
    environment = os.environ if environment is None else environment
    values: Dict[str, str] = {}
    for name, value in environment.items():
        value = (value or "").strip()
        if len(value) < _MIN_SECRET_VALUE_LENGTH:
            continue
        if name in SENSITIVE_ENV_VARS or _SECRET_NAME_PATTERN.search(name.upper()):
            values.setdefault(value, name)
    return values


def sanitize_text(text: str, assignments: bool = True) -> str:
    """
    Sanitize text by redacting API keys and sensitive values.

    Args:
        text: Text to sanitize
        assignments: Also redact `NAME=value` for known credential variables.
            Use False for source files, where only real key values should change.

    Returns:
        Sanitized text with API keys redacted
    """
    result = text
    # Exact values first, so a known key is labelled by its variable name.
    for value, name in sensitive_env_values().items():
        if value in result:
            result = result.replace(value, f'[REDACTED_{name}]')
    for pattern, replacement in (_COMPILED_PATTERNS if assignments else _KEY_PATTERNS):
        result = pattern.sub(replacement, result)
    return result


def find_secrets(text: str) -> list:
    """Return the labels of any API key values found in text."""
    found = [name for value, name in sensitive_env_values().items() if value in text]
    for pattern, replacement in _KEY_PATTERNS:
        if pattern.search(text):
            found.append(replacement)
    return found


# Largest file the publisher will push. Files above it are excluded from
# publication, so they are also the only ones not scanned: everything that can
# be published is inspected. Kept below GitHub's 100 MiB per-file limit.
MAX_PUBLISH_BYTES = 50 * 1024 * 1024
MAX_SCAN_BYTES = MAX_PUBLISH_BYTES


_CORE_DUMP_NAME = re.compile(r'^core(\.\d+)?$')


def is_core_dump(path: Path) -> bool:
    """True for files that look like process core dumps (name and ELF/CORE header)."""
    if not _CORE_DUMP_NAME.match(path.name):
        return False
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except OSError:
        return True  # unreadable, but named like a dump: treat it as one


def binary_files_with_secrets(root: Path, relative_paths) -> list:
    """Relative paths of binary files that contain a configured credential value.

    Text files are rewritten by sanitize_files; a binary file (core dump, pickle,
    database) cannot be rewritten safely, so callers must drop it instead.
    """
    values = [value.encode('utf-8') for value in sensitive_env_values()]
    found = []
    for relative in relative_paths:
        path = Path(root) / relative
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if is_core_dump(path):
            found.append(relative)
            continue
        try:
            data.decode('utf-8')
            continue  # text: handled by sanitize_files
        except UnicodeDecodeError:
            pass
        if any(value in data for value in values):
            found.append(relative)
    return found


def sanitize_files(root: Path, relative_paths) -> list:
    """
    Redact API key values in the given files (paths relative to root).

    Used on everything about to be published, not only logs: an agent can echo
    a key into code, notes or result files. Binary, missing and oversized files
    are skipped. Returns the relative paths that were rewritten.
    """
    redacted = []
    for relative in relative_paths:
        path = Path(root) / relative
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: nothing to rewrite
        if not find_secrets(content):
            continue
        path.write_text(sanitize_text(content, assignments=False), encoding="utf-8")
        redacted.append(relative)
    return redacted


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
        for log_file in logs_dir.rglob(pattern):
            if sanitize_log_file(log_file):
                modified_count += 1

    return modified_count
