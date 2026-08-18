"""Shared Git subprocess plumbing for runtime-owned HITL operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping


@dataclass(frozen=True)
class GitCommandFailure:
    argv: tuple[str, ...]
    returncode: int
    stdout: str | bytes
    stderr: str | bytes


class GitCommandError(RuntimeError):
    def __init__(self, failure: GitCommandFailure):
        detail_value = failure.stderr or failure.stdout or "unknown Git error"
        detail = (
            detail_value.decode("utf-8", errors="replace")
            if isinstance(detail_value, bytes)
            else str(detail_value)
        ).strip()
        super().__init__(f"Git command failed ({' '.join(failure.argv)}): {detail}")
        self.failure = failure


def run_git(
    work_dir: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    text: bool = True,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    argv = ("git", "-C", str(Path(work_dir)), *map(str, args))
    completed = subprocess.run(
        list(argv),
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
        text=text,
        encoding="utf-8" if text else None,
        env={**os.environ, **dict(env or {})},
        check=False,
    )
    if check and completed.returncode:
        raise GitCommandError(
            GitCommandFailure(
                argv=argv,
                returncode=completed.returncode,
                stdout=completed.stdout or ("" if text else b""),
                stderr=completed.stderr or ("" if text else b""),
            )
        )
    return completed


def git_stdout(work_dir: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    completed = run_git(work_dir, *args, env=env)
    return str(completed.stdout)


def git_stdout_bytes(work_dir: Path, *args: str) -> bytes:
    completed = run_git(work_dir, *args, text=False)
    return bytes(completed.stdout)


def delete_git_ref(work_dir: Path, ref_name: str, *, strict: bool) -> None:
    ref = str(ref_name).strip()
    if not ref:
        return
    removed = run_git(work_dir, "update-ref", "-d", ref, check=False)
    if removed.returncode == 0:
        return
    exists = run_git(
        work_dir,
        "rev-parse",
        "--verify",
        "--quiet",
        ref,
        check=False,
        quiet=True,
    )
    if exists.returncode == 1 or not strict:
        return
    if exists.returncode != 0:
        raise RuntimeError("Runtime could not verify its temporary Git ref.")
    raise GitCommandError(
        GitCommandFailure(
            argv=("git", "-C", str(Path(work_dir)), "update-ref", "-d", ref),
            returncode=removed.returncode,
            stdout=removed.stdout or "",
            stderr=removed.stderr or "",
        )
    )
