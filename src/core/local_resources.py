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


def _usable_path_strings(idea_spec: Dict[str, Any]) -> List[str]:
    """
    Collect path strings from the locations the pipeline actually honors:
    local_resources entries (path / source_path) and background paper paths.

    Everything else — notably background.description prose — carries no
    staging or mounting behavior, so a path that only survives there is
    effectively dropped.
    """
    idea = idea_spec.get('idea') if isinstance(idea_spec.get('idea'), dict) else idea_spec
    out: List[str] = []

    resources = idea.get('local_resources')
    if isinstance(resources, dict):
        for kind in ('datasets', 'functions'):
            for entry in resources.get(kind) or []:
                if isinstance(entry, dict):
                    out.extend([entry.get('path'), entry.get('source_path')])

    background = idea.get('background')
    if isinstance(background, dict):
        for paper in background.get('papers') or []:
            if isinstance(paper, dict):
                out.append(paper.get('path'))

    return [str(p) for p in out if p]


def missing_paths_in_idea(raw_text: str, idea_spec: Dict[str, Any]) -> List[str]:
    """
    Find local paths mentioned in the source text that did not survive
    conversion into a USABLE location of the idea specification.

    Usable means local_resources entries or background.papers[].path — the
    places staging and mount collection read from. A plain substring match
    against the whole idea would pass a path that merely survives inside
    background.description prose (the no-API-key fallback keeps the full
    input there), while never being staged or mounted.

    Args:
        raw_text: Original text the idea was converted from
        idea_spec: Converted idea specification dictionary

    Returns:
        List of dropped path tokens (empty means the conversion was faithful)
    """
    usable = _usable_path_strings(idea_spec)
    return [
        token for token in find_path_tokens(raw_text)
        if not any(token in candidate for candidate in usable)
    ]


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


def _staging_destination(work_dir: Path, staging_dir: str, requested: str,
                         kind: str, taken: set) -> Path:
    """
    Compute a safe, collision-free staging destination.

    The requested name is reduced to its basename, so path separators,
    traversal sequences ('../../outside') and absolute paths cannot escape
    the staging directory. Within one staging pass, duplicate names receive
    a deterministic numeric suffix instead of silently merging (datasets)
    or overwriting (functions). Determinism matters: a continuation that
    re-stages the same entries in the same order must map each entry to the
    same destination.
    """
    safe = Path(str(requested)).name
    if not safe or safe in ('.', '..'):
        raise ValueError(
            f"local_resources.{kind}: unusable resource name {requested!r}")

    if safe in taken:
        stem, dot, ext = safe.partition('.')
        counter = 2
        candidate = f"{stem}_{counter}{dot}{ext}"
        while candidate in taken:
            counter += 1
            candidate = f"{stem}_{counter}{dot}{ext}"
        print(f"   ⚠️  Duplicate staged name '{safe}'; staging as '{candidate}'")
        safe = candidate
    taken.add(safe)

    root = work_dir / staging_dir
    dst = root / safe
    # Belt and braces: the basename reduction above must keep us inside root
    if dst.parent != root:
        raise ValueError(
            f"local_resources.{kind}: staging destination escaped "
            f"{staging_dir}: {requested!r}")
    return dst


