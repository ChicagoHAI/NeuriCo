"""POSIX process ownership helpers for the Harbor adapter."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


_PR_SET_CHILD_SUBREAPER = 36
_DESCENDANT_TERMINATION_GRACE_SECONDS = 1.0
_DESCENDANT_KILL_GRACE_SECONDS = 1.0
_SUCCESSFUL_COMPLETION_EXIT_CODES = frozenset({0, 124})


def _linux_process_rows() -> list[tuple[int, int, int]]:
    """Read PID, parent PID, and process group from Linux procfs."""
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    rows: list[tuple[int, int, int]] = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat_line = (entry / "stat").read_text(encoding="utf-8")
            # The command name is parenthesized and may itself contain spaces.
            fields = stat_line[stat_line.rfind(")") + 2 :].split()
            rows.append((int(entry.name), int(fields[1]), int(fields[2])))
        except (IndexError, OSError, ValueError):
            continue
    return rows


def process_rows() -> list[tuple[int, int, int]]:
    """Return the process ancestry fields available on this POSIX host."""
    linux_rows = _linux_process_rows()
    if linux_rows:
        return linux_rows
    try:
        process_table = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    rows: list[tuple[int, int, int]] = []
    for line in process_table.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            rows.append(tuple(int(field) for field in fields))
        except ValueError:
            continue
    return rows


def _descendant_rows(
    root_pid: int,
    *,
    include_root: bool,
) -> list[tuple[int, int, int]]:
    rows = process_rows()
    descendants = {root_pid}
    while True:
        discovered = {pid for pid, parent_pid, _group_id in rows if parent_pid in descendants}
        expanded = descendants | discovered
        if expanded == descendants:
            break
        descendants = expanded
    if not include_root:
        descendants.discard(root_pid)
    return [row for row in rows if row[0] in descendants]


def owned_process_group_ids(root_pid: int) -> set[int]:
    """Return POSIX process groups currently descended from ``root_pid``."""
    if os.name != "posix":
        return set()
    rows = _descendant_rows(root_pid, include_root=True)
    if not rows:
        try:
            group_id = os.getpgid(root_pid)
        except (ProcessLookupError, PermissionError):
            return set()
        return {group_id} if group_id > 1 and group_id != os.getpgrp() else set()

    own_group = os.getpgrp()
    return {
        group_id for _pid, _parent_pid, group_id in rows if group_id > 1 and group_id != own_group
    }


def signal_process_groups(process_groups: set[int], signum: signal.Signals) -> None:
    """Signal only explicitly owned process groups."""
    for group_id in sorted(process_groups, reverse=True):
        try:
            os.killpg(group_id, signum)
        except (ProcessLookupError, PermissionError):
            continue


def enable_child_subreaper() -> bool:
    """Retain orphaned descendants under this process on Linux."""
    if sys.platform != "linux":
        return False

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    prctl.restype = ctypes.c_int
    if prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error_number = ctypes.get_errno() or errno.EINVAL
        raise OSError(error_number, "Could not retain Harbor child-process ownership")
    return True


def _reap_exited_children() -> None:
    while True:
        try:
            child_pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if child_pid == 0:
            return


def _signal_descendants(
    rows: list[tuple[int, int, int]],
    signum: signal.Signals,
) -> None:
    own_group = os.getpgrp()
    process_groups = {
        group_id for _pid, _parent_pid, group_id in rows if group_id > 1 and group_id != own_group
    }
    signal_process_groups(process_groups, signum)

    # Children that did not create their own group share ours and must be
    # signalled individually so cleanup never signals the supervisor itself.
    for pid, _parent_pid, group_id in rows:
        if group_id != own_group:
            continue
        try:
            os.kill(pid, signum)
        except (ProcessLookupError, PermissionError):
            continue


def terminate_owned_descendants() -> bool:
    """Terminate and reap every descendant retained by the Harbor child."""
    if os.name != "posix":
        return False
    root_pid = os.getpid()
    terminated = False

    for signum, grace_seconds in (
        (signal.SIGTERM, _DESCENDANT_TERMINATION_GRACE_SECONDS),
        (signal.SIGKILL, _DESCENDANT_KILL_GRACE_SECONDS),
    ):
        deadline = time.monotonic() + grace_seconds
        while True:
            _reap_exited_children()
            rows = _descendant_rows(root_pid, include_root=False)
            if not rows:
                return terminated
            terminated = True
            _signal_descendants(rows, signum)
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)

    _reap_exited_children()
    return terminated


def supervise(command: list[str]) -> int:
    """Keep Linux descendants owned until the manager's outcome is known.

    A separate supervisor keeps the subreaper alive even when the manager
    exits during cooperative shutdown or gets stuck unwinding its own stack.
    The adapter's existing timeout remains responsible for escalation. Failed,
    cancelled, and forcibly terminated runs clean every retained descendant;
    successful runs release task services for Harbor's verifier.
    """
    if not enable_child_subreaper():
        # Harbor uses Linux. Preserve the original PID and signal behavior for
        # local protocol checks on platforms without subreaper support.
        os.execvp(command[0], command)

    interrupted = False
    terminated = False
    completed_exit_code: int | None = None

    def request_interrupt(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    def request_termination(_signum: int, _frame: object) -> None:
        nonlocal terminated
        terminated = True

    signal.signal(signal.SIGINT, request_interrupt)
    signal.signal(signal.SIGTERM, request_termination)
    try:
        if terminated:
            completed_exit_code = 128 + signal.SIGTERM
            return completed_exit_code
        child = subprocess.Popen(command, start_new_session=True)
        interrupt_forwarded = False
        while True:
            if terminated:
                completed_exit_code = 128 + signal.SIGTERM
                return completed_exit_code
            return_code = child.poll()
            if return_code is not None:
                completed_exit_code = (
                    return_code if return_code >= 0 else 128 - return_code
                )
                return completed_exit_code
            if interrupted and not interrupt_forwarded:
                try:
                    child.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                interrupt_forwarded = True
            time.sleep(0.01)
    finally:
        # The parent also signals captured groups. Do not let another signal
        # interrupt cleanup before adopted children have been killed/reaped.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if (
            interrupted
            or terminated
            or completed_exit_code not in _SUCCESSFUL_COMPLETION_EXIT_CODES
        ):
            terminate_owned_descendants()
        else:
            # Provider launchers already reject and terminate their own
            # lingering process groups before NeuriCo can report success. Any
            # live descendants left here belong to the task and must remain
            # available to Harbor's verifier after this supervisor exits.
            _reap_exited_children()


if __name__ == "__main__":
    raise SystemExit(supervise(sys.argv[1:]))
