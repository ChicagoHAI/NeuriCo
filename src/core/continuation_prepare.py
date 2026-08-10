"""
Continuation preparation -- Stage 1 of continue-research.

Turns an existing repository + a continuation contract (goal, invariants) +
declared evaluation materials into a STANDARD NeuriCo workspace, then stops.

The point of the two-stage design: NO optimizing (reward-seeking) agent runs
here. Adoption, held-out staging, and scorer generation are the trusted setup,
and they complete before Stage 2 ever spawns the optimizing agent. So the agent
never coexists with the raw materials, the scorer generation, or any protocol
regeneration -- which is what removes the whole class of tampering/leak bugs
the single-stage design kept hitting.

The output is an ordinary NeuriCo workspace:

    <work_dir>/
        <adopted repo>                 fresh git history + anchor commit
        scoring/{eval.py,targets.json,interface.md}   rule-maker generated
        data/.test/...                 held-out materials, gitignored
        .neurico/idea.yaml             redacted continuation contract

Stage 2 (a plain NeuriCo run) consumes this exactly as it would any workspace;
it needs no continue-research-specific code.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Held-out evaluation data lands here, gitignored. eval.py reads it at this
# workspace-relative path; Stage 2's ordinary scoring seal relocates it out of
# the workspace while agents run (the same protection every NeuriCo run gets).
SEALED_STAGING_DIR = "data/.test"

# Trusted baseline of protected-path content, written by Stage 1 and read by the
# generated eval.py to enforce `protected_path` invariants as a hard scoring
# guardrail (the `protected_paths_unchanged` property). Written in this trusted
# phase before the optimizing agent exists, so its hashes cannot be forged.
PROTECTED_BASELINE_FILE = "scoring/protected_baseline.json"


def _gitignore_add(work_dir: Path, line: str) -> None:
    gitignore = Path(work_dir) / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if line not in existing.splitlines():
        prefix = existing.rstrip("\n") + "\n" if existing.strip() else ""
        gitignore.write_text(prefix + line + "\n", encoding="utf-8")


def _hash_protected_path(root: Path) -> str:
    """sha256 of a protected file, or of a directory tree (sorted relpath+bytes).

    A directory hash folds in each file's relative path and content so adding,
    removing, renaming, or editing any file under a protected prefix changes it.
    """
    root = Path(root)
    digest = hashlib.sha256()
    if root.is_file():
        digest.update(root.read_bytes())
        return digest.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_protected_baseline(idea: Dict[str, Any], work_dir: Path) -> Dict[str, str]:
    """Record sha256 of each declared `protected_path` into the trusted baseline.

    Written in Stage 1 (no optimizing agent) so the generated eval.py can flag
    any change to a protected path. Returns the {path: sha256} map (empty when
    no protected_path invariants are declared, in which case no file is written).
    """
    from core.local_resources import protected_path_prefixes

    work_dir = Path(work_dir)
    baseline: Dict[str, str] = {}
    for rel in protected_path_prefixes(idea):
        target = work_dir / rel
        if target.exists():
            baseline[rel] = _hash_protected_path(target)
        # A declared protected path that is absent at prepare time is recorded
        # as a sentinel, so its later CREATION is also a guardrail violation.
        else:
            baseline[rel] = "__absent__"
    if baseline:
        dst = work_dir / PROTECTED_BASELINE_FILE
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
    return baseline


def _resolve_source(raw: str, work_dir: Path, base_dir: Optional[Path]) -> Path:
    """Resolve a declared held-out source path.

    An absolute or ~ path is a host material; a relative path is resolved
    against base_dir (submitting dir) if given, else treated as in-workspace.
    """
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    if base_dir is not None:
        candidate = (Path(base_dir) / p)
        if candidate.exists():
            return candidate
    return Path(work_dir) / p


def stage_held_out_data(idea: Dict[str, Any], work_dir: Path,
                        base_dir: Optional[Path] = None) -> List[str]:
    """Copy declared held-out (sealed) datasets into gitignored data/.test.

    A simple, trusted copy: Stage 1 has no optimizing agent, so there is
    nothing to hide from at this point. Each sealed entry's ``path`` is
    rewritten to its eval-facing ``data/.test/<name>``. An in-workspace source
    (held-out data committed inside the adopted repo) is MOVED, so only the
    gitignored copy remains; an external host source is copied.
    """
    from core.local_resources import sealed_dataset_entries

    entries = sealed_dataset_entries(idea)
    if not entries:
        return []
    dest_root = Path(work_dir) / "data" / ".test"
    dest_root.mkdir(parents=True, exist_ok=True)
    staged: List[str] = []
    for entry in entries:
        raw = str(entry.get("source_path") or entry.get("path") or "").strip()
        if not raw:
            continue
        # Sanitize the declared name to a bare basename so a name containing
        # '/' or '..' cannot escape data/.test (the contract is trusted, but
        # this matches stage_local_resources and costs nothing).
        name = Path(str(entry.get("name") or Path(raw).name)).name
        if not name or name in (".", ".."):
            raise ValueError(
                f"held-out dataset has an unusable name: {entry.get('name')!r}")
        dst = dest_root / name
        rewritten = f"{SEALED_STAGING_DIR}/{name}"
        # Idempotent re-prepare: the path was already rewritten to the
        # eval-facing form, OR the destination already holds the staged copy
        # (a resume after Stage 1 partially completed -- e.g. baseline scoring
        # failed after the move). In both cases the move is done; just
        # (re)assert the eval-facing path so the in-memory idea is consistent.
        if raw.replace("\\", "/").startswith(SEALED_STAGING_DIR + "/") or dst.exists():
            entry.setdefault("source_path", raw)
            entry["path"] = rewritten
            staged.append(name)
            continue
        src = _resolve_source(raw, work_dir, base_dir)
        if not src.exists():
            raise FileNotFoundError(
                f"held-out dataset source not found: {raw} (resolved {src})")
        if src.resolve() != dst.resolve():
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, symlinks=False)
            else:
                shutil.copy2(src, dst, follow_symlinks=True)
            # Move semantics for an in-workspace (in-repo) source: remove the
            # readable original so only the gitignored data/.test copy remains.
            try:
                src.resolve().relative_to(Path(work_dir).resolve())
                if src.is_dir():
                    shutil.rmtree(src)
                elif src.exists():
                    src.unlink()
            except ValueError:
                pass  # external host source -- leave it in place
        entry["source_path"] = raw
        entry["path"] = rewritten
        staged.append(name)
    _gitignore_add(work_dir, "data/.test/")
    return staged


def _idea_without_sealed(idea: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of the idea with sealed datasets removed from local_resources,
    so the normal stager handles only non-held-out resources."""
    out = copy.deepcopy(idea)
    inner = out.get("idea", out)
    resources = inner.get("local_resources") if isinstance(inner, dict) else None
    if isinstance(resources, dict) and isinstance(resources.get("datasets"), list):
        resources["datasets"] = [
            d for d in resources["datasets"]
            if not (isinstance(d, dict) and d.get("sealed"))
        ]
    return out


