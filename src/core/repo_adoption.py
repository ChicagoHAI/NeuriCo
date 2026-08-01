"""
Repo Adoption - Turn an existing repository into a continue-research workspace

Continue-research runs start from a repository the user already has (local
path or GitHub URL) rather than a NeuriCo-created workspace. Adoption makes a
private working copy under the runs directory, never touching the original:

1. Clone (URL) or copy (local path) the source into the workspace directory
2. Ensure the copy is a git repository with a committed state, so the
   AutoResearch checkpoint machinery has an anchor
3. Optionally create a NeuriCo research repo on GitHub and point origin at
   it; the source's own remote, when present, is kept as 'upstream'
4. Record the adoption in .neurico/adoption.json and write the canonical
   .neurico/idea.yaml

Adoption is idempotent: a workspace with an adoption record is left as-is so
interrupted runs can resume.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import shutil
import subprocess

REMOTE_PREFIXES = ('http://', 'https://', 'git@')

ADOPTION_RECORD = ".neurico/adoption.json"


def is_remote_repo(source: str) -> bool:
    """True when the continuation source is a URL rather than a local path."""
    return str(source).startswith(REMOTE_PREFIXES)


def _sealed_entries_inside_repo(idea: Dict[str, Any],
                                repo_root: Optional[Path]) -> bool:
    """True when any sealed dataset's source lives inside the repository
    being adopted (a relative declaration is in-repo by construction)."""
    from core.local_resources import sealed_dataset_entries

    for entry in sealed_dataset_entries(idea):
        raw = str(entry.get('source_path') or entry.get('path') or '')
        if not raw or raw.startswith(('http://', 'https://', 'git@')):
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            return True
        if repo_root is not None:
            try:
                path.resolve().relative_to(Path(repo_root).resolve())
                return True
            except (ValueError, OSError):
                continue
    return False


def _warn_external_symlinks(work_dir: Path, source_root: Path) -> None:
    """
    Flag copied symlinks that will not survive the move into the workspace.

    Relative links are resolved against their location in the COPY and are
    fine when they stay inside the workspace (ordinary in-repo links).
    Absolute links are broken either way: a target outside the source repo
    is external material that was deliberately NOT copied in, and a target
    INSIDE the source repo points at the read-only mount during runs and
    dangles entirely once the source is unmounted or on another machine —
    it should be declared relative in the source repo instead.
    """
    work_resolved = work_dir.resolve()
    external = []
    absolute_into_source = []
    for path in work_dir.rglob('*'):
        if not path.is_symlink():
            continue
        raw_target = Path(os.readlink(path))
        rel_name = path.relative_to(work_dir)
        if raw_target.is_absolute():
            try:
                raw_target.resolve().relative_to(Path(source_root).resolve())
                absolute_into_source.append(f"{rel_name} -> {raw_target}")
            except (ValueError, OSError):
                external.append(f"{rel_name} -> {raw_target}")
        else:
            resolved = (path.parent / raw_target).resolve()
            try:
                resolved.relative_to(work_resolved)
            except ValueError:
                external.append(f"{rel_name} -> {raw_target}")
    if external:
        print("   ⚠️  Symlinks pointing outside the repository were preserved "
              "as links (their targets are NOT copied in and will not resolve "
              "in the workspace):")
        for entry in external:
            print(f"      - {entry}")
    if absolute_into_source:
        print("   ⚠️  Symlinks with ABSOLUTE targets inside the source "
              "repository will dangle once the source is not mounted; "
              "consider making them relative in the source repo:")
        for entry in absolute_into_source:
            print(f"      - {entry}")


def _git(work_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the workspace with a stable committer identity."""
    return subprocess.run(
        ["git", "-c", "user.email=neurico@local", "-c", "user.name=NeuriCo", *args],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
    )


