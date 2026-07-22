"""
Local Resources - Validation helpers for locally declared datasets and functions

Ideas submitted from local files can declare resources that already exist on
the machine running NeuriCo (idea.local_resources) and structured evaluation
expectations (idea.evaluation). Unlike background.* fields, which are advisory
hints for the resource finder, these declarations are contractual: the paths
are staged into the workspace and their stated usage is binding.

This module holds the pure validation logic shared by the submission CLIs and
IdeaManager.validate_idea():
1. Structural validation of local_resources and evaluation entries
2. Existence checks for declared paths (warnings at submit time; staging in
   runner.py is where a missing path becomes a hard error)
3. Conversion faithfulness: every path-like token in the source text must
   survive into the generated YAML verbatim
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple
import ast
import hashlib
import json
import os
import re
import shutil


# Staged resources land here, relative to the workspace root
DATASETS_STAGING_DIR = "datasets/local"
FUNCTIONS_STAGING_DIR = "code/local"

# Warn (but proceed) when a single dataset exceeds this many bytes
LARGE_DATASET_BYTES = 2 * 1024 ** 3


# Path-like tokens: absolute (/...), relative (./ or ../), or home (~/) with at
# least two segments. The lookbehind rejects tokens embedded in URLs or words
# (e.g. the /data.csv inside https://example.com/data.csv).
_PATH_TOKEN_RE = re.compile(
    r"(?<![\w:/])"
    r"(?:~/|\.{1,2}/|/)"
    r"[\w.\-]+(?:/[\w.\-]+)+"
)


def find_path_tokens(text: str) -> List[str]:
    """
    Extract local path-like tokens from free text.

    Args:
        text: Raw text of the idea (markdown or plain text)

    Returns:
        Deduplicated list of path tokens in order of first appearance
    """
    seen = []
    for match in _PATH_TOKEN_RE.finditer(text):
        # Trailing dots are sentence punctuation, not part of the path
        token = match.group(0).rstrip('.')
        if token not in seen:
            seen.append(token)
    return seen


def missing_paths_in_idea(raw_text: str, idea_spec: Dict[str, Any]) -> List[str]:
    """
    Find local paths mentioned in the source text that did not survive
    conversion into the idea specification.

    The check is a verbatim substring match against a JSON dump of the idea
    (JSON, not YAML, because yaml.dump may wrap long lines and split a path).

    Args:
        raw_text: Original text the idea was converted from
        idea_spec: Converted idea specification dictionary

    Returns:
        List of dropped path tokens (empty means the conversion was faithful)
    """
    blob = json.dumps(idea_spec, ensure_ascii=False)
    return [token for token in find_path_tokens(raw_text) if token not in blob]


def _entrypoint_defined(file_path: Path, entrypoint: str) -> bool:
    """Check whether a Python file defines a top-level function or class
    named entrypoint. Returns True on parse failure (benefit of the doubt;
    the eval verifier catches real problems later)."""
    try:
        tree = ast.parse(file_path.read_text(encoding='utf-8'))
    except (OSError, SyntaxError, ValueError):
        return True
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == entrypoint:
                return True
    return False


def _resolve(path_str: str, base_dir: Path = None) -> Path:
    """Expand ~ and resolve relative paths against base_dir (default cwd)."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    return path


