from __future__ import annotations

import mimetypes
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
}

SUPPORTED_STRUCTURED_SUFFIXES = {
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",

}

@dataclass(frozen=True)
class DiscoveredRepository:
    """
    One repository/run directory found under the corpus root.
    """
    run_id: str
    repo_name: str
    repository_path: Path

@dataclass(frozen=True)
class DiscoveredFile:
    """
    Filesystem metadata collected before structured parsing.
    """
    run_id: str
    repo_name: str
    repository_path: Path
    absolute_path: Path
    relative_path: str
    suffix: str | None
    media_type: str | None
    source_family: str
    size_bytes: int
    sha256: str
    modified_at: datetime | None
    storage_uri: str
    is_structured: bool

def sha256_file(path: Path) -> str:
    """
    Compute the sha-256 hash of a file without loading it all into memory.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def infer_media_type(path: Path) -> str | None:
    """
    Infer a MIME type from the file name.
    mimetypes may return None for extensionless or uncommon files.
    """
    media_type, _encoding = mimetypes.guess_type(path.name)
    return media_type

def source_family(relative_path: str) -> str:
    """
    Assign a coarse, evidence-oriented source family.
    This is not semantic trajectory interpretation. It only groups files by 
    their location and known repository conventions.
    """
    normalized = relative_path.lower()
    if normalized.startswith("logs/"):
        if "execution_" in normalized and "transcript" in normalized:
            return "execution_transcript"
        if "resource_finder" in normalized and "transcript" in normalized:
            return "resource_finder_transcript"
        if "paper_writer" in normalized:
            return "paper_writer_transcript"
        return "logs"
    if normalized.startswith(".neurico/"):
        if normalized.endswith(("idea.yaml", "idea.yml")):
            return "neurico_idea"
        if normalized.endswith("pipeline_state.json"):
            return "neurico_pipeline_state"
        if normalized.endswith("pipeline_results.json"):
            return "neurico_pipeline_results"
        return "neurico_metadata"
    if normalized.startswith(".idea-explorer/"):
        if normalized.endswith(("idea.yaml", "idea.yml")):
            return "idea_explorer_idea"
        if normalized.endswith("pipeline_state.json"):
            return "idea_explorer_pipeline_state"
        if normalized.endswith("pipeline_results.json"):
            return "idea_explorer_pipeline_results"
        return "idea_explorer_metadata"
    if normalized.startswith("results/"):
        return "results"
    if normalized.startswith("datasets/"):
        return "datasets"
    if normalized.startswith("paper_search_results/"):
        return "paper_search_results"
    if normalized.startswith(("paper_draft/", "paper/")):
        return "paper_draft"
    if normalized.startswith(("src/", "code/", "scripts/")):
        return "source_code"
    if normalized.endswith((".md", ".rst", ".txt")):
        return "documentation"
    return "other"

def should_skip_path(relative_path: Path) -> bool:
    """
    Return True when any directory component is excluded.
    """
    return any(part in SKIP_DIRS for part in relative_path.parts)

def is_structured_file(path: Path) -> bool:
    """
    Return whether the file has a currently supported structured format.
    """
    return path.suffix.lower() in SUPPORTED_STRUCTURED_SUFFIXES

def discover_repositories(
    repos_root: Path,
    *,
    include_repos: set[str] | None = None,
) -> list[DiscoveredRepository]:
    """
    Discover immediate child directories as historical research runs.
    Hidden directories at the corpus-root level are ignored.
    """
    root = repos_root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repositories root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repositories root is not a directory: {root}")
    repositories: list[DiscoveredRepository] = [] 
    for repository_path in sorted(root.iterdir()):
        if not repository_path.is_dir():
            continue
        if repository_path.name.startswith("."):
            continue
        repo_name = repository_path.name
        if include_repos and repo_name not in include_repos:
            continue
        repositories.append(
            DiscoveredRepository(
                run_id=repo_name,
                repo_name=repo_name,
                repository_path=repository_path.resolve(),
            )
        )
    return repositories
    
def iter_repository_files(
    repository: DiscoveredRepository,
) -> Iterable[DiscoveredFile]:
    """
    Yield every non-skipped file in one repository.
    Discovery include all files. Structured parsing is decided separately.
    """
    root = repository.repository_path
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if should_skip_path(relative):
            continue
        try:
            stat = path.stat()
            digest = sha256_file(path)
        except OSError:
            # Ingest orchestration may later record an error for unreadble files.
            # Scanner skips files whose metadata can't be collected.
            continue
        modified_at = datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        )
        suffix = path.suffix.lower() or None
        relative_path = relative.as_posix()
        yield DiscoveredFile(
            run_id=repository.run_id,
            repo_name=repository.repo_name,
            repository_path=root,
            absolute_path=path.resolve(),
            relative_path=relative_path,
            suffix=suffix,
            media_type=infer_media_type(path),
            source_family=source_family(relative_path),
            size_bytes=stat.st_size,
            sha256=digest,
            modified_at=modified_at,
            storage_uri=path.resolve().as_uri(),
            is_structured=is_structured_file(path),
        )
    