PREPARED_MARKER = ".neurico/continuation_prepared.json"


def _write_prepared_marker(work_dir: Path, idea_id: str) -> None:
    """Record that Stage 1 finished, so the runner's isolation backstop can
    tell a properly prepared workspace from a mid-prepare one."""
    import json
    target = Path(work_dir) / PREPARED_MARKER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"idea_id": idea_id, "stage": "prepared"}, indent=2) + "\n",
        encoding="utf-8")


def _write_workspace_idea(idea: Dict[str, Any], work_dir: Path) -> None:
    """Write the redacted continuation contract to .neurico/idea.yaml so the
    bootstrap rule maker (which substitutes {idea_yaml}) and Stage 2 both see
    the goal, invariants, and the data/.test held-out reference."""
    import yaml
    from core.local_resources import workspace_contract_copy

    target = Path(work_dir) / ".neurico" / "idea.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.dump(workspace_contract_copy(idea), handle,
                  default_flow_style=False, sort_keys=False)


def prepare_continuation_workspace(
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    *,
    templates_dir: Path,
    provider: str = "claude",
    full_permissions: bool = True,
    github_manager=None,
    rule_maker_timeout: int = 1800,
    scorer_timeout: int = 600,
    manifest_trimmer_timeout: int = 300,
    autoresearch_history_dir: Optional[Path] = None,
    prepare_workspace: Optional[Callable[[Path], None]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Stage 1: build a SCORED standard NeuriCo workspace from a continuation
    contract.

    Runs only the trusted setup agents (manifest trimmer, bootstrap rule maker)
    and the scorer -- NO optimizing (reward-seeking) agent. On return,
    ``work_dir`` is an ordinary NeuriCo workspace with a scored baseline and a
    recorded ``current_best`` in ``.neurico/autoresearch_state.json``, ready for
    a plain ``continue_from_current_best`` (Stage 2) with no continue-research
    code.
    """
    from core.repo_adoption import adopt_repository
    from core.local_resources import stage_local_resources
    from core.autoresearch import construct_bootstrap_initial_node

    work_dir = Path(work_dir)

    # 1+2. Adopt the repo (fresh git history, source remotes scrubbed, nested
    #    .git removed), staging held-out materials into the gitignored
    #    data/.test BEFORE the anchor commit via the pre-commit hook. Ordering
    #    matters: an in-repo held-out file must be moved out before the commit,
    #    or the fresh history (and the GitHub backup) would capture the
    #    plaintext -- readable by the Stage 2 agent through `git show`.
    adoption = adopt_repository(
        idea, idea_id, work_dir, github_manager=github_manager, provider=provider,
        pre_commit_hook=lambda wd: stage_held_out_data(idea, wd, base_dir=base_dir))

    # Re-assert the eval-facing held-out paths in this process. On a fresh
    # adoption the hook already staged and rewrote them; on an idempotent
    # resume the hook did not run (the anchor commit already exists), so this
    # call performs the rewrite (and is a no-op move -- the data is already in
    # data/.test). Either way the in-memory idea ends up consistent.
    held_out = stage_held_out_data(idea, work_dir, base_dir=base_dir)

    # 3. Non-sealed local resources through the normal stager.
    stage_local_resources(work_dir, _idea_without_sealed(idea), base_dir=base_dir)

    # 4. Publish the full (redacted) contract so the rule maker and Stage 2 see
    #    goal + invariants + the data/.test held-out reference.
    _write_workspace_idea(idea, work_dir)

    # 4b. Record the trusted baseline hashes of every declared protected_path,
    #    computed here (no optimizing agent) from the adopted+staged tree. The
    #    generated eval.py compares against this to enforce protected_path
    #    invariants as the hard `protected_paths_unchanged` scoring guardrail.
    write_protected_baseline(idea, work_dir)

    # 5. Generate the scorer AND score the baseline, all in this trusted phase,
    #    by reusing main's bootstrap-baseline path. construct_bootstrap runs the
    #    manifest trimmer + bootstrap rule maker (which bakes the declared
    #    check-invariants in as guardrail properties), scores the adopted repo
    #    against the held-out data, and records current_best. No optimizing
    #    agent runs. On return the workspace is a standard scored NeuriCo
    #    workspace ready for --continue-autoresearch.
    baseline = construct_bootstrap_initial_node(
        idea=idea,
        idea_id=idea_id,
        work_dir=work_dir,
        templates_dir=Path(templates_dir),
        provider=provider,
        full_permissions=full_permissions,
        rule_maker_timeout=rule_maker_timeout,
        scorer_timeout=scorer_timeout,
        manifest_trimmer_timeout=manifest_trimmer_timeout,
        autoresearch_history_dir=autoresearch_history_dir,
        prepare_workspace=prepare_workspace,
    )
    if not baseline.get("success"):
        raise RuntimeError(
            f"continuation prepare: baseline construction failed: "
            f"{baseline.get('reason') or baseline}")

    # Trusted "Stage 1 complete" marker. The runner uses it (together with a
    # check that the source materials are no longer readable) as a
    # defense-in-depth backstop so Stage 2 never runs in a container that still
    # has the source repo / held-out materials mounted.
    _write_prepared_marker(work_dir, idea_id)

    # The workspace is now a plain scored NeuriCo workspace. Stage 2
    # (continue_from_current_best) consumes it with no continue-research code.
    return {
        "work_dir": str(work_dir),
        "prepared": True,
        "adoption": adoption,
        "held_out": held_out,
        "baseline": baseline,
        "current_best_sha": baseline.get("current_best_sha"),
        "scoring_ready": True,
    }