def validate_local_resources(idea: Dict[str, Any],
                             base_dir: Path = None) -> Tuple[List[str], List[str]]:
    """
    Validate the idea.local_resources section.

    Every entry must state its address (path) and its dedicated usage;
    functions must additionally name their entrypoint. Missing paths are
    warnings here (the submitting machine may differ from the staging
    machine); staging turns them into hard errors.

    Args:
        idea: The inner idea dictionary (idea_spec['idea'])
        base_dir: Directory to resolve relative paths against (default cwd)

    Returns:
        Tuple of (errors, warnings) message lists
    """
    errors = []
    warnings = []

    resources = idea.get('local_resources')
    if resources is None:
        return errors, warnings

    if not isinstance(resources, dict):
        errors.append("local_resources must be a mapping with 'datasets' and/or 'functions'")
        return errors, warnings

    for kind in ('datasets', 'functions'):
        entries = resources.get(kind)
        if entries is None:
            continue
        if not isinstance(entries, list):
            errors.append(f"local_resources.{kind} must be a list")
            continue

        for idx, entry in enumerate(entries):
            label = f"local_resources.{kind}[{idx}]"
            if not isinstance(entry, dict):
                errors.append(f"{label}: must be a mapping with 'path' and 'usage'")
                continue

            path_str = entry.get('path')
            if not path_str:
                errors.append(f"{label}: missing 'path' (the address of the resource)")
            usage = entry.get('usage')
            if not usage or not str(usage).strip():
                errors.append(f"{label}: missing 'usage' (what this resource is for is required)")

            if kind == 'functions':
                entrypoint = entry.get('entrypoint')
                if not entrypoint:
                    errors.append(f"{label}: missing 'entrypoint' (the function name to call)")

            if path_str:
                resolved = _resolve(str(path_str), base_dir)
                if not resolved.exists():
                    warnings.append(
                        f"{label}: path does not exist on this machine: {path_str} "
                        f"(staging will fail unless it exists where the research runs)"
                    )
                elif kind == 'functions' and entry.get('entrypoint'):
                    if resolved.is_file() and resolved.suffix == '.py':
                        if not _entrypoint_defined(resolved, entry['entrypoint']):
                            warnings.append(
                                f"{label}: entrypoint '{entry['entrypoint']}' not found "
                                f"at top level of {path_str}"
                            )

    return errors, warnings


