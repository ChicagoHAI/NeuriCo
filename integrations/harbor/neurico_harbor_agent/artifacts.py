"""Post-run, run-isolated Harbor artifacts with explicit trust boundaries.

This module does not try to recognize evaluator material by comparing payload
fragments. Eligibility follows NeuriCo's application-level authority contract:
research workers must not access sealed evaluator material, evaluator-owned
producers and paths are private, and explicitly classified worker logs are
public. Private runtime state, unclassified logs, binaries, symlinks, and
credential-like paths are never artifact sources. This is a behavioral trust
model, not an operating-system sandbox. The Harbor supervisor calls the
exporter only after the NeuriCo child has stopped.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import time
from typing import Any, Mapping
from uuid import uuid4

from core.scoring_seal import SEALED_PATHS
from core.security import find_secrets, sanitize_text, sensitive_env_values

from .scratch import EphemeralRunScratch, SCRATCH_MAX_FILE_BYTES


DEFAULT_HARBOR_ARTIFACT_ROOT = Path("/logs/artifacts/neurico")

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FIELD_TOKEN = re.compile(r"[a-z0-9]+")
_ACRONYM_FIELD_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_FIELD_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_LINE_ASSIGNMENT = re.compile(
    r"^(?P<prefix>[ \t]*(?:-[ \t]*)?(?P<quote>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?P=quote)[ \t]*[:=][ \t]*)(?P<value>[^\r\n]*)(?P<newline>\r?\n|$)"
)
_INLINE_ASSIGNMENT = re.compile(
    r"(?P<quote>[\"']?)(?P<key>\b[A-Za-z_][A-Za-z0-9_.-]*)(?P=quote)"
    r"(?P<separator>[ \t]*[:=][ \t]*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
)
_BARE_BEARER_TOKEN = re.compile(
    r"(?i)\bbearer(?P<space>\s+)(?P<token>[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,})"
)
_CREDENTIAL_URI = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)" r"(?P<username>[^\s/:@]+):(?P<password>[^\s/@]+)@"
)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,}" r"(?:\.[A-Za-z0-9_-]{5,}){2,4}(?![A-Za-z0-9_-])"
)
_PATH_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<path>(?:\./|/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
    r"(?![A-Za-z0-9_.-])"
)
_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----", re.I)
_PRIVATE_KEY_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----", re.I)
_REDACTED_VALUE = "[REDACTED_SECRET_FIELD]"
_REDACTED_BEARER = "[REDACTED_BEARER_TOKEN]"
_REDACTED_JWT = "[REDACTED_JSON_WEB_TOKEN]"
_REDACTED_PRIVATE_KEY = "[REDACTED_PRIVATE_KEY_BLOCK]"
_REDACTED_SENSITIVE_PATH = "[REDACTED_SENSITIVE_PATH]"
_REDACTED_URI_CREDENTIALS = "[REDACTED_URI_CREDENTIALS]@"

_PUBLIC_SCORING_PATHS = frozenset({"scoring/interface.md", "scoring/results.json"})
_HIDDEN_EVALUATION_PREFIXES = (
    ".scoring_sealed",
    "data/.test",
    "data/holdout",
    "data/test",
)
_PROVIDER_HOME_DIR_NAMES = frozenset(
    {
        ".aws",
        ".azure",
        ".claude",
        ".codex",
        ".config",
        ".docker",
        ".gemini",
        ".gnupg",
        ".kube",
        ".ssh",
    }
)
_DEPENDENCY_DIR_NAMES = frozenset(
    {
        ".tox",
        ".venv",
        "env",
        "neurico-research-env",
        "node_modules",
        "venv",
    }
)
_CACHE_DIR_NAMES = frozenset(
    {".ipynb_checkpoints", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)
_SECRET_FILE_NAMES = frozenset(
    {
        ".netrc",
        ".npmrc",
        ".pypirc",
        "auth.json",
        "credential",
        "credential.json",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "manager_mcp.json",
        ".envrc",
        "secret",
        "secrets.json",
        "service-account.json",
        "service_account.json",
        "token",
        "tokens.json",
    }
)
_SECRET_FILE_SUFFIXES = (".key", ".kubeconfig", ".p12", ".pem", ".pfx")

# Logs have mixed authority.  A privileged marker always wins.  Everything
# else under logs/ must identify one of these public research producers.
_PRIVILEGED_LOG_MARKERS = (
    "bootstrap_rule_maker",
    "eval_verifier",
    "evaluator",
    "manager",
    "rule-maker",
    "rule_maker",
    "scorer",
    "scoring_verification",
)
_PUBLIC_LOG_PATH_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^logs/(?:hitl/)?resource_finder(?:[._/-]|$)",
        r"^logs/(?:hitl/)?experiment_runner(?:[._/-]|$)",
        r"^logs/(?:hitl/)?execution(?:[._/-]|$)",
        r"^logs/(?:hitl/)?research_prompt\.",
        r"^logs/(?:hitl/)?session_instructions\.",
        r"^logs/(?:hitl/)?comment_handler(?:[._/-]|$)",
        r"^logs/(?:hitl/)?paper_writer(?:[._/-]|$)",
        r"^logs/autoresearch_hitl_experiment(?:[._/-]|$)",
        r"^logs/experiment-autoresearch/",
        r"^logs/dsi-slurm-artifacts/",
        r"^logs/modal_[a-z0-9_-]+_[0-9]{8}_[0-9]{6}\.log$",
    )
)
_PUBLIC_LOG_SUFFIXES = frozenset(
    {".err", ".json", ".jsonl", ".log", ".md", ".out", ".txt", ".yaml", ".yml"}
)
_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".bin",
        ".bz2",
        ".ckpt",
        ".db",
        ".dylib",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".npy",
        ".npz",
        ".o",
        ".parquet",
        ".pkl",
        ".png",
        ".pt",
        ".pth",
        ".pyc",
        ".safetensors",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tiff",
        ".webp",
        ".xz",
        ".zip",
    }
)

_SENSITIVE_EXCLUSION_REASONS = frozenset(
    {
        "binary_payload_not_exportable",
        "credential_like_path",
        "hardlink_not_exportable",
        "provider_home",
        "privileged_evaluation_log",
        "privileged_runtime_material",
        "sealed_evaluation_material",
        "secret_redaction_incomplete",
        "symlink_not_exportable",
        "unclassified_log",
        "unchanged_input",
        "unknown_pre_run_state",
    }
)

_SNAPSHOT_MAX_FILE_BYTES = 64 * 1024 * 1024
_SNAPSHOT_BUDGET_BYTES = 512 * 1024 * 1024
_SNAPSHOT_MIN_FREE_BYTES = 256 * 1024 * 1024
_SNAPSHOT_MAX_CAPTURE_SECONDS = 30.0
_SNAPSHOT_MAX_ENTRIES = 50_000
_BASELINE_MAX_CAPTURE_SECONDS = 10.0
_BASELINE_MAX_ENTRIES = 200_000
_GIT_COMMAND_TIMEOUT_SECONDS = 3.0
_MAX_CREDENTIAL_FILE_BYTES = 4 * 1024 * 1024
_MIN_REDACTABLE_EXACT_SECRET_LENGTH = 4


def _contains_recognizable_secret_value(value: str) -> bool:
    return bool(
        _CREDENTIAL_URI.search(value)
        or _JWT.search(value)
        or _PRIVATE_KEY_BEGIN.search(value)
        or _BARE_BEARER_TOKEN.search(value)
    )


def _sanitize_sensitive_path_references(content: str, redactor: "TraceRedactor") -> str:
    """Withhold a line when its path reference crosses a sensitive boundary."""

    for match in _PATH_REFERENCE.finditer(content):
        rendered = match.group("path")
        # Avoid classifying ordinary prose tokens. Standalone dotfiles and
        # filename-like values remain eligible for the same path policy.
        if "/" not in rendered and not rendered.startswith(".") and "." not in rendered:
            continue
        normalized = rendered.strip("/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized:
            continue
        parts = Path(normalized).parts
        for index in range(len(parts)):
            relative = Path(*parts[index:])
            reason = _path_exclusion_reason(
                relative,
                artifact_relative=None,
                is_directory=False,
                redactor=redactor,
            )
            if reason in _SENSITIVE_EXCLUSION_REASONS:
                newline = (
                    "\r\n" if content.endswith("\r\n") else ("\n" if content.endswith("\n") else "")
                )
                return _REDACTED_SENSITIVE_PATH + newline
    return content


@dataclass(frozen=True)
class WorkspaceBaseline:
    """In-memory pre-run file identities; no workspace payload is retained."""

    fingerprints: dict[str, tuple[int, int, int, int, int, int, int]]
    root_identity: tuple[int, int, int] | None
    complete: bool
    stop_reason: str | None = None


@dataclass(frozen=True)
class TraceRedactor:
    """Parent-only exact secrets used by the existing trace sanitizer."""

    exact_values: tuple[str, ...] = ()

    @classmethod
    def from_sources(
        cls,
        environment: Mapping[str, str],
        *,
        credential_file: Path | None = None,
        additional_values: tuple[str | None, ...] = (),
    ) -> "TraceRedactor":
        values = set(sensitive_env_values(dict(environment)))

        def add_exact_secret(value: Any) -> None:
            rendered = str(value).strip()
            if not rendered:
                return
            if len(rendered) < _MIN_REDACTABLE_EXACT_SECRET_LENGTH:
                raise ValueError("A configured credential is too short for safe trace redaction")
            values.add(rendered)

        for name, value in environment.items():
            if _is_sensitive_field_name(str(name)) or _contains_recognizable_secret_value(
                str(value)
            ):
                add_exact_secret(value)
        for value in additional_values:
            if value is not None:
                add_exact_secret(value)
        if credential_file is not None:
            credential_file = Path(credential_file)
            if credential_file.stat().st_size > _MAX_CREDENTIAL_FILE_BYTES:
                raise ValueError("Codex credential file is too large for safe trace redaction")
            try:
                credential_payload = json.loads(credential_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    "Codex credential file could not establish safe trace redaction"
                ) from error

            def collect_strings(
                value: Any,
                field_name: str | None = None,
                *,
                sensitive_context: bool = False,
            ) -> None:
                current_context = sensitive_context or (
                    field_name is not None and _is_sensitive_field_name(field_name)
                )
                if isinstance(value, Mapping):
                    for key, child in value.items():
                        collect_strings(
                            child,
                            str(key),
                            sensitive_context=current_context,
                        )
                elif isinstance(value, (list, tuple)):
                    for child in value:
                        collect_strings(
                            child,
                            field_name,
                            sensitive_context=current_context,
                        )
                elif isinstance(value, str) and (
                    current_context or _contains_recognizable_secret_value(value)
                ):
                    add_exact_secret(value)

            collect_strings(credential_payload)
        return cls(exact_values=tuple(sorted(values, key=lambda value: (-len(value), value))))

    def sanitize(self, content: str) -> str:
        sanitized = content
        for value in self.exact_values:
            sanitized = sanitized.replace(value, "[REDACTED_CONFIGURED_SECRET]")
        return sanitize_text(sanitized)

    def contains_secret(self, content: str) -> bool:
        return any(value in content for value in self.exact_values) or bool(find_secrets(content))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("Harbor trace run ID must contain only letters, digits, '.', '_' or '-'")


def _directory_identity(directory_stat: os.stat_result) -> tuple[int, int, int]:
    return (
        directory_stat.st_dev,
        directory_stat.st_ino,
        stat.S_IFMT(directory_stat.st_mode),
    )


def _open_trusted_directory(path: Path) -> tuple[int, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(path_stat.st_mode) or not stat.S_ISDIR(opened_stat.st_mode):
            raise OSError("Harbor trace storage path is not a directory")
        if _directory_identity(path_stat) != _directory_identity(opened_stat):
            raise OSError("Harbor trace storage path changed while opening")
        return descriptor, opened_stat
    except BaseException:
        os.close(descriptor)
        raise


def _directory_entry_stat(name: str, descriptor: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _validate_workspace_root(
    workspace: Path,
    baseline: WorkspaceBaseline,
) -> os.stat_result:
    """Reject a workspace path that no longer names the pre-run directory."""
    workspace_stat = os.stat(workspace, follow_symlinks=False)
    if not stat.S_ISDIR(workspace_stat.st_mode):
        raise OSError("Harbor task workspace changed type during the run")
    if baseline.root_identity is not None and (
        _directory_identity(workspace_stat) != baseline.root_identity
    ):
        raise OSError("Harbor task workspace was replaced during the run")
    return workspace_stat


@dataclass
class HarborArtifactStore:
    """Parent-owned directory capability retained across one child run."""

    root: Path
    transaction_root: Path
    root_descriptor: int
    transaction_descriptor: int
    root_identity: tuple[int, int, int]
    transaction_identity: tuple[int, int, int]
    closed: bool = False

    @classmethod
    def open(cls, root: Path) -> "HarborArtifactStore":
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("Harbor trace artifact root must be absolute")
        root.mkdir(parents=True, exist_ok=True)
        root_descriptor, root_stat = _open_trusted_directory(root)
        transaction_descriptor: int | None = None
        transaction_root = root.parent / f".{root.name}.transactions"
        try:
            transaction_root.mkdir(mode=0o700, exist_ok=True)
            transaction_descriptor, transaction_stat = _open_trusted_directory(transaction_root)
            os.fchmod(transaction_descriptor, 0o700)
            transaction_stat = os.fstat(transaction_descriptor)
            if root_stat.st_dev != transaction_stat.st_dev:
                raise OSError(
                    "Harbor trace staging and publication roots use different filesystems"
                )
            return cls(
                root=root,
                transaction_root=transaction_root,
                root_descriptor=root_descriptor,
                transaction_descriptor=transaction_descriptor,
                root_identity=_directory_identity(root_stat),
                transaction_identity=_directory_identity(transaction_stat),
            )
        except BaseException:
            if transaction_descriptor is not None:
                os.close(transaction_descriptor)
            os.close(root_descriptor)
            raise

    def validate(self) -> None:
        if self.closed:
            raise RuntimeError("Harbor trace artifact store is closed")
        for path, descriptor, expected in (
            (self.root, self.root_descriptor, self.root_identity),
            (
                self.transaction_root,
                self.transaction_descriptor,
                self.transaction_identity,
            ),
        ):
            path_stat = os.stat(path, follow_symlinks=False)
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISDIR(path_stat.st_mode):
                raise OSError("Harbor trace storage path changed type during the run")
            if _directory_identity(path_stat) != expected:
                raise OSError("Harbor trace storage path was replaced during the run")
            if _directory_identity(opened_stat) != expected:
                raise OSError("Harbor trace storage capability changed during the run")
        if stat.S_IMODE(os.fstat(self.transaction_descriptor).st_mode) != 0o700:
            raise OSError("Harbor trace transaction root permissions changed during the run")

    def begin(self, run_id: str) -> "HarborRunBundleTransaction":
        _validate_run_id(run_id)
        self.validate()
        reservation_name = f"{run_id}.reservation"
        reservation_descriptor = os.open(
            reservation_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=self.transaction_descriptor,
        )
        os.close(reservation_descriptor)
        staging_name: str | None = None
        try:
            if _directory_entry_stat(run_id, self.root_descriptor) is not None:
                raise FileExistsError(self.root / run_id)
            staging_name = f"{run_id}.staging-{uuid4().hex}"
            os.mkdir(staging_name, mode=0o700, dir_fd=self.transaction_descriptor)
            staging_stat = os.stat(
                staging_name,
                dir_fd=self.transaction_descriptor,
                follow_symlinks=False,
            )
            return HarborRunBundleTransaction(
                store=self,
                run_id=run_id,
                staging_name=staging_name,
                staging_dir=self.transaction_root / staging_name,
                final_dir=self.root / run_id,
                reservation_name=reservation_name,
                staging_identity=_directory_identity(staging_stat),
            )
        except BaseException:
            if staging_name is not None:
                staging_path = self.transaction_root / staging_name
                try:
                    staging_stat = _directory_entry_stat(
                        staging_name,
                        self.transaction_descriptor,
                    )
                    if staging_stat is not None and stat.S_ISDIR(staging_stat.st_mode):
                        shutil.rmtree(staging_path)
                except OSError:
                    pass
            try:
                os.unlink(reservation_name, dir_fd=self.transaction_descriptor)
            except OSError:
                pass
            raise

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for descriptor in (self.transaction_descriptor, self.root_descriptor):
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class HarborRunBundleTransaction:
    """Build one complete bundle privately, then publish it with one rename."""

    store: HarborArtifactStore
    run_id: str
    staging_name: str
    staging_dir: Path
    final_dir: Path
    reservation_name: str
    staging_identity: tuple[int, int, int]
    committed: bool = False

    def _validate_staging(self) -> None:
        self.store.validate()
        staging_stat = _directory_entry_stat(
            self.staging_name,
            self.store.transaction_descriptor,
        )
        if staging_stat is None or not stat.S_ISDIR(staging_stat.st_mode):
            raise OSError("Harbor trace staging directory is missing or changed type")
        if _directory_identity(staging_stat) != self.staging_identity:
            raise OSError("Harbor trace staging directory was replaced")

    def _remove_reservation(self) -> None:
        try:
            os.unlink(self.reservation_name, dir_fd=self.store.transaction_descriptor)
        except OSError:
            pass

    def reset(self) -> Path:
        """Discard an incomplete bundle and return a fresh private staging tree."""
        if self.committed:
            raise RuntimeError("Cannot reset a published Harbor run bundle")
        self._validate_staging()
        shutil.rmtree(self.staging_dir)
        os.mkdir(
            self.staging_name,
            mode=0o700,
            dir_fd=self.store.transaction_descriptor,
        )
        staging_stat = os.stat(
            self.staging_name,
            dir_fd=self.store.transaction_descriptor,
            follow_symlinks=False,
        )
        self.staging_identity = _directory_identity(staging_stat)
        return self.staging_dir

    def commit(self) -> Path:
        """Atomically make the completed staging tree visible as this run."""
        if self.committed:
            return self.final_dir
        self._validate_staging()
        if _directory_entry_stat(self.run_id, self.store.root_descriptor) is not None:
            raise FileExistsError(self.final_dir)
        os.rename(
            self.staging_name,
            self.run_id,
            src_dir_fd=self.store.transaction_descriptor,
            dst_dir_fd=self.store.root_descriptor,
        )
        self.committed = True
        self._remove_reservation()
        return self.final_dir

    def abort(self) -> None:
        """Best-effort removal of an unpublished transaction."""
        if not self.committed:
            try:
                self._validate_staging()
            except OSError:
                pass
            else:
                shutil.rmtree(self.staging_dir, ignore_errors=True)
        self._remove_reservation()


def _field_tokens(field_name: str) -> tuple[str, ...]:
    separated = _ACRONYM_FIELD_BOUNDARY.sub(r"\1_\2", field_name)
    separated = _CAMEL_FIELD_BOUNDARY.sub(r"\1_\2", separated)
    return tuple(_FIELD_TOKEN.findall(separated.lower()))


def _is_sensitive_field_name(field_name: str) -> bool:
    tokens = _field_tokens(field_name)
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & {"authorization", "cookie", "credential", "credentials", "password", "passwd"}:
        return True
    if "secret" in token_set:
        return True
    if "auth" in token_set or tokens == ("dsn",) or tokens == ("key",) or tokens == ("pat",):
        return True
    adjacent_pairs = set(zip(tokens, tokens[1:]))
    if adjacent_pairs & {
        ("access", "key"),
        ("api", "key"),
        ("client", "secret"),
        ("connection", "string"),
        ("private", "key"),
        ("refresh", "token"),
        ("session", "token"),
    }:
        return True
    if "token" in token_set or "tokens" in token_set:
        non_secret_token_metadata = {
            "budget",
            "completion",
            "count",
            "estimated",
            "input",
            "limit",
            "max",
            "min",
            "output",
            "prompt",
            "remaining",
            "total",
            "usage",
            "used",
        }
        return not bool(token_set & non_secret_token_metadata)
    if tokens[-1] == "key" and token_set & {"access", "api", "private"}:
        return True
    return False


def _sanitize_free_text(content: str, redactor: TraceRedactor) -> str:
    sanitized = redactor.sanitize(content)
    rendered_lines: list[str] = []
    sensitive_block_indent: int | None = None
    private_key_block = False
    for line in sanitized.splitlines(keepends=True):
        newline = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        if private_key_block:
            if _PRIVATE_KEY_END.search(line):
                private_key_block = False
            rendered_lines.append(newline)
            continue
        if sensitive_block_indent is not None:
            if not line.strip():
                rendered_lines.append(newline)
                continue
            indentation = len(line) - len(line.lstrip(" \t"))
            if indentation > sensitive_block_indent:
                rendered_lines.append(newline)
                continue
            sensitive_block_indent = None
        private_key_begin = _PRIVATE_KEY_BEGIN.search(line)
        if private_key_begin is not None:
            rendered_lines.append(_REDACTED_PRIVATE_KEY + newline)
            if _PRIVATE_KEY_END.search(line, private_key_begin.end()) is None:
                private_key_block = True
            continue
        match = _LINE_ASSIGNMENT.match(line)
        if match and _is_sensitive_field_name(match.group("key")):
            rendered_lines.append(match.group("prefix") + _REDACTED_VALUE + match.group("newline"))
            raw_value = match.group("value").strip()
            if not raw_value or raw_value.startswith(("|", ">")):
                sensitive_block_indent = len(line) - len(line.lstrip(" \t"))
            continue
        sensitive_match = next(
            (
                inline_match
                for inline_match in _INLINE_ASSIGNMENT.finditer(line)
                if _is_sensitive_field_name(inline_match.group("key"))
                and not inline_match.group("value").lstrip("\"'").startswith("[REDACTED")
            ),
            None,
        )
        if sensitive_match is not None:
            # Free-form text has no reliable delimiter after an unquoted
            # sensitive value. Redact the remainder rather than preserving a
            # possible token continuation.
            rendered_lines.append(
                line[: sensitive_match.start("value")] + _REDACTED_VALUE + newline
            )
            continue
        rendered_lines.append(
            _sanitize_sensitive_path_references(
                _JWT.sub(
                    _REDACTED_JWT,
                    _CREDENTIAL_URI.sub(
                        lambda credential: (credential.group("scheme") + _REDACTED_URI_CREDENTIALS),
                        _BARE_BEARER_TOKEN.sub(
                            lambda bearer: f"Bearer{bearer.group('space')}{_REDACTED_BEARER}",
                            line,
                        ),
                    ),
                ),
                redactor,
            )
        )
    return "".join(rendered_lines)


def _sanitize_serializable(
    value: Any,
    *,
    redactor: TraceRedactor,
    field_name: str | None = None,
    redact_sensitive_fields: bool = True,
) -> Any:
    if redact_sensitive_fields and field_name is not None and _is_sensitive_field_name(field_name):
        return _REDACTED_VALUE
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            rendered_key = _sanitize_free_text(str(key), redactor)
            if _REDACTED_SENSITIVE_PATH in rendered_key:
                continue
            sanitized[rendered_key] = _sanitize_serializable(
                child,
                redactor=redactor,
                field_name=rendered_key,
                redact_sensitive_fields=redact_sensitive_fields,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_serializable(
                child,
                redactor=redactor,
                redact_sensitive_fields=redact_sensitive_fields,
            )
            for child in value
        ]
    if isinstance(value, str):
        return _sanitize_free_text(value, redactor)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_free_text(str(value), redactor)


def _sanitize_trace_text(
    content: str,
    suffix: str,
    redactor: TraceRedactor,
    *,
    redact_sensitive_fields: bool = True,
) -> str:
    suffix = suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            pass
        else:
            return (
                json.dumps(
                    _sanitize_serializable(
                        parsed,
                        redactor=redactor,
                        redact_sensitive_fields=redact_sensitive_fields,
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    if suffix == ".jsonl":
        rendered_lines: list[str] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                break
            rendered_lines.append(
                json.dumps(
                    _sanitize_serializable(
                        parsed,
                        redactor=redactor,
                        redact_sensitive_fields=redact_sensitive_fields,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            return ("\n".join(rendered_lines) + "\n") if rendered_lines else ""
    return _sanitize_free_text(content, redactor)


def _contains_unredacted_sensitive_material(content: str) -> bool:
    if _contains_recognizable_secret_value(content):
        return True
    for match in _INLINE_ASSIGNMENT.finditer(content):
        if not _is_sensitive_field_name(match.group("key")):
            continue
        if not match.group("value").lstrip("\"'").startswith("[REDACTED"):
            return True
    return False


def _decode_text_payload(payload: bytes) -> str | None:
    if b"\x00" in payload:
        return None
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(character) < 32 and character not in "\t\n\r\f" for character in content):
        return None
    return content


def _safe_text_payload(
    payload: bytes,
    suffix: str,
    redactor: TraceRedactor,
    *,
    redact_sensitive_fields: bool = True,
) -> tuple[bytes, bool] | None:
    content = _decode_text_payload(payload)
    if content is None:
        return None
    sanitized = _sanitize_trace_text(
        content,
        suffix,
        redactor,
        redact_sensitive_fields=redact_sensitive_fields,
    )
    if redactor.contains_secret(sanitized) or (
        redact_sensitive_fields and _contains_unredacted_sensitive_material(sanitized)
    ):
        return None
    rendered = sanitized.encode("utf-8")
    return rendered, rendered != payload


def _write_sanitized_text(
    destination: Path,
    content: str,
    *,
    redactor: TraceRedactor,
    suffix: str | None = None,
    redact_sensitive_fields: bool = True,
) -> bool:
    safe_payload = _safe_text_payload(
        content.encode("utf-8"),
        suffix or destination.suffix,
        redactor,
        redact_sensitive_fields=redact_sensitive_fields,
    )
    if safe_payload is None:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_bytes(safe_payload[0])
        os.replace(temporary, destination)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _write_json(
    destination: Path,
    value: Any,
    *,
    redactor: TraceRedactor,
) -> tuple[str, int]:
    content = (
        json.dumps(
            _sanitize_serializable(
                value,
                redactor=redactor,
                redact_sensitive_fields=False,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if not _write_sanitized_text(
        destination,
        content,
        redactor=redactor,
        suffix=".json",
        redact_sensitive_fields=False,
    ):
        raise ValueError(f"Generated artifact metadata could not be sanitized: {destination.name}")
    safe_payload = _safe_text_payload(
        content.encode("utf-8"),
        ".json",
        redactor,
        redact_sensitive_fields=False,
    )
    if safe_payload is None:
        raise ValueError(f"Generated artifact metadata could not be hashed: {destination.name}")
    return sha256(safe_payload[0]).hexdigest(), len(safe_payload[0])


def _normalized(relative: Path) -> str:
    return relative.as_posix().strip("/").lower()


def _is_sealed_path(relative: Path) -> bool:
    normalized = _normalized(relative)
    parts = tuple(part.lower() for part in relative.parts)
    if ".scoring_sealed" in parts:
        return True
    if any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _HIDDEN_EVALUATION_PREFIXES
    ):
        return True
    for sealed_path in SEALED_PATHS:
        prefix = sealed_path.rstrip("/").lower()
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            return True
    return normalized.startswith("scoring/") and normalized not in _PUBLIC_SCORING_PATHS


def _is_credential_path(relative: Path, redactor: TraceRedactor) -> bool:
    name = relative.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or any(part.lower() == ".direnv" for part in relative.parts)
        or name in _SECRET_FILE_NAMES
        or name.startswith(("credential", "secret", "service-account", "service_account"))
        or name.startswith(("token.", "token_", "tokens.", "tokens_"))
        or name.endswith(_SECRET_FILE_SUFFIXES)
        or _is_sensitive_field_name(Path(name).stem)
        or redactor.sanitize(relative.as_posix()) != relative.as_posix()
    )


def _log_exclusion_reason(relative: Path, *, is_directory: bool) -> str | None:
    normalized = _normalized(relative)
    if any(marker in normalized for marker in _PRIVILEGED_LOG_MARKERS):
        return "privileged_evaluation_log"
    if is_directory:
        return None
    if relative.suffix.lower() not in _PUBLIC_LOG_SUFFIXES:
        return "unclassified_log"
    if any(pattern.match(normalized) for pattern in _PUBLIC_LOG_PATH_PATTERNS):
        return None
    return "unclassified_log"


def _path_exclusion_reason(
    relative: Path,
    *,
    artifact_relative: Path | None,
    is_directory: bool,
    redactor: TraceRedactor,
) -> str | None:
    normalized = _normalized(relative)
    parts = tuple(part.lower() for part in relative.parts)
    if artifact_relative is not None:
        artifact_container = artifact_relative.parent
        if relative == artifact_relative or artifact_relative in relative.parents:
            return "artifact_output"
        if artifact_container.parts and (
            relative == artifact_container or artifact_container in relative.parents
        ):
            return "artifact_output"
    if _is_sealed_path(relative):
        return "sealed_evaluation_material"
    if _is_credential_path(relative, redactor):
        return "credential_like_path"
    if ".git" in parts:
        return "git_object_database"
    if any(part in _PROVIDER_HOME_DIR_NAMES for part in parts):
        return "provider_home"
    if any(part in _DEPENDENCY_DIR_NAMES for part in parts):
        return "dependency_environment"
    if any(part in _CACHE_DIR_NAMES for part in parts):
        return "dependency_cache"
    if normalized == ".neurico" or normalized.startswith(".neurico/"):
        return "privileged_runtime_material"
    if normalized == "logs" and is_directory:
        return None
    if normalized.startswith("logs/"):
        return _log_exclusion_reason(relative, is_directory=is_directory)
    if not is_directory and relative.suffix.lower() in _BINARY_SUFFIXES:
        return "binary_payload_not_exportable"
    if relative.name.lower().endswith((".lock", ".sock", ".tmp")):
        return "live_runtime_control"
    return None


def _artifact_relative_to_workspace(workspace: Path, artifact_dir: Path) -> Path | None:
    try:
        return artifact_dir.resolve().relative_to(workspace.resolve())
    except ValueError:
        return None


def _record_exclusion(
    summary: dict[str, dict[str, int | bool]],
    public_entries: list[dict[str, Any]],
    *,
    reason: str,
    relative: Path,
    entry_type: str,
    byte_count: int = 0,
) -> None:
    # Do not let a trace prove that a sensitive entry exists, how many such
    # entries exist, or which sensitive class was encountered. The static
    # policy documents what is ineligible; per-run records contain only public
    # exclusions whose paths and counts are safe to disclose.
    if reason in _SENSITIVE_EXCLUSION_REASONS:
        return
    record = summary.setdefault(reason, {"entries": 0, "known_bytes": 0})
    record["entries"] = int(record["entries"]) + 1
    record["known_bytes"] = int(record.get("known_bytes", 0)) + max(0, byte_count)
    entry: dict[str, Any] = {
        "path": relative.as_posix(),
        "reason": reason,
        "type": entry_type,
    }
    if entry_type == "file":
        entry["bytes"] = max(0, byte_count)
    public_entries.append(entry)


def _stat_fingerprint(
    source_stat: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
        stat.S_IMODE(source_stat.st_mode),
        source_stat.st_nlink,
    )


def _same_opened_identity(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        stat.S_IFMT(before.st_mode),
    ) == (
        after.st_dev,
        after.st_ino,
        stat.S_IFMT(after.st_mode),
    )


def _open_verified_component(
    parent_descriptor: int,
    name: str,
    *,
    directory: bool,
) -> tuple[int, os.stat_result]:
    """Open one child without trusting a path lookup that can later change."""
    before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(before.st_mode):
        raise OSError("workspace capture path changed type")
    if not directory and before.st_nlink != 1:
        raise OSError("workspace capture refuses hard-linked files")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    else:
        flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        if not expected(opened.st_mode) or not _same_opened_identity(before, opened):
            raise OSError("workspace capture path changed while opening")
        if not directory and opened.st_nlink != 1:
            raise OSError("workspace capture refuses hard-linked files")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _open_workspace_regular_file(
    workspace: Path,
    expected_workspace_stat: os.stat_result,
    relative: Path,
) -> tuple[int, os.stat_result]:
    """Open a regular file beneath the fixed workspace descriptor."""
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError("invalid workspace-relative capture path")
    root_before = workspace.stat(follow_symlinks=False)
    if not stat.S_ISDIR(root_before.st_mode) or not _same_opened_identity(
        expected_workspace_stat,
        root_before,
    ):
        raise OSError("workspace root changed during capture")
    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_descriptor = os.open(workspace, root_flags)
    try:
        opened_root = os.fstat(directory_descriptor)
        if not _same_opened_identity(root_before, opened_root):
            raise OSError("workspace root changed while opening")
        for part in parts[:-1]:
            next_descriptor, _opened = _open_verified_component(
                directory_descriptor,
                part,
                directory=True,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        return _open_verified_component(
            directory_descriptor,
            parts[-1],
            directory=False,
        )
    finally:
        os.close(directory_descriptor)


def _read_open_regular_file(
    descriptor: int,
    opened_stat: os.stat_result,
    maximum_bytes: int,
) -> tuple[bytes, os.stat_result]:
    """Read one already-validated descriptor and reject concurrent mutation."""
    payload_parts: list[bytes] = []
    bytes_read = 0
    while bytes_read <= maximum_bytes:
        chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - bytes_read))
        if not chunk:
            break
        payload_parts.append(chunk)
        bytes_read += len(chunk)
    if bytes_read > maximum_bytes:
        raise OverflowError("file grew beyond the capture limit")
    final_stat = os.fstat(descriptor)
    if final_stat.st_nlink != 1 or _stat_fingerprint(final_stat) != _stat_fingerprint(opened_stat):
        raise OSError("workspace file changed during capture")
    return b"".join(payload_parts), final_stat


def _read_open_regular_file_prefix(
    descriptor: int,
    opened_stat: os.stat_result,
    maximum_bytes: int,
) -> tuple[bytes, os.stat_result, bool]:
    """Read a stable bounded prefix for private scratch retention."""
    payload_parts: list[bytes] = []
    bytes_read = 0
    while bytes_read < maximum_bytes:
        chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes - bytes_read))
        if not chunk:
            break
        payload_parts.append(chunk)
        bytes_read += len(chunk)
    final_stat = os.fstat(descriptor)
    if final_stat.st_nlink != 1 or _stat_fingerprint(final_stat) != _stat_fingerprint(opened_stat):
        raise OSError("workspace file changed during scratch capture")
    return b"".join(payload_parts), final_stat, final_stat.st_size > bytes_read


def _retain_private_scratch_file(
    *,
    scratch: EphemeralRunScratch | None,
    workspace: Path,
    expected_workspace_stat: os.stat_result,
    relative: Path,
    source_stat: os.stat_result,
) -> None:
    """Best-effort raw retention that cannot affect the public collection."""
    if scratch is None:
        return
    descriptor: int | None = None
    try:
        descriptor, opened_stat = _open_workspace_regular_file(
            workspace,
            expected_workspace_stat,
            relative,
        )
        if _stat_fingerprint(opened_stat) != _stat_fingerprint(source_stat):
            raise OSError("workspace file changed before scratch capture")
        payload, _final_stat, truncated = _read_open_regular_file_prefix(
            descriptor,
            opened_stat,
            SCRATCH_MAX_FILE_BYTES,
        )
        _retain_private_scratch_payload(
            scratch=scratch,
            relative=relative,
            payload=payload,
            source_truncated=truncated,
        )
    except (OSError, ValueError):
        # Scratch is private, observational, and intentionally absent from the
        # public collection report. Its own metadata records write failures.
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _retain_private_scratch_payload(
    *,
    scratch: EphemeralRunScratch | None,
    relative: Path,
    payload: bytes,
    source_truncated: bool = False,
) -> None:
    if scratch is None:
        return
    try:
        scratch.preserve_workspace_file(
            relative,
            payload,
            source_truncated=source_truncated,
        )
    except Exception:
        return


def capture_workspace_baseline(
    workspace: Path,
    *,
    redactor: TraceRedactor | None = None,
) -> WorkspaceBaseline:
    """Inventory pre-run file identities in memory without reading payloads."""
    redactor = redactor or TraceRedactor()
    workspace = workspace.absolute()
    workspace_descriptor, workspace_stat = _open_trusted_directory(workspace)
    os.close(workspace_descriptor)
    deadline = time.monotonic() + _BASELINE_MAX_CAPTURE_SECONDS
    fingerprints: dict[str, tuple[int, int, int, int, int, int, int]] = {}
    complete = True
    stop_reason: str | None = None

    def record_walk_error(_error: OSError) -> None:
        nonlocal complete, stop_reason
        complete = False
        stop_reason = stop_reason or "filesystem_error"

    for directory, directory_names, file_names in os.walk(
        workspace,
        followlinks=False,
        onerror=record_walk_error,
    ):
        if time.monotonic() >= deadline:
            complete = False
            stop_reason = "capture_time_budget_exhausted"
            break
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = directory_path / name
            relative = candidate.relative_to(workspace)
            if (
                _path_exclusion_reason(
                    relative,
                    artifact_relative=None,
                    is_directory=True,
                    redactor=redactor,
                )
                is not None
            ):
                continue
            if candidate.is_symlink():
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            if time.monotonic() >= deadline:
                complete = False
                stop_reason = "capture_time_budget_exhausted"
                break
            if len(fingerprints) >= _BASELINE_MAX_ENTRIES:
                complete = False
                stop_reason = "entry_budget_exhausted"
                break
            source = directory_path / name
            relative = source.relative_to(workspace)
            reason = _path_exclusion_reason(
                relative,
                artifact_relative=None,
                is_directory=False,
                redactor=redactor,
            )
            # Selected policy-limited inputs retain only in-memory identities so
            # final collection can distinguish unchanged benchmark material
            # from a newly generated artifact without reading either payload.
            if reason is not None and reason not in {
                "binary_payload_not_exportable",
                "unclassified_log",
            }:
                continue
            if source.is_symlink():
                continue
            try:
                source_stat = source.lstat()
            except OSError:
                complete = False
                stop_reason = stop_reason or "filesystem_error"
                continue
            if stat.S_ISREG(source_stat.st_mode):
                fingerprints[relative.as_posix()] = _stat_fingerprint(source_stat)
        if not complete and stop_reason in {
            "capture_time_budget_exhausted",
            "entry_budget_exhausted",
        }:
            break

    try:
        final_workspace_stat = os.stat(workspace, follow_symlinks=False)
    except OSError:
        complete = False
        stop_reason = stop_reason or "filesystem_error"
    else:
        if _directory_identity(final_workspace_stat) != _directory_identity(workspace_stat):
            complete = False
            stop_reason = stop_reason or "filesystem_error"

    return WorkspaceBaseline(
        fingerprints=fingerprints,
        root_identity=_directory_identity(workspace_stat),
        complete=complete,
        stop_reason=stop_reason,
    )


def capture_workspace_snapshot(
    *,
    workspace: Path,
    artifact_dir: Path,
    baseline: WorkspaceBaseline,
    redactor: TraceRedactor | None = None,
    scratch: EphemeralRunScratch | None = None,
    phase: str = "final",
) -> dict[str, Any]:
    """Copy eligible final public text into one sanitized workspace tree."""
    redactor = redactor or TraceRedactor()
    if phase != "final":
        raise ValueError("Harbor trace snapshots are post-run only")
    started = time.monotonic()
    deadline = started + _SNAPSHOT_MAX_CAPTURE_SECONDS
    workspace = workspace.absolute()
    expected_workspace_stat = _validate_workspace_root(workspace, baseline)
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    files_root = artifact_dir / "workspace/files"
    artifact_relative = _artifact_relative_to_workspace(workspace, artifact_dir)

    files: list[dict[str, Any]] = []
    exclusions: dict[str, dict[str, int | bool]] = {}
    public_exclusions: list[dict[str, Any]] = []
    error_counts: Counter[str] = Counter()
    visited_entries = 0
    examined_public_files = 0
    captured_bytes = 0
    capture_complete = baseline.complete
    stop_reason: str | None = None
    incomplete_reasons: list[str] = []
    if not baseline.complete:
        incomplete_reasons.append("pre_run_inventory_incomplete")

    def mark_incomplete(reason: str, *, stopped: bool = False) -> None:
        nonlocal capture_complete, stop_reason
        capture_complete = False
        if reason not in incomplete_reasons:
            incomplete_reasons.append(reason)
        if stopped and stop_reason is None:
            stop_reason = reason

    def record_capture_error(error: OSError) -> None:
        mark_incomplete("filesystem_error")
        error_counts[type(error).__name__] += 1

    for directory, directory_names, file_names in os.walk(
        workspace,
        followlinks=False,
        onerror=record_capture_error,
    ):
        if time.monotonic() >= deadline:
            mark_incomplete("capture_time_budget_exhausted", stopped=True)
            break
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            if visited_entries >= _SNAPSHOT_MAX_ENTRIES:
                mark_incomplete("entry_budget_exhausted", stopped=True)
                directory_names[:] = []
                break
            visited_entries += 1
            candidate = directory_path / name
            relative = candidate.relative_to(workspace)
            reason = _path_exclusion_reason(
                relative,
                artifact_relative=artifact_relative,
                is_directory=True,
                redactor=redactor,
            )
            if reason is not None:
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason=reason,
                    relative=relative,
                    entry_type="directory",
                )
                continue
            if candidate.is_symlink():
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="symlink_not_exportable",
                    relative=relative,
                    entry_type="symlink",
                )
                continue
            retained_directories.append(name)
        if stop_reason == "entry_budget_exhausted":
            break
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            if time.monotonic() >= deadline:
                mark_incomplete("capture_time_budget_exhausted", stopped=True)
                break
            if visited_entries >= _SNAPSHOT_MAX_ENTRIES:
                mark_incomplete("entry_budget_exhausted", stopped=True)
                break
            visited_entries += 1
            source = directory_path / name
            relative = source.relative_to(workspace)
            reason = _path_exclusion_reason(
                relative,
                artifact_relative=artifact_relative,
                is_directory=False,
                redactor=redactor,
            )
            # Reject all sensitive path classes before even asking the
            # filesystem for entry metadata.  In particular, a permission
            # error must not turn a sealed path into observable error data.
            if reason in _SENSITIVE_EXCLUSION_REASONS and reason not in {
                "binary_payload_not_exportable",
                "unclassified_log",
            }:
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason=reason,
                    relative=relative,
                    entry_type="file",
                )
                continue
            if source.is_symlink():
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="symlink_not_exportable",
                    relative=relative,
                    entry_type="symlink",
                )
                continue
            try:
                source_stat = source.lstat()
            except OSError as error:
                record_capture_error(error)
                continue
            if reason is not None and reason not in {
                "binary_payload_not_exportable",
                "unclassified_log",
            }:
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason=reason,
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            if not stat.S_ISREG(source_stat.st_mode):
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="non_regular_file",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            if reason in {"binary_payload_not_exportable", "unclassified_log"}:
                baseline_fingerprint = baseline.fingerprints.get(relative.as_posix())
                if baseline_fingerprint != _stat_fingerprint(source_stat):
                    mark_incomplete(
                        "public_binary_payload_withheld"
                        if reason == "binary_payload_not_exportable"
                        else "unclassified_log_withheld"
                    )
                    if baseline_fingerprint is not None or baseline.complete:
                        _retain_private_scratch_file(
                            scratch=scratch,
                            workspace=workspace,
                            expected_workspace_stat=expected_workspace_stat,
                            relative=relative,
                            source_stat=source_stat,
                        )
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason=reason,
                    relative=relative,
                    entry_type="file",
                )
                continue
            if source_stat.st_nlink > 1:
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="hardlink_not_exportable",
                    relative=relative,
                    entry_type="file",
                )
                continue
            examined_public_files += 1
            baseline_fingerprint = baseline.fingerprints.get(relative.as_posix())
            if baseline_fingerprint == _stat_fingerprint(source_stat):
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="unchanged_input",
                    relative=relative,
                    entry_type="file",
                )
                continue
            if baseline_fingerprint is None and not baseline.complete:
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="unknown_pre_run_state",
                    relative=relative,
                    entry_type="file",
                )
                continue
            if source_stat.st_size > _SNAPSHOT_MAX_FILE_BYTES:
                mark_incomplete("file_size_limit")
                _retain_private_scratch_file(
                    scratch=scratch,
                    workspace=workspace,
                    expected_workspace_stat=expected_workspace_stat,
                    relative=relative,
                    source_stat=source_stat,
                )
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="file_size_limit",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            descriptor: int | None = None
            try:
                descriptor, opened_stat = _open_workspace_regular_file(
                    workspace,
                    expected_workspace_stat,
                    relative,
                )
                if _stat_fingerprint(opened_stat) != _stat_fingerprint(source_stat):
                    raise OSError("workspace file changed before capture")
                payload, opened_stat = _read_open_regular_file(
                    descriptor,
                    opened_stat,
                    _SNAPSHOT_MAX_FILE_BYTES,
                )
            except OverflowError:
                mark_incomplete("file_size_limit")
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="file_size_limit",
                    relative=relative,
                    entry_type="file",
                    byte_count=source_stat.st_size,
                )
                continue
            except OSError as error:
                record_capture_error(error)
                continue
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            safe_payload = _safe_text_payload(payload, relative.suffix, redactor)
            if safe_payload is None:
                reason = (
                    "binary_payload_not_exportable"
                    if _decode_text_payload(payload) is None
                    else "secret_redaction_incomplete"
                )
                mark_incomplete(
                    "public_binary_payload_withheld"
                    if reason == "binary_payload_not_exportable"
                    else "public_text_redaction_failed"
                )
                _retain_private_scratch_payload(
                    scratch=scratch,
                    relative=relative,
                    payload=payload,
                )
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason=reason,
                    relative=relative,
                    entry_type="file",
                )
                continue
            rendered, redacted = safe_payload
            if captured_bytes + len(rendered) > _SNAPSHOT_BUDGET_BYTES:
                mark_incomplete("snapshot_byte_budget")
                _retain_private_scratch_payload(
                    scratch=scratch,
                    relative=relative,
                    payload=payload,
                )
                _record_exclusion(
                    exclusions,
                    public_exclusions,
                    reason="snapshot_byte_budget",
                    relative=relative,
                    entry_type="file",
                    byte_count=opened_stat.st_size,
                )
                continue
            if shutil.disk_usage(artifact_dir).free - len(rendered) < _SNAPSHOT_MIN_FREE_BYTES:
                mark_incomplete("minimum_free_space_reached", stopped=True)
                _retain_private_scratch_payload(
                    scratch=scratch,
                    relative=relative,
                    payload=payload,
                )
                break
            destination = files_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(rendered)
            captured_bytes += len(rendered)
            file_record = {
                "path": relative.as_posix(),
                "artifact": destination.relative_to(artifact_dir).as_posix(),
                "captured_bytes": len(rendered),
                "sha256": sha256(rendered).hexdigest(),
                "redacted": redacted,
                "mode": oct(stat.S_IMODE(opened_stat.st_mode)),
                "mtime_ns": opened_stat.st_mtime_ns,
            }
            if redacted:
                file_record["source_metadata_withheld"] = True
            else:
                file_record["source_bytes"] = opened_stat.st_size
            files.append(file_record)
        if stop_reason in {
            "capture_time_budget_exhausted",
            "entry_budget_exhausted",
            "minimum_free_space_reached",
        }:
            break

    # A replacement after the last file read must fail the whole transaction,
    # not leave a seemingly complete snapshot of a different directory.
    _validate_workspace_root(workspace, baseline)

    snapshot = {
        "schema_version": 5,
        "phase": "final",
        "generated_at": _utc_now(),
        "policy": {
            "timing": "after_supervised_process_stop",
            "eligibility": "producer_and_path_classification",
            "provenance": "new_or_changed_since_parent_inventory",
            "payloads": "sanitized_utf8_text_only",
            "sensitive_exclusions": "not_enumerated",
        },
        "baseline_complete": baseline.complete,
        "baseline_stop_reason": baseline.stop_reason,
        "capture_complete": capture_complete,
        "capture_stop_reason": stop_reason,
        "capture_incomplete_reasons": sorted(incomplete_reasons),
        "examined_public_files": examined_public_files,
        "captured_bytes": captured_bytes,
        "files": files,
        "exclusion_summary": dict(sorted(exclusions.items())),
        "public_exclusions": public_exclusions,
        "errors": [
            {"type": error_type, "count": count}
            for error_type, count in sorted(error_counts.items())
        ],
    }
    snapshot_sha256, _snapshot_bytes = _write_json(
        artifact_dir / "workspace/snapshot.json",
        snapshot,
        redactor=redactor,
    )
    snapshot["_artifact_sha256"] = snapshot_sha256
    return snapshot


def _runtime_inventory() -> dict[str, Any]:
    components: dict[str, str] = {}
    for distribution in ("neurico", "neurico-harbor-agent"):
        try:
            components[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            continue
    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "components": components,
    }


def _git_output(repository: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(repository),
                *arguments,
            ],
            capture_output=True,
            check=False,
            env={
                "GIT_CONFIG_NOSYSTEM": "1",
                "LC_ALL": "C",
                "PATH": os.environ.get("PATH", os.defpath),
            },
            text=True,
            timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def verify_trace_bundle(*, artifact_dir: Path) -> dict[str, Any]:
    """Verify manifest membership and hashes for accidental-corruption checks."""
    artifact_dir = Path(artifact_dir)
    run_id = artifact_dir.name
    _validate_run_id(run_id)
    artifact_dir_stat = artifact_dir.lstat()
    if not stat.S_ISDIR(artifact_dir_stat.st_mode):
        raise OSError("Collected Harbor trace run path is not a directory")
    manifest_path = artifact_dir / "manifest.json"
    manifest_stat = manifest_path.lstat()
    if not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_nlink != 1:
        raise OSError("Collected Harbor trace manifest is not a private regular file")
    manifest_payload = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_payload)
    except json.JSONDecodeError as error:
        raise ValueError("Collected Harbor trace manifest is invalid JSON") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 4
        or manifest.get("run_id") != run_id
        or manifest.get("collection_status") not in {"scope_complete", "partial", "minimal"}
    ):
        raise ValueError("Collected Harbor trace manifest contract is invalid")
    file_records = manifest.get("files")
    if not isinstance(file_records, list):
        raise ValueError("Collected Harbor trace manifest has no file records")
    expected: dict[str, tuple[int, str]] = {}
    for record in file_records:
        if not isinstance(record, Mapping):
            raise ValueError("Collected Harbor trace manifest contains an invalid file record")
        relative = str(record.get("path", ""))
        byte_count = record.get("bytes")
        digest = str(record.get("sha256", ""))
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or not isinstance(byte_count, int)
            or byte_count < 0
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in expected
        ):
            raise ValueError("Collected Harbor trace manifest contains an unsafe file record")
        expected[relative] = (byte_count, digest)

    actual: set[str] = set()
    for path in sorted(artifact_dir.rglob("*")):
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise OSError("Collected Harbor trace contains a symlink")
        if stat.S_ISDIR(path_stat.st_mode):
            continue
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
            raise OSError("Collected Harbor trace contains a non-private file")
        relative = path.relative_to(artifact_dir).as_posix()
        if relative == "manifest.json":
            continue
        actual.add(relative)
        expected_record = expected.get(relative)
        if expected_record is None:
            raise ValueError("Collected Harbor trace contains a file absent from its manifest")
        payload = path.read_bytes()
        if (len(payload), sha256(payload).hexdigest()) != expected_record:
            raise ValueError("Collected Harbor trace member does not match its manifest")
    if actual != set(expected):
        raise ValueError("Collected Harbor trace is missing a manifest member")
    return manifest


def _write_git_summary(
    repository: Path,
    destination: Path,
    *,
    redactor: TraceRedactor,
    include_worktree_state: bool = True,
) -> dict[str, Any]:
    head = _git_output(repository, "rev-parse", "HEAD")
    summary = {
        "available": head is not None,
        "head": head,
    }
    if include_worktree_state:
        status = _git_output(repository, "status", "--porcelain=v1", "--untracked-files=all")
        summary.update(
            {
                "dirty": bool(status) if status is not None else None,
                "changed_entry_count": len(status.splitlines()) if status else 0,
            }
        )
    summary_sha256, _summary_bytes = _write_json(destination, summary, redactor=redactor)
    summary["_artifact_sha256"] = summary_sha256
    return summary


def _artifact_manifest(
    artifact_dir: Path,
    *,
    expected_hashes: Mapping[str, str],
    redactor: TraceRedactor,
) -> list[dict[str, Any]]:
    remaining = set(expected_hashes)
    records: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.rglob("*")):
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise OSError("Harbor trace staging contains a symlink")
        if stat.S_ISDIR(path_stat.st_mode):
            continue
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
            raise OSError("Harbor trace staging contains a non-private file")
        relative = path.relative_to(artifact_dir).as_posix()
        if relative == "manifest.json":
            continue
        if relative not in remaining:
            raise OSError("Harbor trace staging contains an unexpected artifact")
        payload = path.read_bytes()
        safe_payload = _safe_text_payload(payload, path.suffix, redactor)
        if safe_payload is None or safe_payload[0] != payload:
            raise ValueError("Harbor trace staging changed after sanitization")
        digest = sha256(payload).hexdigest()
        if digest != expected_hashes[relative]:
            raise ValueError("Harbor trace staging does not match its parent write ledger")
        records.append(
            {
                "path": relative,
                "bytes": len(payload),
                "sha256": digest,
            }
        )
        remaining.remove(relative)
        del safe_payload, payload
    if remaining:
        raise OSError("Harbor trace staging is missing an expected artifact")
    return records


def _write_manifest(
    artifact_dir: Path,
    *,
    run_id: str,
    redactor: TraceRedactor,
    collection_status: str,
    expected_hashes: Mapping[str, str],
) -> dict[str, Any]:
    if collection_status not in {"scope_complete", "partial", "minimal"}:
        raise ValueError("Unknown Harbor trace collection status")
    _validate_run_id(run_id)
    manifest = {
        "schema_version": 4,
        "run_id": run_id,
        "generated_at": _utc_now(),
        "collection_status": collection_status,
        "coverage_scope": "classified_public_utf8_text",
        "known_policy_omissions": [
            "manager_private_history",
            "mixed_authority_stdout",
            "private_or_sealed_runtime_material",
            "workspace_entries_removed_before_post_run_collection",
        ],
        "files": _artifact_manifest(
            artifact_dir,
            expected_hashes=expected_hashes,
            redactor=redactor,
        ),
    }
    _manifest_sha256, _manifest_bytes = _write_json(
        artifact_dir / "manifest.json",
        manifest,
        redactor=redactor,
    )
    return manifest


def export_harbor_research_artifacts(
    *,
    run_id: str,
    workspace: Path,
    workspace_baseline: WorkspaceBaseline,
    artifact_dir: Path,
    project_root: Path,
    instruction: str,
    run_configuration: dict[str, Any],
    started_at: str,
    elapsed_seconds: float,
    outcome: str,
    return_code: int | None,
    supervisor_error_type: str | None,
    redactor: TraceRedactor | None = None,
    scratch: EphemeralRunScratch | None = None,
) -> dict[str, Any]:
    """Finalize one Harbor run bundle after its supervised child has stopped."""
    redactor = redactor or TraceRedactor()
    workspace = workspace.absolute()
    artifact_dir = artifact_dir.resolve()
    if not artifact_dir.is_dir():
        raise FileNotFoundError("Harbor run artifact directory must be allocated before launch")

    safe_instruction = _safe_text_payload(
        instruction.encode("utf-8"),
        ".txt",
        redactor,
    )
    sanitized_instruction = safe_instruction[0] if safe_instruction is not None else None
    run_record = {
        "schema_version": 4,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
        "instruction_sha256": (
            sha256(sanitized_instruction).hexdigest() if sanitized_instruction is not None else None
        ),
        "instruction_hash_basis": (
            "sanitized_trace_text" if sanitized_instruction is not None else "not_recorded"
        ),
        "configuration": run_configuration,
        "outcome": outcome,
        "return_code": return_code,
        "supervisor_error_type": supervisor_error_type,
        "output_stream": {
            "public_payload_forwarded": False,
            "public_payload_persisted": False,
            "public_payload_metadata_persisted": False,
            "reason": "mixed_authority_stream_not_public",
        },
    }
    run_sha256, _run_bytes = _write_json(
        artifact_dir / "run.json",
        run_record,
        redactor=redactor,
    )
    runtime_sha256, _runtime_bytes = _write_json(
        artifact_dir / "runtime.json",
        _runtime_inventory(),
        redactor=redactor,
    )

    instruction_preserved = _write_sanitized_text(
        artifact_dir / "input/instruction.txt",
        instruction,
        redactor=redactor,
        suffix=".txt",
    )
    snapshot = capture_workspace_snapshot(
        workspace=workspace,
        artifact_dir=artifact_dir,
        baseline=workspace_baseline,
        redactor=redactor,
        scratch=scratch,
        phase="final",
    )
    _validate_workspace_root(workspace, workspace_baseline)
    workspace_git_summary = _write_git_summary(
        workspace,
        artifact_dir / "workspace/git-summary.json",
        redactor=redactor,
        include_worktree_state=False,
    )
    adapter_git_summary = _write_git_summary(
        project_root,
        artifact_dir / "adapter-source/git-summary.json",
        redactor=redactor,
    )

    exclusion_counts = Counter()
    exclusion_counts.update(
        {
            reason: int(record.get("entries", 0))
            for reason, record in snapshot["exclusion_summary"].items()
        }
    )
    collection_incomplete_reasons = list(snapshot["capture_incomplete_reasons"])
    if not instruction_preserved:
        collection_incomplete_reasons.append("instruction_not_preserved")
    collection_sha256, _collection_bytes = _write_json(
        artifact_dir / "collection.json",
        {
            "schema_version": 4,
            "coverage_scope": "classified_public_utf8_text",
            "known_policy_omissions": [
                "manager_private_history",
                "mixed_authority_stdout",
                "private_or_sealed_runtime_material",
                "workspace_entries_removed_before_post_run_collection",
            ],
            "policy": {
                "collector": "harbor_parent_supervisor",
                "threat_model": "behavioral_application_level_sealing",
                "worker_log_assumption": "workers_do_not_access_sealed_evaluator_material",
                "unregistered_mount_assumption": (
                    "workers_do_not_access_or_disclose_unrelated_mounted_credentials"
                ),
                "not_an_os_sandbox": True,
                "publication_channel": "agent_controlled_harbor_artifacts",
                "integrity_check": "manifest_member_hashes",
                "integrity_limit": "agent_controlled_storage_not_a_trust_anchor",
                "timing": "after_supervised_process_stop",
                "detached_task_services_may_remain": True,
                "workspace_payloads": "sanitized_utf8_text_only",
                "mixed_authority_stdout": "not_public",
                "manager_history": "not_eligible_without_public_visibility_labels",
                "sensitive_exclusions": "not_enumerated",
            },
            "instruction_preserved": instruction_preserved,
            "workspace_snapshot_preserved": True,
            "workspace_capture_complete": snapshot["capture_complete"],
            "workspace_capture_stop_reason": snapshot["capture_stop_reason"],
            "workspace_capture_incomplete_reasons": snapshot["capture_incomplete_reasons"],
            "collection_incomplete_reasons": sorted(collection_incomplete_reasons),
            "excluded_entry_counts": dict(sorted(exclusion_counts.items())),
            "errors": [
                {
                    "stage": "workspace_snapshot",
                    "type": record["type"],
                    "count": record["count"],
                }
                for record in snapshot["errors"]
            ],
        },
        redactor=redactor,
    )
    expected_hashes = {
        "run.json": run_sha256,
        "runtime.json": runtime_sha256,
        "workspace/snapshot.json": str(snapshot["_artifact_sha256"]),
        "workspace/git-summary.json": str(workspace_git_summary["_artifact_sha256"]),
        "adapter-source/git-summary.json": str(adapter_git_summary["_artifact_sha256"]),
        "collection.json": collection_sha256,
        **{str(entry["artifact"]): str(entry["sha256"]) for entry in snapshot["files"]},
    }
    if instruction_preserved:
        if sanitized_instruction is None:
            raise ValueError("Preserved Harbor instruction has no sanitized digest source")
        expected_hashes["input/instruction.txt"] = sha256(sanitized_instruction).hexdigest()
    return _write_manifest(
        artifact_dir,
        run_id=run_id,
        redactor=redactor,
        collection_status=(
            "scope_complete"
            if snapshot["capture_complete"] and instruction_preserved
            else "partial"
        ),
        expected_hashes=expected_hashes,
    )


def write_minimal_harbor_run_bundle(
    *,
    run_id: str,
    artifact_dir: Path,
    run_configuration: dict[str, Any],
    started_at: str,
    elapsed_seconds: float,
    outcome: str,
    return_code: int | None,
    supervisor_error_type: str | None,
    export_error_type: str,
    redactor: TraceRedactor | None = None,
) -> dict[str, Any]:
    """Write a metadata-only fallback if normal post-run collection fails."""
    redactor = redactor or TraceRedactor()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_sha256, _run_bytes = _write_json(
        artifact_dir / "run.json",
        {
            "schema_version": 4,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
            "configuration": run_configuration,
            "outcome": outcome,
            "return_code": return_code,
            "supervisor_error_type": supervisor_error_type,
            "output_stream": {
                "public_payload_forwarded": False,
                "public_payload_persisted": False,
                "public_payload_metadata_persisted": False,
                "reason": "mixed_authority_stream_not_public",
            },
            "trace_export_error_type": export_error_type,
        },
        redactor=redactor,
    )
    collection_sha256, _collection_bytes = _write_json(
        artifact_dir / "collection.json",
        {
            "schema_version": 4,
            "coverage_scope": "metadata_only",
            "known_policy_omissions": ["workspace_payloads"],
            "workspace_snapshot_preserved": False,
            "workspace_capture_complete": False,
            "workspace_capture_incomplete_reasons": ["trace_export_failed"],
            "collection_incomplete_reasons": ["trace_export_failed"],
            "errors": [{"stage": "trace_export", "type": export_error_type}],
        },
        redactor=redactor,
    )
    return _write_manifest(
        artifact_dir,
        run_id=run_id,
        redactor=redactor,
        collection_status="minimal",
        expected_hashes={
            "run.json": run_sha256,
            "collection.json": collection_sha256,
        },
    )
