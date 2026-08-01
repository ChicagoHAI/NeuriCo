"""
Local Resources - Validation helpers for locally declared datasets and functions

Ideas submitted from local files can declare resources that already exist on
the machine running NeuriCo (idea.local_resources) and structured evaluation
expectations (idea.evaluation). Unlike background.* fields, which are advisory
hints for the resource finder, these declarations are contractual: the paths
are staged into the workspace and their stated usage is binding.

This module owns the full lifecycle of those declarations, layered by when
each piece runs:
1. Submit time — structural validation of local_resources and evaluation
   entries, existence checks for declared paths (warnings only; staging is
   where a missing path becomes a hard error), conversion faithfulness
   (every path-like token in the source text must survive into the YAML),
   and canonicalization of relative paths against the submitting directory.
2. Run dispatch — host mount collection and staging: declared resources are
   copied to sanitized workspace destinations (one deterministic protocol,
   _planned_destination, shared with verification) and fingerprinted, and
   the redacted workspace contract copy is written.
3. Score time — the integrity guard (staged_function_mismatches): staged
   function bytes are verified against the trusted contract, failing closed.
   Staging silently re-heals a tampered file only when the pristine source
   is reachable; the guard is what rejects tampering the source cannot heal.
"""

from contextlib import contextmanager
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

# Sealed datasets are read by eval.py at this workspace-relative path, but
# the path is a MATERIALIZATION, not a location: the bytes live in the
# sealed store (a sibling of the workspace, see sealed_store_for) and are
# copied into the tree being scored only while the scorer runs. The
# workspace itself never contains sealed data, so no agent — manifest
# trimmer, rule maker, or experiment runner — can ever read it.
SEALED_STAGING_DIR = "data/.test"

# Sibling directory holding each workspace's sealed data, mirroring the
# .scoring_sealed / .bootstrap_sealed conventions. Lives under the
# workspaces root so it rides the same Docker mount in every phase.
SEALED_STORE_DIRNAME = ".sealed_store"


def sealed_store_for(work_dir: Path) -> Path:
    """Sealed-data store for a workspace: <parent>/.sealed_store/<name>/."""
    work_dir = Path(work_dir)
    return work_dir.parent / SEALED_STORE_DIRNAME / work_dir.name

# Invariant kinds accepted in idea.continuation.invariants, with the field
# each kind requires
INVARIANT_KINDS = {
    'protected_path': 'path',
    'check': 'command',
    'statement': 'text',
}


def normalize_protected_path(raw: str) -> str:
    """
    Canonical normalization of one protected_path declaration: exact './'
    prefixes removed (never a character-set strip, which would eat the
    leading dot of '.github' or '.env'), trailing slashes dropped.

    Raises ValueError for declarations that cannot name a workspace-relative
    prefix (empty, '.', absolute, or '..' traversal) so the guard fails
    closed instead of silently watching the wrong path.
    """
    path = str(raw).strip().replace('\\', '/')
    if path.startswith('/'):
        raise ValueError(
            f"protected path {raw!r} is absolute; declare it relative to "
            f"the workspace root")
    # Component-wise canonicalization: drops empty ('a//b') and '.' parts,
    # so equivalent declarations normalize identically, and catches '..'
    # ANYWHERE — including a trailing 'src/..', which resolves to the
    # workspace root and would otherwise sail past prefix/substring checks.
    parts = [part for part in path.split('/') if part not in ('', '.')]
    if any(part == '..' for part in parts):
        raise ValueError(
            f"protected path {raw!r} escapes or renames the workspace root "
            f"('..' components are not allowed)")
    if not parts:
        raise ValueError(
            f"protected path {raw!r} does not name a workspace-relative "
            f"prefix (protecting the entire workspace is not supported)")
    return '/'.join(parts)


