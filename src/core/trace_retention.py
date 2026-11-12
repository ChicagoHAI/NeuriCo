"""Optional observational recording at existing execution boundaries.

The embedding runner owns storage. Core research runs install no recorder by
default, and recording failures never change research control flow.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator


_recorder: Callable[[str, dict[str, Any]], Any] | None = None
_invocation: ContextVar[str | None] = ContextVar("trace_invocation", default=None)
TRACE_GAP_MARKER = "NEURICO_TRACE_COLLECTION_GAP"


def set_trace_recorder(recorder: Callable[[str, dict[str, Any]], Any] | None) -> None:
    """Install an optional recorder for this run; it owns no workflow decisions."""
    global _recorder
    _recorder = recorder


def retain_trace(event: str, **fields: Any) -> Any:
    if _recorder is None:
        return None
    try:
        return _recorder(event, fields)
    except Exception as error:
        # The parent retains this marker even if the archive itself is unwritable.
        print(f"{TRACE_GAP_MARKER} {event} {type(error).__name__}", flush=True)
        return None


def current_trace_invocation() -> str | None:
    return _invocation.get()


@contextmanager
def retained_invocation(kind: str, **inputs: Any) -> Iterator[dict[str, Any]]:
    identity = retain_trace("invocation_start", kind=kind, **inputs)
    token = _invocation.set(identity)
    outcome: dict[str, Any] = {}
    try:
        yield outcome
    except BaseException as error:
        outcome["error_type"] = type(error).__name__
        raise
    finally:
        retain_trace("invocation_finish", invocation_id=identity, kind=kind, outcome=outcome,
                     log_file=inputs.get("log_file"), transcript_file=inputs.get("transcript_file"))
        _invocation.reset(token)
