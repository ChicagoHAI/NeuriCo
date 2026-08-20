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

# Trusted baseline of the protected paths, written by Stage 1 and read by the
# generated eval.py to enforce `protected_path` invariants as a hard scoring
# guardrail (the `protected_paths_unchanged` property). Written in this trusted
# phase before the optimizing agent exists. Records the git commit the protected
# paths were captured in, not a hash: git is the single source of truth for
# whether they changed, so there is no hand-rolled hash for eval.py to mirror
# (and drift from).
PROTECTED_BASELINE_FILE = "scoring/protected_baseline.json"


def _gitignore_add(work_dir: Path, line: str) -> None:
    gitignore = Path(work_dir) / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if line not in existing.splitlines():
        prefix = existing.rstrip("\n") + "\n" if existing.strip() else ""
        gitignore.write_text(prefix + line + "\n", encoding="utf-8")


def write_protected_baseline(idea: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    """Anchor the `protected_path` invariants to a git baseline commit.

    Written in Stage 1 (no optimizing agent) so the generated eval.py can flag
    any change to a protected path. We use git purely as an IMMUTABLE, content-
    addressed baseline STORE: force-add each declared protected path (so even a
    gitignored one is captured), commit if that staged anything, and record the
    resulting commit sha. eval.py reads the baseline objects back with
    `git ls-tree` / `git cat-file blob` (which the agent cannot forge at a fixed
    sha) and compares them to the real filesystem with plain Python reads.

    It deliberately does NOT record a hand-rolled hash (that had to be mirrored
    in eval.py byte-for-byte and drifted), and eval.py deliberately does NOT use
    `git diff` / `git ls-files` to detect change: the Stage 2 agent controls the
    workspace .git (index skip bits, clean filters, core.fileMode, .gitignore),
    each of which can make git's working-tree view report a modified protected
    file as clean. Reading immutable blobs + raw filesystem bytes is immune to
    all of those, and the comparison lives only in eval.py, so nothing drifts.

    Returns {"baseline_ref": <sha>, "paths": [...]} (empty, and no file written,
    when no protected_path invariants are declared).
    """
    from core.local_resources import protected_path_prefixes
    from core.repo_adoption import _git

    work_dir = Path(work_dir)
    paths = list(protected_path_prefixes(idea))
    if not paths:
        return {}

    # Force-add every declared path that exists (-f so a gitignored protected
    # path is still tracked in the baseline). A path absent at prepare time is
    # still recorded: its later creation shows up as a diff or an untracked file.
    for rel in paths:
        if (work_dir / rel).exists():
            _git(work_dir, "add", "-f", "--", rel)
    # Commit only if force-adding staged something new; otherwise the current
    # HEAD (the anchor commit) already captures the protected paths.
    if _git(work_dir, "diff", "--cached", "--quiet").returncode != 0:
        _git(work_dir, "commit", "-m",
             "continue-research: protected-path baseline")
    baseline_ref = _git(work_dir, "rev-parse", "HEAD").stdout.strip()

    baseline: Dict[str, Any] = {"baseline_ref": baseline_ref, "paths": paths}
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


def _content_signature(root: Path) -> str:
    """sha256 of a file's bytes, or of a directory tree (sorted relpath+bytes)."""
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


def _same_content(a: Path, b: Path) -> bool:
    """True when two paths hold identical content (file bytes, or dir tree).

    Used to accept an already-staged held-out destination only when it still
    matches its declared source, so a partial, stale, or wrong existing copy is
    re-staged instead of trusted on existence alone.
    """
    a, b = Path(a), Path(b)
    if a.is_dir() != b.is_dir():
        return False
    if a.is_file() and a.stat().st_size != b.stat().st_size:
        return False
    return _content_signature(a) == _content_signature(b)


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
    taken: set = set()
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
        # Disambiguate a basename collision: two declared sources with the same
        # basename would otherwise map to the same data/.test/<name>, and the
        # second would silently resolve to the first's bytes. Suffix later
        # collisions (name.jsonl -> name-2.jsonl) so every source keeps its own
        # copy. An already-rewritten eval-facing path keeps its resolved name.
        already_rewritten = raw.replace("\\", "/").startswith(
            SEALED_STAGING_DIR + "/")
        if already_rewritten:
            name = Path(raw).name
        elif name in taken:
            stem, suffix = Path(name).stem, Path(name).suffix
            n = 2
            while f"{stem}-{n}{suffix}" in taken:
                n += 1
            name = f"{stem}-{n}{suffix}"
        taken.add(name)
        dst = dest_root / name
        rewritten = f"{SEALED_STAGING_DIR}/{name}"
        src = None if already_rewritten else _resolve_source(raw, work_dir, base_dir)
        # Accept the already-staged destination in three idempotent cases:
        #   - the path was already rewritten to the eval-facing form;
        #   - the source is GONE and the destination exists: this is an in-repo
        #     sealed source that the pre-commit-hook pass already MOVED (the
        #     source is removed only AFTER a complete copy, so source-absent +
        #     destination-present means the move finished). stage_held_out_data
        #     runs twice per prepare (in the hook, then again after), so the
        #     second pass MUST accept the moved copy rather than fail;
        #   - the source is still present AND its content matches the staged
        #     copy (an interrupted-then-resumed prepare).
        # A destination that exists but MISMATCHES a still-present source is a
        # partial/stale copy and falls through to re-stage.
        moved_source = dst.exists() and src is not None and not src.exists()
        if already_rewritten or moved_source or (
                dst.exists() and src is not None and src.exists()
                and _same_content(src, dst)):
            entry.setdefault("source_path", raw)
            entry["path"] = rewritten
            staged.append(name)
            continue
        if src is None or not src.exists():
            raise FileNotFoundError(
                f"held-out dataset source not found: {raw} "
                f"(resolved {src if src is not None else raw})")
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


def verify_invariant_guardrails(idea: Dict[str, Any], work_dir: Path) -> None:
    """Confirm the generated eval.py actually enforces every declared invariant.

    The eval_verifier only checks routing/transcription/format, so a generated
    eval.py could silently omit or misimplement a `protected_path` or `check`
    guardrail. This is a mechanical, behavioral cross-check run in Stage 1 (no
    optimizing agent): after the baseline is scored, every declared invariant
    must have produced its guardrail property AND passed at baseline (nothing
    has changed yet, and the check command is expected to pass on the adopted
    repo). A missing or failing guardrail fails Stage 1 loudly rather than
    letting an unenforced invariant reach optimization.
    """
    from core.local_resources import (
        protected_path_prefixes,
        continuation_check_commands,
    )

    work_dir = Path(work_dir)
    protected = protected_path_prefixes(idea)
    checks = continuation_check_commands(idea)
    if not protected and not checks:
        return

    def _load(rel: str) -> Dict[str, Any]:
        try:
            payload = json.loads((work_dir / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"continuation invariant check: cannot read {rel}: {exc}")
        props = payload.get("properties")
        return props if isinstance(props, dict) else {}

    targets = _load("scoring/targets.json")
    results = _load("scoring/results.json")
    problems: List[str] = []

    if protected:
        prop = results.get("protected_paths_unchanged")
        if prop is None:
            problems.append(
                "declared protected_path invariant(s) but the generated eval.py "
                "produced no 'protected_paths_unchanged' property")
        elif not prop.get("satisfied"):
            problems.append(
                "'protected_paths_unchanged' did not pass at baseline "
                f"(value {prop.get('value')!r}); nothing has changed, so the "
                "generated protected-path check is misimplemented")

    # Each declared check command must appear as a user guardrail property
    # (matched by source_text) and pass at baseline.
    scored_by_cmd = {
        str(spec.get("source_text")).strip(): name
        for name, spec in targets.items()
        if isinstance(spec, dict) and spec.get("source") == "user"
        and spec.get("source_text")
    }
    for cmd in checks:
        name = scored_by_cmd.get(cmd)
        if name is None:
            problems.append(
                f"check invariant not encoded as a guardrail property: {cmd!r}")
            continue
        prop = results.get(name)
        if prop is None or not prop.get("satisfied"):
            problems.append(
                f"check guardrail {name!r} for {cmd!r} did not pass at baseline")

    if problems:
        raise RuntimeError(
            "continuation invariants are not correctly enforced by the "
            "generated eval.py:\n  - " + "\n  - ".join(problems))


def prepare_continuation_workspace(
    idea: Dict[str, Any],
    idea_id: str,
    work_dir: Path,
    *,
    templates_dir: Path,
    provider: str = "claude",
    full_permissions: bool = True,
    github_manager=None,
    private: bool = False,
    no_hash: bool = False,
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
        private=private, no_hash=no_hash,
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

    # 4b. Anchor every declared protected_path to a git baseline commit here (no
    #    optimizing agent), from the adopted+staged tree. The generated eval.py
    #    asks git whether any protected path differs from this ref to enforce
    #    protected_path invariants as the hard `protected_paths_unchanged`
    #    scoring guardrail.
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

    # 5b. Mechanical cross-check that the generated eval.py actually enforces
    #    every declared invariant (the eval_verifier does not). Runs here, in
    #    the trusted phase, so an omitted or misimplemented guardrail fails
    #    Stage 1 rather than silently reaching optimization.
    verify_invariant_guardrails(idea, work_dir)

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