def protected_path_prefixes(idea: Dict[str, Any]) -> List[str]:
    """
    Normalized workspace-relative prefixes of protected_path invariants.

    One canonical normalization for every consumer of protected paths, so
    the guard and any prompt rendering can never drift on what counts as
    inside a protected prefix. Raises ValueError (via
    normalize_protected_path) on declarations that cannot be protected;
    validate_continuation rejects those at submit time, and a runtime caller
    treats the exception as a guard failure, never a silent skip.
    """
    idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
    if not isinstance(idea_spec, dict):
        return []
    continuation = idea_spec.get('continuation')
    if not isinstance(continuation, dict):
        return []
    return [
        normalize_protected_path(invariant['path'])
        for invariant in (continuation.get('invariants') or [])
        if isinstance(invariant, dict)
        and invariant.get('kind') == 'protected_path'
        and invariant.get('path')
    ]


def snapshot_protected_paths(work_dir: Path,
                             idea: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    Content fingerprint of every protected prefix: {prefix: {relpath: digest}}.

    Walks the filesystem directly rather than asking git, so files git
    ignores (model weights, generated configs, .env files) are covered, and
    symlinks are fingerprinted by their target string rather than followed.
    A missing prefix snapshots as an empty mapping, so its later appearance
    is a change like any other. Compare two snapshots with
    protected_path_changes().

    Args:
        work_dir: Workspace root directory
        idea: Full idea specification (or inner idea dict)

    Returns:
        {prefix: {relpath: digest}} for every protected prefix
    """
    work_dir = Path(work_dir)
    snapshot: Dict[str, Dict[str, str]] = {}
    for prefix in protected_path_prefixes(idea):
        files: Dict[str, str] = {}
        root = work_dir / prefix
        if root.is_symlink():
            files[''] = 'link:' + os.readlink(root)
        elif root.is_file():
            files[''] = hashlib.sha256(root.read_bytes()).hexdigest()
        elif root.is_dir():
            for path in sorted(root.rglob('*')):
                rel = path.relative_to(root).as_posix()
                if path.is_symlink():
                    files[rel] = 'link:' + os.readlink(path)
                elif path.is_file():
                    files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[prefix] = files
    return snapshot


def protected_path_changes(before: Dict[str, Dict[str, str]],
                           after: Dict[str, Dict[str, str]]) -> List[str]:
    """
    Workspace-relative paths whose content changed between two protected
    snapshots (modified, created, or deleted files alike).
    """
    changes: List[str] = []
    for prefix in before:
        b = before[prefix]
        a = after.get(prefix, {})
        for rel in sorted(set(b) | set(a)):
            if b.get(rel) != a.get(rel):
                changes.append(f"{prefix}/{rel}" if rel else prefix)
    return sorted(set(changes))

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
    Collect path strings from the structured locations a converted idea may
    legitimately record a path: local_resources entries (path / source_path),
    background.papers[].path, background.datasets[].source, and
    background.code_references[].repo — the destinations the conversion
    instructions document for a mentioned path.

    Only structured fields count; prose (notably background.description) carries
    no path semantics, so a path that survives only there is treated as dropped.
    The background.* fields are advisory (not staged or mounted), but they still
    satisfy faithfulness, which asks whether a path survived conversion, not
    whether it became a declared, staged resource.
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
        for dataset in background.get('datasets') or []:
            if isinstance(dataset, dict):
                out.append(dataset.get('source'))
        for ref in background.get('code_references') or []:
            if isinstance(ref, dict):
                out.append(ref.get('repo'))

    return [str(p) for p in out if p]


def missing_paths_in_idea(raw_text: str, idea_spec: Dict[str, Any]) -> List[str]:
    """
    Find local paths mentioned in the source text that did not survive
    conversion into a USABLE location of the idea specification.

    Usable means the structured path locations _usable_path_strings recognizes
    (local_resources entries, background.papers[].path, background.datasets[].source,
    background.code_references[].repo). A plain substring match against the whole
    idea would instead pass a path that merely survives inside background.description
    prose (the no-API-key fallback keeps the full input there), where nothing reads
    it as a path.

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


def _planned_destination(work_dir: Path, kind: str, entry: Dict[str, Any],
                         taken: set):
    """
    The one destination protocol shared by staging and the integrity guard:
    an entry whose path was already rewritten into the staging directory
    keeps that destination (reserving its name against later duplicates);
    otherwise the destination is derived from the declared name/basename via
    _staging_destination. Callers must iterate entries in declaration order
    with one `taken` set per kind — that lockstep determinism is what lets
    staged_function_mismatches re-derive exactly where staging wrote each
    function, so any protocol change here changes both sides at once.

    Returns (destination, source_str): destination is None when the entry
    stages nothing (no usable path or source), and source_str is the string
    the staged bytes are expected to come from (None when unknown, e.g. an
    in-repo resource whose only reference is its recorded fingerprint).
    Raises ValueError for unusable names, as _staging_destination does.
    """
    staging_dir = (DATASETS_STAGING_DIR if kind == 'datasets'
                   else FUNCTIONS_STAGING_DIR)
    dest_root = Path(work_dir)
    # Sealed datasets stage into the sealed STORE (a workspace sibling):
    # the contract records the eval-facing data/.test/... path, but the
    # bytes never enter the workspace — they are materialized into the tree
    # being scored only while the scorer runs. Decided before the
    # already-staged check so a reloaded contract whose path was rewritten
    # to data/.test/... is recognized as already staged (in the store).
    if kind == 'datasets' and entry.get('sealed'):
        staging_dir = SEALED_STAGING_DIR
        dest_root = sealed_store_for(work_dir)
    entry_path = str(entry.get('path') or '').replace('\\', '/')
    if entry_path.startswith(f"{staging_dir}/"):
        dst = dest_root / entry_path
        taken.add(dst.name)
        source = entry.get('source_path')
        return dst, (str(source) if source else None)

    # In-repo resource (common for adopted repositories): a relative path
    # with no external source that already exists inside the workspace is
    # its own destination — fingerprinted in place, never copied. A relative
    # path resolving outside the workspace root is NOT in-repo; it falls
    # through to normal staging, which contains it. SEALED entries never
    # take this shortcut: staying at the readable repo location would defeat
    # the seal, so they route through sealed staging with the workspace file
    # as the source (staging then removes the original: move semantics).
    if entry_path and not Path(entry_path).is_absolute() \
            and not entry.get('source_path'):
        candidate = (Path(work_dir) / entry_path).resolve()
        try:
            candidate.relative_to(Path(work_dir).resolve())
            in_workspace = candidate.exists()
        except ValueError:
            in_workspace = False
        if in_workspace:
            if not (kind == 'datasets' and entry.get('sealed')):
                return work_dir / entry_path, None
            requested = entry.get('name') or Path(entry_path).name
            return _staging_destination(dest_root, staging_dir, requested,
                                        kind, taken), str(Path(work_dir) / entry_path)

    source_str = str(entry.get('source_path') or entry_path)
    if not source_str:
        return None, None
    requested = ((entry.get('name') if kind == 'datasets' else None)
                 or Path(source_str).name)
    return _staging_destination(dest_root, staging_dir, requested,
                                kind, taken), source_str


@contextmanager
def materialized_sealed_data(tree: Path, store: Path):
    """
    Copy the sealed store's data/.test into the tree being scored for
    exactly the scorer's lifetime, then remove it.

    eval.py keeps its workspace-relative data/.test contract; the bytes
    exist inside an agent-reachable tree only while the (sealed, verified)
    scorer runs — and no agent runs then. A store without sealed data is a
    no-op, so unsealed runs pay nothing.
    """
    src = Path(store) / SEALED_STAGING_DIR
    dst = Path(tree) / SEALED_STAGING_DIR
    if not src.is_dir():
        yield
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    try:
        yield
    finally:
        shutil.rmtree(dst, ignore_errors=True)


def _remove_in_workspace_sealed_source(work_dir: Path, src: Path,
                                       source_repo: str = None) -> None:
    """
    Move semantics for a sealed source that exists inside the workspace:
    after the copy into data/.test, the readable copy is deleted so the
    research agent cannot read it at its old location. Covers both a
    workspace-relative source AND a host source living under the adopted
    continuation source repo — adoption copytrees the whole repo, so the
    sealed file has a second life at its repo-relative workspace path. The
    adopted repo's git HISTORY may still contain the bytes; scrubbing
    history is out of scope. Sources outside both trees (ordinary host
    paths) are never touched, and the workspace root itself is never a
    removal target — a sealed declaration naming the whole repo must not
    delete the freshly adopted workspace.
    """
    work_resolved = Path(work_dir).resolve()
    doomed: List[Path] = []
    try:
        resolved = Path(src).resolve()
    except OSError:
        return
    try:
        resolved.relative_to(work_resolved)
        doomed.append(resolved)
    except ValueError:
        pass
    if source_repo and not str(source_repo).startswith(
            ('http://', 'https://', 'git@')):
        try:
            rel = resolved.relative_to(Path(source_repo).expanduser().resolve())
            adopted_copy = (work_resolved / rel)
            if rel != Path('.') and (adopted_copy.exists()
                                     or adopted_copy.is_symlink()):
                doomed.append(adopted_copy)
        except (ValueError, OSError):
            pass

    sealed_root = (Path(work_dir) / SEALED_STAGING_DIR).resolve()
    for target in doomed:
        if target == work_resolved:
            continue
        if target == sealed_root or sealed_root in target.parents:
            continue
        if target.is_symlink():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        print(f"   🔒 Sealed source removed from the workspace tree: {target}")


def sealed_dataset_entries(idea: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All dataset entries declared sealed (any path form)."""
    idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
    if not isinstance(idea_spec, dict):
        return []
    resources = idea_spec.get('local_resources')
    if not isinstance(resources, dict):
        return []
    return [entry for entry in resources.get('datasets') or []
            if isinstance(entry, dict) and entry.get('sealed')]


def sealed_host_paths(idea: Dict[str, Any]) -> List[str]:
    """
    Absolute host source paths of datasets declared sealed.

    These must be visible ONLY while resources are staged (the two-phase
    dispatch's preparation container): leaving them mounted in the research
    container would let the agent read held-out data at its original host
    path even though the staged copy is hidden under data/.test.

    Args:
        idea: Full idea specification (or inner idea dict)

    Returns:
        Deduplicated absolute host paths in declaration order
    """
    sealed: List[str] = []
    for entry in sealed_dataset_entries(idea):
        raw = str(entry.get('source_path') or entry.get('path') or '')
        if not raw or raw.startswith(('http://', 'https://', 'git@')):
            continue
        expanded = str(Path(raw).expanduser())
        if Path(expanded).is_absolute() and expanded not in sealed:
            sealed.append(expanded)
    return sealed


def staging_only_host_paths(idea: Dict[str, Any]) -> List[str]:
    """
    Sidecar paths that must be mounted ONLY in the preparation container of
    the two-phase dispatch, never in the research container.

    Mounts expose whole trees, so a per-path sealed exclusion is not enough:
    beyond the sealed sources themselves, every declared path that is an
    ANCESTOR of a sealed source re-exposes the bytes, and whenever any
    sealed dataset exists at all, the continuation source repo does too
    (sealed files typically live inside the repo being continued — including
    in-repo relative declarations that produce no host path of their own).
    The research container provably does not need these mounts: adoption
    resumes on its record and staging is idempotent against data/.test.

    Args:
        idea: Full idea specification (or inner idea dict)

    Returns:
        Sorted absolute host paths to mount only during preparation
    """
    sealed_sources = sealed_host_paths(idea)
    staging_only = set(sealed_sources)

    for declared in collect_host_paths(idea.get('idea', idea)
                                       if isinstance(idea, dict) else {}):
        prefix = declared.rstrip('/')
        for source in sealed_sources:
            if source == prefix or source.startswith(prefix + '/'):
                staging_only.add(declared)
                break

    if sealed_dataset_entries(idea):
        idea_spec = idea.get('idea', idea) if isinstance(idea, dict) else {}
        continuation = idea_spec.get('continuation') \
            if isinstance(idea_spec, dict) else None
        if isinstance(continuation, dict):
            source_repo = str(continuation.get('source_repo') or '')
            if source_repo and not source_repo.startswith(
                    ('http://', 'https://', 'git@')):
                expanded = str(Path(source_repo).expanduser())
                if Path(expanded).is_absolute():
                    staging_only.add(expanded)

    return sorted(staging_only)


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

    # A local continuation source repo is an absolute host path; reduce it
    # to its name for the workspace copy. Remote URLs are provenance worth
    # keeping and leak nothing about the host machine.
    continuation = idea.get('continuation')
    if isinstance(continuation, dict):
        source_repo = str(continuation.get('source_repo') or '')
        if source_repo and not source_repo.startswith(
                ('http://', 'https://', 'git@')):
            continuation['source_repo'] = Path(source_repo).name

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

    continuation_repo = str(
        (idea_spec.get('idea', {}).get('continuation') or {}).get('source_repo')
        or '') or None

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

            dst, source_str = _planned_destination(work_dir, kind, entry, taken)
            src = _resolve(source_str, base_dir) if source_str else None

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
                    hint = ""
                    declared_link = Path(work_dir) / entry_path
                    if declared_link.is_symlink():
                        hint = (" (the declared path is a symlink whose target "
                                "is outside the workspace; declare the target's "
                                "real path instead)")
                    raise FileNotFoundError(
                        f"local_resources.{kind}: declared path does not "
                        f"exist: {src or entry.get('source_path')} "
                        f"(declared as '{entry['path']}') and no staged copy "
                        f"is present at {dst}{hint}"
                    )
                if kind == 'datasets':
                    size = _tree_size_bytes(src)
                    if size > LARGE_DATASET_BYTES:
                        print(f"   ⚠️  Dataset '{dst.name}' is "
                              f"{size / 1024 ** 3:.1f} GB; copying may take a while")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # Deliberately dereferences symlinks (unlike adoption):
                    # staged copies must be self-contained, because sealed
                    # sources are unmounted in the research container and
                    # a preserved link would dangle exactly when eval.py
                    # needs the data.
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                    if entry.get('sealed'):
                        _remove_in_workspace_sealed_source(
                            work_dir, src, source_repo=continuation_repo)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    # Record a fingerprint so the scorer can detect a mandated
                    # function that was edited after staging (gaming guard)
                    entry['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
                staged += 1
                if kind == 'datasets' and entry.get('sealed'):
                    label = ("sealed store: "
                             + dst.relative_to(sealed_store_for(work_dir)).as_posix())
                else:
                    label = dst.relative_to(work_dir).as_posix()
                print(f"   ✓ Staged {kind[:-1]}: "
                      f"{entry.get('source_path') or entry['path']} -> {label}")

            if src is not None:
                entry.setdefault('source_path', str(src))
            if kind == 'datasets' and entry.get('sealed'):
                # Store-relative, i.e. the eval-facing data/.test/... path
                # the scorer materializes; never a workspace location
                entry['path'] = str(
                    dst.relative_to(sealed_store_for(work_dir)).as_posix())
            else:
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
                               idea: Dict[str, Any]) -> List[str]:
    """
    Check staged local functions against their expected fingerprints.

    `idea` is the TRUSTED submitted contract held by the orchestrator, which
    lives outside the worker-visible workspace; it is required so the check
    always fails closed. The contract says which functions are mandated, so
    missing integrity metadata is itself a mismatch — a worker deleting or
    editing .neurico/idea.yaml must not silence the guard. Where the original
    source file is still reachable (it is mounted read-only during Docker
    runs), the staged bytes are verified against the SOURCE, which a forged
    workspace-recorded sha256 cannot defeat.

    Returns one message per problem; an empty list means the mandated
    functions are intact. Workspaces whose contract declares no local
    functions trivially pass.
    """
    import yaml

    if not isinstance(idea, dict):
        raise ValueError(
            "staged_function_mismatches requires the trusted submitted idea; "
            "verifying against the worker-writable workspace record alone "
            "would fail open")

    work_dir = Path(work_dir)

    def _functions_of(spec) -> List[Dict[str, Any]]:
        inner = spec.get('idea') if isinstance(spec.get('idea'), dict) else spec
        resources = inner.get('local_resources')
        if not isinstance(resources, dict):
            return []
        return [e for e in resources.get('functions') or []
                if isinstance(e, dict)]

    trusted_functions = _functions_of(idea)

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

    # Every load-bearing fact — which functions exist, where
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

        # Canonical staged location and expected source come from the same
        # destination protocol staging follows (_planned_destination), so
        # the guard always looks exactly where staging wrote.
        try:
            staged, source_str = _planned_destination(
                work_dir, 'functions', trusted, taken)
        except ValueError as exc:
            mismatches.append(str(exc))
            continue
        if staged is None:
            mismatches.append(
                f"mandated function '{label}' declares no usable path")
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


def _ignore_staged_datasets(work_dir: Path) -> None:
    """Append the staged-datasets directories to the workspace .gitignore."""
    gitignore = work_dir / ".gitignore"
    existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ""
    existing_lines = existing.splitlines()
    missing = [p for p in (f"{DATASETS_STAGING_DIR}/", f"{SEALED_STAGING_DIR}/")
               if p not in existing_lines]
    if not missing:
        return
    section = ("\n# Staged local datasets (copied from the submitting machine)\n"
               + "\n".join(missing) + "\n")
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

    Covers: a local continuation source repo, unstaged local_resources
    entries, and local paper paths. Entries that already carry source_path
    were staged into the workspace and need no mount. Relative paths cannot
    be mounted meaningfully on another machine: canonicalize_local_paths()
    should have rewritten them at submit time, so finding one here is worth
    a loud warning rather than a silent skip.

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

    continuation = idea.get('continuation')
    if isinstance(continuation, dict):
        add(continuation.get('source_repo'))

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


def validate_continuation(idea: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Validate the idea.continuation section (continue-research mode).

    Requires source_repo and goal; each invariant must name a supported kind
    and carry that kind's field (protected_path: path, check: command,
    statement: text). A missing reason is a warning: agents obey constraints
    better when told why they exist.

    Args:
        idea: The inner idea dictionary (idea_spec['idea'])

    Returns:
        Tuple of (errors, warnings) message lists
    """
    errors = []
    warnings = []

    continuation = idea.get('continuation')
    if continuation is None:
        return errors, warnings

    if not isinstance(continuation, dict):
        errors.append("continuation must be a mapping with 'source_repo' and 'goal'")
        return errors, warnings

    if not continuation.get('source_repo'):
        errors.append("continuation: missing 'source_repo' (repository path or URL)")
    goal = continuation.get('goal')
    if not goal or not str(goal).strip():
        errors.append("continuation: missing 'goal' (what to optimize is required)")
    elif len(str(goal).strip()) < 10:
        warnings.append("continuation.goal is very short; state the direction of "
                        "improvement so proposals stay aimed at it")

    invariants = continuation.get('invariants')
    if invariants is None:
        return errors, warnings
    if not isinstance(invariants, list):
        errors.append("continuation.invariants must be a list")
        return errors, warnings

    for idx, invariant in enumerate(invariants):
        label = f"continuation.invariants[{idx}]"
        if not isinstance(invariant, dict):
            errors.append(f"{label}: must be a mapping with 'kind'")
            continue
        kind = invariant.get('kind')
        if kind not in INVARIANT_KINDS:
            errors.append(f"{label}: unknown kind '{kind}' "
                          f"(supported: {', '.join(INVARIANT_KINDS)})")
            continue
        required_field = INVARIANT_KINDS[kind]
        if not invariant.get(required_field):
            errors.append(f"{label}: kind '{kind}' requires '{required_field}'")
        if kind == 'protected_path' and invariant.get('path'):
            try:
                normalize_protected_path(invariant['path'])
            except ValueError as exc:
                errors.append(f"{label}: {exc}")
        if not invariant.get('reason'):
            warnings.append(f"{label}: no 'reason' given; agents follow constraints "
                            f"better when told why they exist")

    return errors, warnings


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
