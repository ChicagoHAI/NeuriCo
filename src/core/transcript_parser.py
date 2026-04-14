"""
Transcript parser for provider streaming JSON logs.

Parses newline-delimited transcript files produced by Claude/Codex/Gemini runs
and normalizes events into a consistent structure.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class TranscriptEvent:
    """Normalized transcript event."""

    index: int
    line_number: int
    provider: str
    event_type: str
    role: Optional[str]
    tool_name: Optional[str]
    text: str
    raw: Dict[str, Any]


@dataclass
class ParsedTranscript:
    """Parsed transcript payload with summary metadata."""

    file_path: str
    provider: str
    total_lines: int
    parsed_json_lines: int
    invalid_json_lines: int
    events: List[TranscriptEvent]
    event_type_counts: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dictionary."""
        return {
            "file_path": self.file_path,
            "provider": self.provider,
            "total_lines": self.total_lines,
            "parsed_json_lines": self.parsed_json_lines,
            "invalid_json_lines": self.invalid_json_lines,
            "events": [asdict(event) for event in self.events],
            "event_type_counts": self.event_type_counts,
        }

    def extracted_text(self) -> str:
        """Concatenate non-empty text fields from normalized events."""
        parts = [event.text for event in self.events if event.text.strip()]
        return "\n".join(parts)


def infer_provider_from_path(path: Path) -> str:
    """Infer provider from transcript filename/path."""
    name = path.name.lower()
    if "claude" in name:
        return "claude"
    if "codex" in name:
        return "codex"
    if "gemini" in name:
        return "gemini"
    return "unknown"


def _extract_role(payload: Dict[str, Any]) -> Optional[str]:
    """Best-effort role extraction across common transcript shapes."""
    for key in ("role", "speaker", "author", "actor"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    message = payload.get("message")
    if isinstance(message, dict):
        value = message.get("role")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _extract_tool_name(payload: Dict[str, Any]) -> Optional[str]:
    """Best-effort tool name extraction."""
    for key in ("tool_name", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            # Avoid treating generic event name as tool when explicit type exists.
            if key == "name" and any(k in payload for k in ("type", "event", "kind")):
                continue
            return value.strip()

    if isinstance(payload.get("tool"), dict):
        maybe_name = payload["tool"].get("name")
        if isinstance(maybe_name, str) and maybe_name.strip():
            return maybe_name.strip()

    return None


def _extract_event_type(payload: Dict[str, Any]) -> str:
    """Best-effort event type extraction."""
    for key in ("type", "event", "kind", "op", "action", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _append_text(chunks: List[str], value: Any) -> None:
    """Recursively collect text from common nested transcript fields."""
    if value is None:
        return

    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            chunks.append(stripped)
        return

    if isinstance(value, list):
        for item in value:
            _append_text(chunks, item)
        return

    if not isinstance(value, dict):
        return

    # Common shapes in streaming responses from different CLIs.
    candidate_keys = (
        "text",
        "delta",
        "content",
        "message",
        "output",
        "response",
        "value",
        "arguments",
        "input",
    )
    for key in candidate_keys:
        if key in value:
            _append_text(chunks, value[key])

    # Content blocks like [{"type":"text","text":"..."}]
    if "items" in value:
        _append_text(chunks, value["items"])
    if "parts" in value:
        _append_text(chunks, value["parts"])


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    """Remove duplicates while preserving the first occurrence order."""
    seen = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def parse_transcript_file(path: Path) -> ParsedTranscript:
    """
    Parse a transcript file into normalized events.

    Args:
        path: Path to newline-delimited transcript (`*.jsonl`).

    Returns:
        ParsedTranscript with normalized events and summary counts.
    """
    transcript_path = Path(path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")

    provider = infer_provider_from_path(transcript_path)
    events: List[TranscriptEvent] = []
    event_type_counts: Dict[str, int] = {}

    total_lines = 0
    parsed_json_lines = 0
    invalid_json_lines = 0

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            total_lines += 1
            stripped = line.strip()
            if not stripped:
                continue

            payload: Dict[str, Any]
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                payload = {"type": "raw_text", "text": stripped}
            else:
                parsed_json_lines += 1
                if isinstance(obj, dict):
                    payload = obj
                else:
                    payload = {"type": "json_scalar", "value": obj}

            event_type = _extract_event_type(payload)
            role = _extract_role(payload)
            tool_name = _extract_tool_name(payload)

            text_chunks: List[str] = []
            _append_text(text_chunks, payload)
            text = "\n".join(_dedupe_preserve_order(text_chunks))

            event = TranscriptEvent(
                index=len(events),
                line_number=line_number,
                provider=provider,
                event_type=event_type,
                role=role,
                tool_name=tool_name,
                text=text,
                raw=payload,
            )
            events.append(event)
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1

    return ParsedTranscript(
        file_path=str(transcript_path),
        provider=provider,
        total_lines=total_lines,
        parsed_json_lines=parsed_json_lines,
        invalid_json_lines=invalid_json_lines,
        events=events,
        event_type_counts=dict(sorted(event_type_counts.items(), key=lambda kv: kv[0])),
    )
