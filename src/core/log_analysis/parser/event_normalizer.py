from typing import Any

from core.log_analysis.models import RawTranscriptEvent, TrajectoryStep, FailureRecord


IGNORED_RAW_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
}


def should_skip_raw_event(
    raw_type: str | None,
    item_type: str | None,
    message: Any = None,
) -> bool:
    """
    Skip transcript lifecycle records that do not add useful trajectory content.

    Phase 1 should preserve meaningful agent/tool actions, but avoid flooding the
    trajectory with thread/turn bookkeeping events.
    """
    if raw_type in IGNORED_RAW_TYPES:
        return True

    # Skip pure lifecycle item events only when they have no useful item type or text.
    if item_type is None and raw_type in {"item.started", "item.completed", "item.updated"} and not message:
        return True

    return False


def extract_file_path(raw: dict[str, Any], item: dict[str, Any]) -> str | None:
    """
    Extract a file path from known Codex transcript file-change shapes.

    Different transcript versions may store the path under different keys.
    Keep this defensive so Phase 1 can parse many historical logs.
    """
    direct_path = (
        item.get("path")
        or item.get("file_path")
        or item.get("file")
        or item.get("filename")
        or raw.get("path")
        or raw.get("file_path")
        or raw.get("file")
        or raw.get("filename")
    )

    if direct_path:
        return str(direct_path)

    # Some logs store file changes as a list of objects.
    changes = item.get("changes") or raw.get("changes")
    if isinstance(changes, list) and changes:
        first = changes[0]
        if isinstance(first, dict):
            path = (
                first.get("path")
                or first.get("file_path")
                or first.get("file")
                or first.get("filename")
            )
            if path:
                return str(path)

    return None


def normalize_event(raw_event: RawTranscriptEvent) -> tuple[list[TrajectoryStep], list[FailureRecord]]:
    """
    Convert one raw transcript event into zero or more normalized trajectory steps.

    This is the main Phase 1 normalization layer:
    - agent_message becomes plan / claim / revision / final_summary / agent_message
    - command_execution becomes a tool command step
    - file_change becomes an artifact-related step
    - web_search becomes a tool_call
    - todo_list becomes todo_update
    - unknown but non-empty records become raw_event for debugging
    """
    raw = raw_event.raw
    raw_type = raw.get("type")

    item = raw.get("item") or raw.get("data") or {}
    if not isinstance(item, dict):
        item = {}

    item_type = item.get("type") or raw.get("item_type")

    message = (
        raw.get("message")
        or raw.get("text")
        or item.get("text")
        or item.get("message")
        or item.get("content")
    )

    if should_skip_raw_event(raw_type, item_type, message):
        return [], []

    steps: list[TrajectoryStep] = []
    failures: list[FailureRecord] = []

    if item_type == "agent_message":
        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="agent",
                event_type=classify_agent_message(str(message or "")),
                raw_event_type=raw_type,
                status=_status_from_raw_type(raw_type),
                message=str(message) if message is not None else None,
                raw_json=raw,
            )
        )

    elif item_type == "command_execution":
        command = item.get("command") or item.get("cmd") or raw.get("command") or raw.get("cmd")
        output = (
            item.get("output")
            or item.get("stdout")
            or item.get("stderr")
            or raw.get("output")
            or raw.get("stdout")
            or raw.get("stderr")
        )
        exit_code = item.get("exit_code", raw.get("exit_code"))

        status = _status_from_raw_type(raw_type)
        if exit_code not in (None, 0):
            status = "failed"

        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="tool",
                event_type="command_execution",
                raw_event_type=raw_type,
                status=status,
                command=str(command) if command is not None else None,
                exit_code=exit_code,
                output_text=str(output) if output is not None else None,
                raw_json=raw,
            )
        )

        if exit_code not in (None, 0):
            failures.append(
                FailureRecord(
                    run_id=raw_event.run_id,
                    reason=f"Command failed with exit code {exit_code}: {command}",
                    error_type="command_failed",
                    recoverable=True,
                    context={
                        "source_file": raw_event.source_file,
                        "line_no": raw_event.line_no,
                        "command": command,
                    },
                )
            )

    elif item_type == "file_change":
        # File-change records are important for reconstructing artifacts such as
        # planning.md, REPORT.md, scripts, figures, and results. Codex logs may
        # store file paths under different keys, so use extract_file_path().
        file_path = extract_file_path(raw, item)

        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="agent",
                event_type="file_change",
                raw_event_type=raw_type,
                status=_status_from_raw_type(raw_type),
                file_path=file_path,
                message=str(message) if message is not None else None,
                raw_json=raw,
            )
        )

    elif item_type == "web_search":
        query = item.get("query") or raw.get("query") or message

        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="tool",
                event_type="tool_call",
                tool_name="web_search",
                raw_event_type=raw_type,
                status=_status_from_raw_type(raw_type),
                input_text=str(query) if query is not None else None,
                raw_json=raw,
            )
        )

    elif item_type == "todo_list":
        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="agent",
                event_type="todo_update",
                raw_event_type=raw_type,
                status=_status_from_raw_type(raw_type),
                message=str(message) if message is not None else None,
                raw_json=raw,
            )
        )

    else:
        steps.append(
            TrajectoryStep(
                run_id=raw_event.run_id,
                timestamp=raw_event.timestamp,
                source_file=raw_event.source_file,
                line_no=raw_event.line_no,
                actor="system",
                event_type="raw_event",
                raw_event_type=raw_type,
                status=_status_from_raw_type(raw_type),
                message=str(message) if message is not None else None,
                raw_json=raw,
            )
        )

    return steps, failures


# NOTE:
# This classifier is intentionally rule-based and conservative for Phase 1.
# The goal is not perfect semantic labeling yet; it is to create stable,
# readable trajectory categories for visualization. We avoid labeling every
# "completed" message as final_summary because many are only local progress
# updates, such as dependency installation or command completion.
def classify_agent_message(text: str) -> str:
    """
    Classify agent natural-language messages into coarse trajectory event types.

    Keep this conservative:
    - "final_summary" should only mean the run or major stage is actually ending.
    - Ordinary progress messages like "package installation completed" should stay
      as "agent_message", "claim", or "plan".
    """
    lowered = text.lower()

    final_markers = [
        "final report",
        "final summary",
        "task complete",
        "research complete",
        "experiment complete",
        "all deliverables",
        "completed the full",
        "the work is complete",
        "i have completed the",
        "successfully completed the research",
    ]

    if any(marker in lowered for marker in final_markers):
        return "final_summary"

    revision_markers = [
        "fix",
        "retry",
        "instead",
        "adjust",
        "modify",
        "change approach",
        "fallback",
        "recover",
    ]

    if any(marker in lowered for marker in revision_markers):
        return "revision"

    plan_markers = [
        "i will",
        "i’ll",
        "plan",
        "next",
        "now i will",
        "i'm going to",
        "i am going to",
    ]

    if any(marker in lowered for marker in plan_markers):
        return "plan"

    claim_markers = [
        "found",
        "result",
        "shows",
        "indicates",
        "suggests",
        "confirms",
        "the workspace is correct",
        "gpu",
        "available",
    ]

    if any(marker in lowered for marker in claim_markers):
        return "claim"

    return "agent_message"


def _status_from_raw_type(raw_type: Any) -> str | None:
    if not raw_type:
        return None

    raw_type = str(raw_type)

    if raw_type.endswith(".started"):
        return "started"

    if raw_type.endswith(".completed"):
        return "completed"

    if raw_type.endswith(".updated"):
        return "updated"

    return None