def workspace_contract_copy(idea_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep copy of the idea with host-machine metadata removed.

    The workspace .neurico/idea.yaml may be committed to a (possibly
    GitHub-backed) research repository, so absolute host paths — resource
    source_path values and the submitting file's metadata.source_path —
    must not leak into it. The submitted yaml under ideas/ keeps them; only
    the workspace copy is redacted.
    """
    import copy

    clean = copy.deepcopy(idea_spec)
    idea = clean.get('idea')
    if not isinstance(idea, dict):
        return clean

    metadata = idea.get('metadata')
    if isinstance(metadata, dict):
        metadata.pop('source_path', None)

    resources = idea.get('local_resources')
    if isinstance(resources, dict):
        for kind in ('datasets', 'functions'):
            for entry in resources.get(kind) or []:
                if isinstance(entry, dict):
                    entry.pop('source_path', None)
    return clean


def stage_local_resources(work_dir: Path, idea_spec: Dict[str, Any],
                          base_dir: Path = None) -> int:
    """
    Copy declared local resources into the workspace and rewrite their paths.

    Datasets are copied to datasets/local/<name> and functions to
    code/local/<filename>. Destination names are sanitized to basenames
    (no traversal or absolute-path escape) and deduplicated per pass. Each
    entry's 'path' is rewritten in place to the workspace-relative location,
    with the original kept as 'source_path' in memory; the workspace
    .neurico/idea.yaml copy is written with host paths redacted.

    Re-staging is idempotent across real continuations, which reload the
    ORIGINAL submitted idea (host paths, no source_path): an entry whose
    deterministic destination already exists is kept as-is — never merged
    over — and functions are refreshed from source when the source is
    still reachable so their recorded sha256 matches the staged bytes.

    Unlike submit-time validation, which only warns, a missing source path
    is a hard error here — unless the staged copy already exists, which a
    continuation on a different machine relies on.

    Args:
        work_dir: Workspace root directory
        idea_spec: Full idea specification (mutated in place)
        base_dir: Directory to resolve relative source paths against

    Returns:
        Number of resources actually copied this pass (0 if none needed)

    Raises:
        FileNotFoundError: If a resource is neither staged nor reachable
    """
    import yaml

    resources = idea_spec.get('idea', {}).get('local_resources')
    if not isinstance(resources, dict):
        return 0

    staged = 0
    processed = 0
    for kind, staging_dir in (('datasets', DATASETS_STAGING_DIR),
                              ('functions', FUNCTIONS_STAGING_DIR)):
        entries = resources.get(kind)
        if not isinstance(entries, list):
            continue

        taken: set = set()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get('path'):
                continue

            entry_path = str(entry['path']).replace('\\', '/')
            already_staged = entry_path.startswith(f"{staging_dir}/")

            if already_staged:
                # Path was rewritten by a previous staging pass (same
                # process or a reloaded contract). Reserve the name so later
                # duplicates cannot collide with it.
                dst = work_dir / entry_path
                taken.add(dst.name)
                src = _resolve(str(entry.get('source_path') or ''), base_dir) \
                    if entry.get('source_path') else None
            else:
                source_str = str(entry.get('source_path') or entry['path'])
                src = _resolve(source_str, base_dir)
                requested = (entry.get('name') if kind == 'datasets' else None) \
                    or Path(source_str).name
                dst = _staging_destination(work_dir, staging_dir, requested,
                                           kind, taken)

            src_available = src is not None and src.exists()

            # A reloaded original contract (path not yet rewritten) whose
            # function is already on disk: refresh from source so the
            # recorded sha256 is computed from the bytes actually staged.
            refresh_function = (kind == 'functions' and not already_staged
                                and dst.exists() and src_available)

            if dst.exists() and not refresh_function:
                # Idempotent re-stage: keep the existing staged copy. For
                # datasets this also avoids merging stale files over a
                # prior copy.
                if kind == 'functions' and not entry.get('sha256'):
                    entry['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
            else:
                if not src_available:
                    raise FileNotFoundError(
                        f"local_resources.{kind}: declared path does not "
                        f"exist: {src or entry.get('source_path')} "
                        f"(declared as '{entry['path']}') and no staged copy "
                        f"is present at {dst}"
                    )
                if kind == 'datasets':
                    size = _tree_size_bytes(src)
                    if size > LARGE_DATASET_BYTES:
                        print(f"   ⚠️  Dataset '{dst.name}' is "
                              f"{size / 1024 ** 3:.1f} GB; copying may take a while")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    # Record a fingerprint so the scorer can detect a mandated
                    # function that was edited after staging (gaming guard)
                    entry['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
                staged += 1
                print(f"   ✓ Staged {kind[:-1]}: "
                      f"{entry.get('source_path') or entry['path']} -> "
                      f"{dst.relative_to(work_dir).as_posix()}")

            if src is not None:
                entry.setdefault('source_path', str(src))
            entry['path'] = str(dst.relative_to(work_dir).as_posix())
            processed += 1

    if processed:
        # Keep staged data out of the research repo (it may be private and
        # large); staged functions stay tracked so eval.py can rely on them.
        _ignore_staged_datasets(work_dir)

        # Keep the workspace copy of the idea in sync with rewritten paths.
        # Written even when GitHub setup did not create it: the staged idea
        # is the canonical contract for every agent in this workspace. Host
        # paths are redacted — this file may be pushed to GitHub.
        workspace_idea = work_dir / ".neurico" / "idea.yaml"
        workspace_idea.parent.mkdir(parents=True, exist_ok=True)
        with open(workspace_idea, 'w', encoding='utf-8') as f:
            yaml.dump(workspace_contract_copy(idea_spec), f,
                      default_flow_style=False, sort_keys=False)

    return staged


def staged_function_mismatches(work_dir: Path,
                               idea: Dict[str, Any] = None) -> List[str]:
    """
    Check staged local functions against their expected fingerprints.

    When the TRUSTED idea (the submitted contract held by the orchestrator,
    which lives outside the worker-visible workspace) is provided, the check
    fails closed: the contract says which functions are mandated, so missing
    integrity metadata is itself a mismatch — a worker deleting or editing
    .neurico/idea.yaml must not silence the guard. Where the original source
    file is still reachable (it is mounted read-only during Docker runs),
    the staged bytes are verified against the SOURCE, which a forged
    workspace-recorded sha256 cannot defeat.

    Without the trusted idea (legacy/standalone callers), the workspace
    .neurico/idea.yaml is the only reference: recorded fingerprints are
    verified, and a function marked required_for_evaluation that lacks a
    verifiable fingerprint is reported rather than skipped.

    Returns one message per problem; an empty list means the mandated
    functions are intact. Workspaces whose contract declares no local
    functions trivially pass.
    """
    import yaml

    work_dir = Path(work_dir)

    def _functions_of(spec) -> List[Dict[str, Any]]:
        inner = spec.get('idea') if isinstance(spec.get('idea'), dict) else spec
        resources = inner.get('local_resources')
        if not isinstance(resources, dict):
            return []
        return [e for e in resources.get('functions') or []
                if isinstance(e, dict)]

    trusted_functions = _functions_of(idea) if isinstance(idea, dict) else None

    idea_path = work_dir / ".neurico" / "idea.yaml"
    workspace_functions: List[Dict[str, Any]] = []
    workspace_error = None
    if idea_path.exists():
        try:
            workspace_spec = yaml.safe_load(
                idea_path.read_text(encoding='utf-8')) or {}
            workspace_functions = _functions_of(workspace_spec)
        except yaml.YAMLError:
            workspace_error = ("could not parse .neurico/idea.yaml to verify "
                               "staged functions")
    if workspace_error:
        return [workspace_error]

    # No trusted contract: legacy mode against the workspace record only
    if trusted_functions is None:
        if not idea_path.exists():
            return []
        mismatches = []
        for entry in workspace_functions:
            if not entry.get('sha256') or not entry.get('path'):
                if entry.get('required_for_evaluation'):
                    mismatches.append(
                        f"mandated function has no verifiable fingerprint: "
                        f"{entry.get('path') or entry.get('entrypoint') or entry!r}")
                continue
            mismatches.extend(_verify_staged_function(work_dir, entry))
        return mismatches

    # Trusted mode: every load-bearing fact — which functions exist, where
    # they are staged, what bytes are expected — comes from the trusted
    # contract or the read-only source file. The worker-writable workspace
    # record is consulted only as a fingerprint of last resort (it travels
    # through git history on continuations, so tampering is auditable);
    # crucially, the VERIFIED PATH is always derived from the contract, so
    # a record redirected at a pristine decoy file cannot shield a
    # tampered staged function.
    if not trusted_functions:
        return []

    recorded_sha_by_name = {}
    for entry in workspace_functions:
        if entry.get('path'):
            recorded_sha_by_name[Path(str(entry['path'])).name] = entry.get('sha256')

    mismatches = []
    taken: set = set()
    for trusted in trusted_functions:
        label = (trusted.get('entrypoint')
                 or Path(str(trusted.get('path', '?'))).name)
        trusted_path = str(trusted.get('path') or '').replace('\\', '/')

        # Canonical staged location per the contract: either the contract
        # already carries the rewritten path (staging mutated the
        # orchestrator-held spec), or it is derived deterministically the
        # same way staging derives it (same entries, same order)
        if trusted_path.startswith(f"{FUNCTIONS_STAGING_DIR}/"):
            staged = work_dir / trusted_path
            taken.add(staged.name)
            source_str = trusted.get('source_path')
        else:
            source_str = str(trusted.get('source_path') or trusted_path)
            try:
                staged = _staging_destination(
                    work_dir, FUNCTIONS_STAGING_DIR,
                    Path(source_str).name, 'functions', taken)
            except ValueError as exc:
                mismatches.append(str(exc))
                continue

        if not staged.exists():
            mismatches.append(
                f"staged function missing: "
                f"{staged.relative_to(work_dir).as_posix()}")
            continue
        staged_digest = hashlib.sha256(staged.read_bytes()).hexdigest()

        # Expected bytes, strongest reference first: the read-only source
        # file (mounted at its host path during Docker runs), then the
        # fingerprint recorded in the trusted contract, then the workspace
        # record. No reference at all means the function cannot be
        # verified — fail closed.
        source = _resolve(str(source_str)) if source_str else None
        if source is not None and source.is_file():
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            problem = f"differs from its source (restore it from {source} "
        elif trusted.get('sha256'):
            expected = trusted['sha256']
            problem = "was modified after staging (restore it "
        elif recorded_sha_by_name.get(staged.name):
            expected = recorded_sha_by_name[staged.name]
            problem = "was modified after staging (restore it "
        else:
            mismatches.append(
                f"mandated function '{label}' cannot be verified: no "
                f"reachable source and no recorded fingerprint")
            continue

        if staged_digest != expected:
            mismatches.append(
                f"staged function {staged.relative_to(work_dir).as_posix()} "
                f"{problem}before scoring)")

    return mismatches


def _verify_staged_function(work_dir: Path, entry: Dict[str, Any]) -> List[str]:
    """Verify one workspace-recorded function entry against its fingerprint."""
    staged = Path(work_dir) / entry['path']
    if not staged.exists():
        return [f"staged function missing: {entry['path']}"]
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    if digest != entry['sha256']:
        return [
            f"staged function modified after staging: {entry['path']} "
            f"(restore it from {entry.get('source_path', 'its source')} "
            f"before scoring)"
        ]
    return []


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


def canonicalize_local_paths(idea: Dict[str, Any],
                             base_dir: Path = None) -> List[Tuple[str, str]]:
    """
    Rewrite relative local_resources / paper paths to absolute host paths.

    Called at submit time, the only moment relative paths still mean
    something (the submitter's working directory). Every later consumer —
    the mounts sidecar, docker/run.sh, in-container staging — needs
    host-absolute paths; a relative path silently skipped at mount
    collection is exactly how a declared resource ends up invisible inside
    Docker. When submission itself runs inside Docker, base_dir should be
    the host working directory (NEURICO_HOST_CWD) so recorded paths keep
    host semantics.

    Absolute paths are left untouched (only ~ is expanded), so intentional
    symlinked locations survive verbatim.

    Args:
        idea: The inner idea dictionary (idea_spec['idea']); mutated in place
        base_dir: Directory to resolve relative paths against (default cwd)

    Returns:
        List of (before, after) rewrites, for reporting
    """
    rewrites: List[Tuple[str, str]] = []

    def canon(container, key):
        value = container.get(key)
        if not value:
            return
        text = str(value)
        if text.startswith(('http://', 'https://', 'git@')):
            return
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = ((base_dir or Path.cwd()) / path).resolve()
        if str(path) != text:
            container[key] = str(path)
            rewrites.append((text, str(path)))

    resources = idea.get('local_resources')
    if isinstance(resources, dict):
        for kind in ('datasets', 'functions'):
            for entry in resources.get(kind) or []:
                if isinstance(entry, dict):
                    canon(entry, 'path')

    background = idea.get('background')
    if isinstance(background, dict):
        for paper in background.get('papers') or []:
            if isinstance(paper, dict):
                canon(paper, 'path')

    return rewrites


def collect_host_paths(idea: Dict[str, Any]) -> List[str]:
    """
    Collect the absolute host paths an idea depends on before staging.

    Written to ideas/mounts/<idea_id>.txt at submit time so docker/run.sh can
    mount each path read-only at its identical in-container location (bash
    reads the sidecar line by line; it cannot parse the idea YAML itself).

    Covers unstaged local_resources entries and local paper paths. Entries
    that already carry source_path were staged into the workspace and need
    no mount. Relative paths cannot be mounted meaningfully on another
    machine: canonicalize_local_paths() should have rewritten them at
    submit time, so finding one here is worth a loud warning rather than a
    silent skip.

    Args:
        idea: The inner idea dictionary (idea_spec['idea'])

    Returns:
        Deduplicated list of absolute host paths in declaration order
    """
    paths = []

    def add(path_str):
        if not path_str:
            return
        path_str = str(path_str)
        if path_str.startswith(('http://', 'https://', 'git@')):
            return
        expanded = str(Path(path_str).expanduser())
        if not Path(expanded).is_absolute():
            print(f"   ⚠️  Relative local path cannot be mounted into Docker: "
                  f"{path_str} — declare it absolute (or submit from the "
                  f"directory it is relative to, so it can be canonicalized)")
            return
        if expanded not in paths:
            paths.append(expanded)

    resources = idea.get('local_resources')
    if isinstance(resources, dict):
        for kind in ('datasets', 'functions'):
            for entry in resources.get(kind) or []:
                if isinstance(entry, dict):
                    add(entry.get('source_path') or entry.get('path'))

    background = idea.get('background')
    if isinstance(background, dict):
        for paper in background.get('papers') or []:
            if isinstance(paper, dict):
                add(paper.get('path'))

    return paths


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