def adopt_repository(
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    github_manager=None,
    provider: Optional[str] = None,
    private: bool = False,
    no_hash: bool = False,
) -> Dict[str, Any]:
    """
    Adopt the continuation source repository into work_dir.

    Args:
        idea: Full idea specification (must carry idea.continuation.source_repo)
        idea_id: Idea identifier (used for GitHub repo naming)
        work_dir: Workspace directory to adopt into
        github_manager: When provided, create a NeuriCo research repo and
            point origin at it (mirrors the normal-run GitHub option)
        provider: AI provider name for repo naming
        private: Create the GitHub repo as private
        no_hash: Skip the random hash in the GitHub repo name

    Returns:
        Dict with: adopted (False when resuming an existing adoption),
        source_repo, mode ('clone' | 'copy'), github_url (None without GitHub)

    Raises:
        ValueError: If the source is missing, is the workspace itself, or the
            workspace is non-empty without an adoption record
        FileNotFoundError: If a local source path does not exist (in Docker
            this usually means the path was not mounted; run.sh mounts the
            paths listed in ideas/mounts/<idea_id>.txt)
        RuntimeError: If cloning fails
    """
    import yaml

    work_dir = Path(work_dir)
    source = str(idea.get('idea', {}).get('continuation', {}).get('source_repo', '')).strip()
    if not source:
        raise ValueError("adopt_repository: idea has no continuation.source_repo")

    # Idempotent resume: a recorded adoption is left untouched
    record_path = work_dir / ADOPTION_RECORD
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            record = {}
        print(f"↩️  Workspace already adopted from {record.get('source_repo', source)}; resuming.")
        record['adopted'] = False
        return record

    if work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError(
            f"Workspace {work_dir} is not empty and has no adoption record. "
            "Use --force-fresh semantics by removing it, or pick a new idea id."
        )

    print(f"📦 Adopting repository for continue-research")
    print(f"   Source: {source}")
    print(f"   Workspace: {work_dir}")

    if is_remote_repo(source):
        mode = 'clone'
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        clone = subprocess.run(
            ["git", "clone", source, str(work_dir)],
            capture_output=True, text=True,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed for {source}: {clone.stderr.strip()}")
    else:
        mode = 'copy'
        source_path = Path(source).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(
                f"continuation source repo not found: {source_path} "
                "(inside Docker, local paths must be mounted; run.sh mounts "
                f"the paths listed in ideas/mounts/{idea_id}.txt)"
            )
        source_resolved = source_path.resolve()
        work_resolved = work_dir.resolve() if work_dir.exists() else work_dir
        if source_resolved == work_resolved or work_dir.is_relative_to(source_resolved):
            raise ValueError(
                f"continuation source {source_resolved} overlaps the workspace "
                f"{work_dir}; adoption must copy, never adopt in place"
            )
        # symlinks=True preserves links as links: dereferencing would turn a
        # symlink to external material (a private dataset, a config file, a
        # huge directory) into real workspace content that later commits and
        # pushes would publish.
        shutil.copytree(source_resolved, work_dir, dirs_exist_ok=True,
                        symlinks=True, ignore_dangling_symlinks=True)
        _warn_external_symlinks(work_dir, source_resolved)

    # A sealed dataset that lives inside the source repository also lives in
    # its git HISTORY: preserving that history would keep the sealed bytes
    # readable through git long after staging removes the working copy.
    # Adopt with a fresh history instead — the checkpoint machinery only
    # needs an anchor commit.
    if _sealed_entries_inside_repo(
            idea, source_resolved if mode == 'copy' else work_dir.resolve()):
        if (work_dir / ".git").exists():
            shutil.rmtree(work_dir / ".git")
        print("   🔒 Sealed data lives inside the source repository; adopting "
              "with a fresh git history (the original history would retain "
              "the sealed bytes).")

    # Ensure a git anchor for the checkpoint machinery: init when the source
    # was not a repo, and commit any dirty state so the adopted baseline is
    # exactly what the checkpoints reproduce
    if not (work_dir / ".git").exists():
        _git(work_dir, "init")

    # Keep Python bytecode out of iteration checkpoints; adopted repos often
    # have no .gitignore of their own
    gitignore = work_dir / ".gitignore"
    existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ""
    if "__pycache__/" not in existing.splitlines():
        section = "\n# Added at adoption for continue-research checkpoints\n__pycache__/\n*.pyc\n"
        gitignore.write_text(existing.rstrip("\n") + "\n" + section if existing
                             else section.lstrip("\n"), encoding='utf-8')
    status = _git(work_dir, "status", "--porcelain")
    if status.stdout.strip():
        _git(work_dir, "add", "-A")
        _git(work_dir, "commit", "-m", f"Adopt {source} for continue-research")

    # Optional GitHub backup repo, mirroring the normal-run GitHub option.
    # The source's own remote is preserved as 'upstream' for provenance.
    github_url = None
    if github_manager is not None:
        try:
            idea_spec = idea.get('idea', {})
            remotes = _git(work_dir, "remote").stdout.split()
            if 'origin' in remotes:
                _git(work_dir, "remote", "rename", "origin", "upstream")
            repo_info = github_manager.create_research_repo(
                idea_id=idea_id,
                title=idea_spec.get('title', idea_id),
                description=f"Continue-research: {idea_spec.get('title', idea_id)}",
                private=private,
                domain=idea_spec.get('domain', 'research'),
                provider=provider,
                no_hash=no_hash,
            )
            github_url = repo_info['repo_url']
            _git(work_dir, "remote", "add", "origin", repo_info['clone_url'])
            push = _git(work_dir, "push", "-u", "origin", "HEAD")
            if push.returncode != 0:
                print(f"⚠️  Initial push to {github_url} failed: {push.stderr.strip()}")
            else:
                print(f"✅ Adopted workspace backed up to: {github_url}")
        except Exception as e:
            print(f"⚠️  GitHub repository creation failed: {e}")
            print("   Continuing with the local workspace only.")
            github_url = None

    # Record the adoption and write the canonical workspace idea. Both files
    # live in a workspace that adoption may push to GitHub, so host-machine
    # paths are redacted: the idea goes through workspace_contract_copy (the
    # single redaction boundary) and the record keeps only the repo's name
    # for a local source (full URLs are remote provenance and stay).
    from core.local_resources import workspace_contract_copy
    record = {
        'source_repo': source if is_remote_repo(source) else Path(source).name,
        'mode': mode,
        'adopted_at': datetime.now().isoformat(),
        'github_url': github_url,
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding='utf-8')
    with open(work_dir / ".neurico" / "idea.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(workspace_contract_copy(idea), f,
                  default_flow_style=False, sort_keys=False)

    print(f"✓ Repository adopted ({mode})")
    record['adopted'] = True
    return record