def _tree_size_bytes(path: Path) -> int:
    """Total size of a file or directory tree in bytes."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def stage_local_resources(work_dir: Path, idea_spec: Dict[str, Any],
                          base_dir: Path = None) -> int:
    """
    Copy declared local resources into the workspace and rewrite their paths.

    Datasets are copied to datasets/local/<name> and functions to
    code/local/<filename>. Each entry's 'path' is rewritten in place to the
    workspace-relative location, with the original kept as 'source_path', so
    agents and eval.py never depend on host paths. If the workspace already
    has .neurico/idea.yaml (GitHub setup writes it before staging), it is
    rewritten to match.

    Re-staging is idempotent: an entry whose path is already workspace-relative
    is only re-copied if its staged copy went missing.

    Unlike submit-time validation, which only warns, a missing source path is
    a hard error here: the run cannot honor the resource contract without
    the files.

    Args:
        work_dir: Workspace root directory
        idea_spec: Full idea specification (mutated in place)
        base_dir: Directory to resolve relative source paths against

    Returns:
        Number of resources staged (0 if the idea declares none)

    Raises:
        FileNotFoundError: If a declared source path does not exist
    """
    import yaml

    resources = idea_spec.get('idea', {}).get('local_resources')
    if not isinstance(resources, dict):
        return 0

    staged = 0
    for kind, staging_dir in (('datasets', DATASETS_STAGING_DIR),
                              ('functions', FUNCTIONS_STAGING_DIR)):
        entries = resources.get(kind)
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict) or not entry.get('path'):
                continue

            # Already staged on a previous run: only re-copy if the staged
            # copy is gone (e.g. fresh clone of the research repo).
            if entry.get('source_path'):
                if (work_dir / entry['path']).exists():
                    continue
                src = _resolve(str(entry['source_path']), base_dir)
            else:
                src = _resolve(str(entry['path']), base_dir)

            if not src.exists():
                raise FileNotFoundError(
                    f"local_resources.{kind}: declared path does not exist: {src} "
                    f"(declared as '{entry['path']}')"
                )

            if kind == 'datasets':
                name = entry.get('name') or src.name
                dst = work_dir / staging_dir / name
                size = _tree_size_bytes(src)
                if size > LARGE_DATASET_BYTES:
                    print(f"   ⚠️  Dataset '{name}' is {size / 1024 ** 3:.1f} GB; "
                          f"copying may take a while")
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            else:
                dst = work_dir / staging_dir / src.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                # Record a fingerprint so the scorer can detect a mandated
                # function that was edited after staging (gaming guard)
                entry['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()

            entry.setdefault('source_path', str(src))
            entry['path'] = str(dst.relative_to(work_dir).as_posix())
            staged += 1
            print(f"   ✓ Staged {kind[:-1]}: {entry['source_path']} -> {entry['path']}")

    if staged:
        # Keep staged data out of the research repo (it may be private and
        # large); staged functions stay tracked so eval.py can rely on them.
        _ignore_staged_datasets(work_dir)

        # Keep the workspace copy of the idea in sync with rewritten paths.
        # Written even when GitHub setup did not create it: the staged idea
        # is the canonical contract for every agent in this workspace.
        workspace_idea = work_dir / ".neurico" / "idea.yaml"
        workspace_idea.parent.mkdir(parents=True, exist_ok=True)
        with open(workspace_idea, 'w', encoding='utf-8') as f:
            yaml.dump(idea_spec, f, default_flow_style=False, sort_keys=False)

    return staged


def staged_function_mismatches(work_dir: Path) -> List[str]:
    """
    Check staged local functions against the fingerprints recorded at
    staging time.

    Reads .neurico/idea.yaml (written by stage_local_resources). Returns one
    message per staged function whose file is missing or whose contents no
    longer match the recorded sha256; an empty list means the mandated
    functions are intact. Workspaces without local resources trivially pass.
    """
    import yaml

    idea_path = Path(work_dir) / ".neurico" / "idea.yaml"
    if not idea_path.exists():
        return []
    try:
        idea_spec = yaml.safe_load(idea_path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError:
        return ["could not parse .neurico/idea.yaml to verify staged functions"]

    resources = idea_spec.get('idea', {}).get('local_resources')
    if not isinstance(resources, dict):
        return []

    mismatches = []
    for entry in resources.get('functions') or []:
        if not isinstance(entry, dict) or not entry.get('sha256') or not entry.get('path'):
            continue
        staged = Path(work_dir) / entry['path']
        if not staged.exists():
            mismatches.append(f"staged function missing: {entry['path']}")
            continue
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            mismatches.append(
                f"staged function modified after staging: {entry['path']} "
                f"(restore it from {entry.get('source_path', 'its source')} before scoring)"
            )
    return mismatches


def _ignore_staged_datasets(work_dir: Path) -> None:
    """Append the staged-datasets directory to the workspace .gitignore."""
    pattern = f"{DATASETS_STAGING_DIR}/"
    gitignore = work_dir / ".gitignore"
    existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ""
    if pattern in existing.splitlines():
        return
    section = f"\n# Staged local datasets (copied from the submitting machine)\n{pattern}\n"
    gitignore.write_text(existing.rstrip("\n") + "\n" + section if existing else section.lstrip("\n"),
                         encoding='utf-8')


def validate_evaluation_spec(idea: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Validate the idea.evaluation section (structured metrics and format).

    Args:
        idea: The inner idea dictionary (idea_spec['idea'])

    Returns:
        Tuple of (errors, warnings) message lists
    """
    errors = []
    warnings = []

    evaluation = idea.get('evaluation')
    if evaluation is None:
        return errors, warnings

    if not isinstance(evaluation, dict):
        errors.append("evaluation must be a mapping with 'metrics' and/or 'results_format'")
        return errors, warnings

    metrics = evaluation.get('metrics')
    if metrics is not None:
        if not isinstance(metrics, list):
            errors.append("evaluation.metrics must be a list")
        else:
            if len(metrics) == 0:
                warnings.append("evaluation.metrics is empty")
            for idx, metric in enumerate(metrics):
                label = f"evaluation.metrics[{idx}]"
                if not isinstance(metric, dict):
                    errors.append(f"{label}: must be a mapping with 'name' and 'definition'")
                    continue
                if not metric.get('name'):
                    errors.append(f"{label}: missing 'name'")
                if not metric.get('definition'):
                    errors.append(f"{label}: missing 'definition'")
                if not metric.get('target'):
                    warnings.append(
                        f"{label}: no 'target' given; the rule maker will set one "
                        f"and tag it source: derived"
                    )

    return errors, warnings
