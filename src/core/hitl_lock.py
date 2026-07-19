"""HITL-only file locking without leaking POSIX imports into main NeuriCo."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - exercised on Windows only.
    fcntl = None  # type: ignore[assignment]


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Take an HITL runtime lock or fail clearly on unsupported platforms."""
    if fcntl is None:
        raise RuntimeError(
            "HITL runtime file locking requires a POSIX platform; ordinary NeuriCo remains available."
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
