"""Plain-language synthesis of the agent's current research reasoning for /status."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.hitl_paths import (
    hitl_idea_log_path,
    hitl_launch_status_path,
    hitl_research_state_path,
)

NO_REASONING = "No research reasoning recorded yet."
UNAVAILABLE = "Research summary unavailable."
_IDEA_FIELDS = (
    "idea_id", "timestamp", "pipeline_stage", "hitl_stage", "idea_type", "actor",
    "premises", "context", "evidence", "decision_needed", "decision", "manager_feedback",
)
_MAX_IDEAS = 8
_MAX_PREMISES = 6
_MAX_FIELD_CHARS = 700
_TIMEOUT_SECONDS = 90


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ideas(work_dir: Path) -> List[Dict[str, Any]]:
    try:
        lines = hitl_idea_log_path(work_dir).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    ideas = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            ideas.append(record)
    return ideas


def _compact(idea: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        key: value[:_MAX_FIELD_CHARS] if isinstance(value, str) else value
        for key in _IDEA_FIELDS
        if (value := idea.get(key)) not in (None, "", [])
    }
    options = {
        option.get("option_id"): option.get("text")
        for option in idea.get("options") or []
        if isinstance(option, dict)
    }
    if compact.get("decision") in options:
        compact["decision"] = options[compact["decision"]]
    return compact


def reasoning_context(work_dir: Path, status: Dict[str, Any]) -> str:
    """Recent current-stage ideas, their direct premises, and lagging manager notes."""
    ideas = _ideas(work_dir)
    stage = str(status.get("stage") or "") or str((ideas or [{}])[-1].get("pipeline_stage") or "")
    recent = [idea for idea in ideas if idea.get("pipeline_stage") == stage][-_MAX_IDEAS:]
    recent = recent or ideas[-_MAX_IDEAS:]
    by_id = {idea.get("idea_id"): idea for idea in ideas}
    seen = {idea.get("idea_id") for idea in recent}
    premises = []
    for idea in recent:
        for premise_id in idea.get("premises") or []:
            if premise_id not in seen and premise_id in by_id and len(premises) < _MAX_PREMISES:
                seen.add(premise_id)
                premises.append(by_id[premise_id])
    state = _read_json(hitl_research_state_path(work_dir))
    state = state if isinstance(state, dict) else {}
    notes = {
        "crux": state.get("crux"),
        "open_questions": state.get("open_questions"),
        "hypotheses": [
            {"statement": h.get("statement"), "status": h.get("status")}
            for h in state.get("hypotheses") or []
            if isinstance(h, dict)
        ],
    }
    notes = {key: value for key, value in notes.items() if value}
    if not recent and not notes:
        return ""
    payload: Dict[str, Any] = {
        "current_position": {"pipeline_stage": stage, "phase": status.get("phase") or ""},
        "premises_of_recent_ideas": [_compact(idea) for idea in premises],
        "recent_ideas_oldest_first": [_compact(idea) for idea in recent],
    }
    if notes:
        payload["manager_notes_may_lag_behind_ideas"] = {
            "updated_at": state.get("updated_at"),
            **notes,
        }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _used_tools(response: Any) -> bool:
    if getattr(response, "tool_calls", None):
        return True
    for event in getattr(response, "raw", None) or []:
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict) and item.get("type") not in ("agent_message", "reasoning", "error"):
            return True
    return False


class HitlStatusSummary:
    """Synthesize once per run, provider and reasoning context; never cache failures."""

    def __init__(self, work_dir: Path, backend_for: Callable[[str], Any], default_provider: Callable[[], str]):
        self.work_dir = Path(work_dir)
        self._backend_for = backend_for
        self._default_provider = default_provider
        self._key = ""
        self._text = ""

    def summarize(self, status: Dict[str, Any]) -> str:
        context = reasoning_context(self.work_dir, status)
        if not context:
            return NO_REASONING
        provider = str(status.get("provider") or self._default_provider())
        launch = _read_json(hitl_launch_status_path(self.work_dir))
        run_id = str(launch.get("request_id") or "") if isinstance(launch, dict) else ""
        key = hashlib.sha256("\0".join((run_id, provider, context)).encode()).hexdigest()
        if key == self._key:
            return self._text
        from core.hitl import render_hitl_template

        try:
            response = self._backend_for(provider).send(
                [
                    {"role": "system", "content": render_hitl_template("status_reasoning_summary.txt")},
                    {
                        "role": "user",
                        "content": "--- BEGIN UNTRUSTED RESEARCH DATA ---\n"
                        + context
                        + "\n--- END UNTRUSTED RESEARCH DATA ---",
                    },
                ],
                [],
                timeout_seconds=_TIMEOUT_SECONDS,
                no_tools=True,
            )
        except Exception:
            return UNAVAILABLE
        text = " ".join(str(getattr(response, "text", "") or "").split())
        if not text or _used_tools(response):
            return UNAVAILABLE
        self._key, self._text = key, text
        return text
