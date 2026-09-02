"""
Plan-centered human-in-the-loop runtime.

HITL v1 keeps the stage worker responsible for stage work and its living plan.
Managers and humans resolve raised ideas; the stage worker receives feedback,
updates the plan, and resumes from the current workspace state.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import stat
import hashlib
import http.server
import sys
import threading
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from core.hitl_lock import exclusive_file_lock
from core.hitl_mode import HitlMode, normalize_hitl_mode
from core.hitl_paths import (
    hitl_artifact_contract_path,
    hitl_idea_log_path,
    hitl_state_dir,
)
from core.hitl_util import (
    atomic_write_json,
    atomic_write_text,
    read_jsonl_objects,
    sha256_file as _sha256_file,
    utc_now,
)

LOGGER = logging.getLogger(__name__)


PIPELINE_STAGES = {
    "resource_finder",
    "rule_maker",
    "experiment_runner",
    "scorer",
    "paper_writer",
}
HITL_WORKER_ACTORS = PIPELINE_STAGES | {"autoresearch_proposer", "comment_handler"}
HITL_STAGES = {"plan", "execution", "proposal", "review"}
LEVELS = {"A", "B", "C"}
IDEA_TYPES = {"decision", "evidence", "proposal"}

_WORKER_COMMAND_MODULES = {
    "hitl-report-idea": "hitl_report_idea.py",
    "hitl-raise-idea": "hitl_raise_idea.py",
    "hitl-view-ideas": "hitl_view_ideas.py",
    "hitl-finish-phase": "hitl_finish_phase.py",
    "hitl-resume-worker-request": "hitl_resume_worker_request.py",
    "hitl-submit-proposal": "hitl_submit_proposal.py",
    "view_current_frontier": "hitl_view_current_frontier.py",
}
PROPOSAL_KINDS = {"exploitation", "exploration"}
EVIDENCE_IDEA_CATEGORIES = {
    "paper_finding",
    "dataset_property",
    "implementation_fact",
    "experiment_result",
    "constraint_or_risk",
    "other",
}
DECISION_IDEA_CATEGORIES = {
    "dataset_choice",
    "search_strategy",
    "method_choice",
    "evaluation_choice",
    "compute_resource_choice",
    "artifact_boundary_choice",
    "other",
}
IDEA_CATEGORIES_BY_TYPE = {
    "evidence": EVIDENCE_IDEA_CATEGORIES,
    "decision": DECISION_IDEA_CATEGORIES,
}
ROUTING_OPTION_MARKERS = (
    "ask human",
    "ask manager",
    "escalate to human",
    "escalate to manager",
    "manager review",
    "human review",
)
IDEA_RECORD_FIELD_ORDER = [
    "idea_id",
    "timestamp",
    "pipeline_stage",
    "hitl_stage",
    "idea_type",
    "level",
    "actor",
    "parent_node_id",
    "attempt_id",
    "premises",
    "worker_context",
    "context",
    "related_artifacts",
    "idea_category",
    "proposal_type",
    "proposal",
    "decision_needed",
    "evidence",
    "options",
    "decision",
    "human_feedback",
    "manager_feedback",
    "raised",
    "worker_escalation_reason",
    "manager_escalation_reason",
]
RUNTIME_PROVENANCE_FIELDS = ("parent_node_id", "attempt_id")


def _now() -> str:
    return utc_now(timespec="seconds")


def _compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _ordered_idea_record(record: Dict[str, Any]) -> Dict[str, Any]:
    ordered: Dict[str, Any] = {}
    for key in IDEA_RECORD_FIELD_ORDER:
        if key in record:
            ordered[key] = record[key]
    for key, value in record.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _apply_runtime_provenance(
    record: Dict[str, Any],
    provenance: Optional[Dict[str, Any]],
) -> None:
    for key in RUNTIME_PROVENANCE_FIELDS:
        value = (provenance or {}).get(key)
        if value is not None and str(value).strip():
            record[key] = str(value)


def _runtime_provenance(provenance: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Return only schema-approved runtime provenance fields."""
    return {
        key: str(value)
        for key in RUNTIME_PROVENANCE_FIELDS
        if (value := (provenance or {}).get(key)) is not None and str(value).strip()
    }


def _with_runtime_premises(
    premises: List[str],
    provenance: Optional[Dict[str, Any]],
) -> List[str]:
    """Add runtime-known causal dependencies without exposing extra log fields."""
    proposal_idea_id = str((provenance or {}).get("proposal_idea_id", "")).strip()
    return _normalize_premises([*premises, *([proposal_idea_id] if proposal_idea_id else [])])


def _as_related_artifacts(value: Any) -> List[Dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HitlValidationError(
            "related_artifacts must be a list of workspace-relative artifact objects"
        )
    artifacts: List[Dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise HitlValidationError(
                f"related_artifacts[{index}] must be an object with path and description"
            )
        path = str(item.get("path", "")).strip()
        description = str(item.get("description", "")).strip()
        if not path:
            raise HitlValidationError(
                f"related_artifacts[{index}].path must be a non-empty workspace-relative path"
            )
        if not description:
            raise HitlValidationError(f"related_artifacts[{index}].description must be non-empty")
        _validate_related_artifact_path(path)
        artifacts.append({"path": path, "description": description})
    return artifacts


def _validate_related_artifact_path(path: str) -> None:
    """Validate NeuriCo's HITL artifact path convention."""
    raw = str(path).strip()
    if not raw:
        raise HitlValidationError("related_artifacts[].path must be non-empty")
    if raw.startswith("/") or "\\" in raw:
        raise HitlValidationError(
            "related_artifacts[].path must be a relative POSIX path under the workspace root"
        )
    parsed = PurePosixPath(raw)
    if str(parsed) in {".", ""} or any(part in {"", ".", ".."} for part in parsed.parts):
        raise HitlValidationError(
            "related_artifacts[].path must not be empty, '.', or contain '..'"
        )


def _validate_substantive_options(
    value: Any,
    *,
    error_prefix: str,
    allow_empty: bool = False,
) -> List[Dict[str, str]]:
    if value is None:
        if allow_empty:
            return []
        raise HitlValidationError(f"{error_prefix} requires options")
    if not isinstance(value, list):
        raise HitlValidationError(f"{error_prefix} options must be a list")
    options = _normalize_options(value)
    if not options:
        if allow_empty:
            return []
        raise HitlValidationError(f"{error_prefix} requires options")
    for option in options:
        lowered = option["text"].lower()
        if any(marker in lowered for marker in ROUTING_OPTION_MARKERS):
            raise HitlValidationError(
                f"{error_prefix} options must be substantive workflow choices"
            )
    return options


def _normalize_premises(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise HitlValidationError(
            "HITL_ERROR invalid_premises\n"
            "`premises` must be a list of existing idea ids.\n"
            "Retry with repeated `--premise I<N>` values, or omit premises if no prior idea is relevant."
        )
    premises: List[str] = []
    seen = set()
    for item in value:
        premise = str(item).strip()
        if not premise:
            continue
        if not premise.startswith("I") or not premise[1:].isdigit():
            raise HitlValidationError(
                "HITL_ERROR invalid_premise_id\n"
                f"Invalid premise id: {premise}\n"
                "Retry using finalized idea ids shown by `hitl-view-ideas`, such as `--premise I3`."
            )
        if premise in seen:
            raise HitlValidationError(
                "HITL_ERROR duplicate_premise\n"
                f"Duplicate premise id: {premise}\n"
                "Retry with each premise id at most once."
            )
        seen.add(premise)
        premises.append(premise)
    return premises


def _validate_premises(premises: List[str], existing_ids: Optional[set[str]]) -> None:
    if existing_ids is None:
        return
    missing = [premise for premise in premises if premise not in existing_ids]
    if missing:
        raise HitlValidationError(
            "HITL_ERROR unknown_premise\n"
            f"Unknown premise idea id(s): {', '.join(missing)}\n"
            "Run `hitl-view-ideas`, then retry using only finalized idea ids that appear there."
        )


def _validate_idea_category(idea_type: str, idea_category: Any) -> str:
    category = str(idea_category or "").strip()
    allowed = IDEA_CATEGORIES_BY_TYPE.get(idea_type, set())
    if not category:
        raise HitlValidationError(
            "HITL_ERROR missing_category\n"
            f"{idea_type} ideas require `idea_category`.\n"
            f"Retry with one category: {', '.join(sorted(allowed))}."
        )
    if category not in allowed:
        raise HitlValidationError(
            "HITL_ERROR invalid_category\n"
            f"Invalid {idea_type} idea category: {category}\n"
            f"Retry with one category: {', '.join(sorted(allowed))}."
        )
    return category


def _normalize_options(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    options: List[Dict[str, str]] = []
    for idx, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = str(item.get("text", item.get("label", item.get("value", "")))).strip()
            if not text:
                label = str(item.get("option", "")).strip()
                description = str(item.get("description", "")).strip()
                text = f"{label}: {description}".strip(": ")
        else:
            text = str(item).strip()
        if text:
            options.append({"option_id": f"O{idx}", "text": text})
    return options


def _option_texts(options: List[Dict[str, str]]) -> List[str]:
    return [option["text"] for option in options]


def _resolve_option_decision(response: str, options: List[Dict[str, str]]) -> Dict[str, str]:
    raw = response.strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            option = options[idx]
            return {"decision": option["option_id"], "feedback": option["text"]}
    normalized_raw = raw.lower().strip().rstrip(".")
    for option in options:
        normalized_text = option["text"].lower().strip().rstrip(".")
        option_aliases = {normalized_text}
        if normalized_text.endswith(" plan"):
            option_aliases.add(normalized_text.removesuffix(" plan").strip())
        if raw == option["option_id"] or raw == option["text"] or normalized_raw in option_aliases:
            return {"decision": option["option_id"], "feedback": option["text"]}
    return {"decision": "CUSTOM", "feedback": raw}


def _is_feedback_placeholder(response: str) -> bool:
    normalized = response.strip().lower().rstrip(".")
    return normalized in {"", "provide feedback", "feedback"}


def _require_text(value: Any, field_name: str, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HitlValidationError(f"{context} must include non-empty `{field_name}`.")
    return text


def _hitl_template_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "templates" / "hitl"


def _load_hitl_template(name: str, **kwargs: Any) -> str:
    from templates.prompt_generator import PromptGenerator

    templates_dir = _hitl_template_dir().parent
    generator = PromptGenerator(templates_dir)
    template = generator.load_template(f"hitl/{name}")
    return generator.render_template(template, kwargs)


def render_hitl_template(name: str, **kwargs: Any) -> str:
    """Render a HITL prompt template from templates/hitl."""
    return _load_hitl_template(name, **kwargs)


def _resolve_manager_option(response: str, options: List[Dict[str, str]]) -> Dict[str, str]:
    resolved = _resolve_option_decision(response, options)
    if resolved["decision"] == "CUSTOM":
        raise HitlValidationError("Manager-resolved decision must match a substantive option")
    return resolved


def _resolve_human_decision(response: str, options: List[Dict[str, str]]) -> Dict[str, str]:
    resolved = _resolve_option_decision(response, options)
    return {
        "decision": resolved["decision"],
        "human_feedback": resolved["feedback"],
    }


def _decision_record_requires_options(record: Dict[str, Any]) -> bool:
    return bool(record.get("raised"))


def _decision_record_uses_option_id(record: Dict[str, Any]) -> bool:
    if "options" not in record or record.get("options") is None:
        return False
    return record.get("level") in {"A", "B"}


class HitlValidationError(ValueError):
    """Raised when a HITL idea is malformed."""


class HitlActiveWorkerRequestError(RuntimeError):
    """Raised when another worker command arrives while one is unresolved."""

    def __init__(self, request: Optional[Dict[str, Any]] = None):
        request = request or {}
        lines = [
            "HITL_WORKER_REQUEST_ACTIVE",
            "",
            "Another blocking worker request is still unresolved.",
        ]
        for key in ("kind", "pipeline_stage", "hitl_stage"):
            value = str(request.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")
        lines.extend(
            [
                "",
                "Keep the current workspace state unchanged.",
                "Wait for runtime feedback, then continue in this same worker session.",
            ]
        )
        super().__init__("\n".join(lines))


class HitlIdeaLog:
    """Append-only finalized HITL idea log stored under .neurico/hitl/idea/."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.hitl_dir = hitl_state_dir(self.work_dir)
        self.hitl_dir.mkdir(parents=True, exist_ok=True)
        self.path = hitl_idea_log_path(self.work_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, idea: Dict[str, Any], *, idempotent: bool = False) -> Dict[str, Any]:
        """Finalize one idea, optionally treating an identical retry as a no-op.

        Runtime finalizers use ``idempotent=True`` because an interrupted process
        can leave a worker request active after its audit record was already written.
        Worker C-level reporting keeps its existing command-level semantics.
        """
        with self._locked_log():
            existing_records = self.records()
            known_ids = {
                str(record.get("idea_id", "")).strip()
                for record in existing_records
                if str(record.get("idea_id", "")).strip()
            }
            record = dict(idea)
            if idempotent:
                expected = self.logical_payload(record)
                for existing_record in reversed(existing_records):
                    if self.logical_payload(existing_record) == expected:
                        return existing_record
            if not str(record.get("idea_id", "")).strip():
                record["idea_id"] = f"I{self._next_number(existing_records)}"
            elif str(record["idea_id"]).strip() in known_ids:
                raise HitlValidationError(
                    f"HITL idea_id already exists: {str(record['idea_id']).strip()}"
                )
            record.setdefault("timestamp", _now())
            record.setdefault("premises", [])
            record["premises"] = _normalize_premises(record["premises"])
            if record.get("idea_type") == "decision" and "options" in record:
                record["options"] = _normalize_options(record["options"])
                if record.get("level") == "C":
                    selected = _resolve_option_decision(
                        str(record.get("decision", "")),
                        record["options"],
                    )
                    if selected["decision"] == "CUSTOM":
                        raise HitlValidationError(
                            "C-level decision idea must select one of its declared options. "
                            "Add the selected action as an option, then retry."
                        )
                    record["decision"] = selected["decision"]
            self.validate(record, existing_ids=known_ids)
            ordered = _ordered_idea_record(record)
            existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            addition = _compact_json(ordered) + "\n"
            atomic_write_text(self.path, existing + addition)
        # The idea log is authoritative. Reconciliation is derived state, so a
        # projection failure must not turn a successfully finalized idea into a
        # failed worker command that an agent will retry and duplicate. A later
        # manager turn can rebuild the projection from this durable log.
        from core.hitl_world_model import HitlWorldModelSync

        try:
            HitlWorldModelSync(self.work_dir).reconcile()
        except Exception:
            LOGGER.warning(
                "HITL world-model projection failed after idea %s was finalized; "
                "the next manager reconciliation will retry it.",
                ordered["idea_id"],
                exc_info=True,
            )
        try:
            from core.hitl_runtime_state import HitlRuntimeState

            HitlRuntimeState(self.work_dir).record_interface_idea(ordered["idea_id"])
        except Exception:
            LOGGER.warning(
                "HITL interface notification failed after idea %s was finalized; "
                "the authoritative idea record remains available.",
                ordered["idea_id"],
                exc_info=True,
            )
        return ordered

    def append_many(self, ideas: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records = list(ideas)
        if len(records) != 1:
            raise HitlValidationError(
                "HITL ideas must be finalized one at a time so every premise refers "
                "to an earlier finalized record."
            )
        return [self.append(records[0])]

    @staticmethod
    def logical_payload(record: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize one command submission while ignoring runtime-assigned identity."""
        payload = {
            key: value for key, value in dict(record).items() if key not in {"idea_id", "timestamp"}
        }
        payload.setdefault("premises", [])
        payload["premises"] = _normalize_premises(payload["premises"])
        if payload.get("idea_type") == "decision" and "options" in payload:
            payload["options"] = _normalize_options(payload["options"])
        return payload

    def find_equivalent(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return an identical already-finalized submission for a safe retry."""
        expected = self.logical_payload(record)
        for existing in reversed(self.records()):
            if self.logical_payload(existing) == expected:
                return existing
        return None

    @contextmanager
    def _locked_log(self) -> Iterator[None]:
        lock_path = self.path.with_suffix(".jsonl.lock")
        with exclusive_file_lock(lock_path):
            yield

    @staticmethod
    def _next_number(records: Iterable[Dict[str, Any]]) -> int:
        numbers = []
        for record in records:
            idea_id = str(record.get("idea_id", "")).strip()
            if idea_id.startswith("I") and idea_id[1:].isdigit():
                numbers.append(int(idea_id[1:]))
        return max(numbers, default=0) + 1

    def records(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return read_jsonl(self.path)

    def render_for_agent(self, *, idea_id: Optional[str] = None) -> str:
        all_records = self.records()
        if not all_records:
            return "No finalized HITL ideas have been recorded yet."
        records = all_records
        if idea_id:
            records = [record for record in all_records if record.get("idea_id") == idea_id]
            if not records:
                raise HitlValidationError(f"No finalized HITL idea exists with id {idea_id}.")
        record_ids = [
            str(record.get("idea_id", "")).strip()
            for record in all_records
            if str(record.get("idea_id", "")).strip()
        ]
        used_by: Dict[str, List[str]] = {idea_id: [] for idea_id in record_ids}
        for record in all_records:
            record_id = str(record.get("idea_id", "")).strip()
            for premise in _normalize_premises(record.get("premises")):
                used_by.setdefault(premise, []).append(record_id)

        if idea_id:
            blocks = [f"Finalized HITL idea: {idea_id}"]
        else:
            roots = [
                record_id
                for record_id, record in zip(record_ids, all_records)
                if not _normalize_premises(record.get("premises"))
            ]
            leaves = [record_id for record_id in record_ids if not used_by.get(record_id)]
            evidence_count = sum(
                1 for record in all_records if record.get("idea_type") == "evidence"
            )
            decision_count = sum(
                1 for record in all_records if record.get("idea_type") == "decision"
            )
            proposal_count = sum(
                1 for record in all_records if record.get("idea_type") == "proposal"
            )
            blocks = [
                f"Finalized HITL ideas: {len(all_records)}",
                f"Evidence: {evidence_count}",
                f"Decision: {decision_count}",
                f"Proposal: {proposal_count}",
                f"Roots: {', '.join(roots) if roots else 'none'}",
                f"Leaves: {', '.join(leaves) if leaves else 'none'}",
                "",
                "Chronological ideas:",
            ]
        for record in records:
            record_id = str(record.get("idea_id", "")).strip()
            idea_type = str(record.get("idea_type", "")).strip()
            category = str(record.get("idea_category", "")).strip()
            level = str(record.get("level", "")).strip()
            actor = str(record.get("actor", "")).strip()
            stage = f"{record.get('pipeline_stage', '')}/{record.get('hitl_stage', '')}"
            blocks.append("")
            blocks.append(
                f"{record_id} [{idea_type}/{category}] level={level} actor={actor} stage={stage}"
            )
            for key in (
                "context",
                "proposal_type",
                "proposal",
                "evidence",
                "decision_needed",
                "decision",
                "manager_feedback",
                "worker_context",
                "worker_escalation_reason",
            ):
                value = record.get(key)
                if value is not None and str(value).strip():
                    blocks.append(f"{key}: {value}")
            options = record.get("options")
            if isinstance(options, list) and options:
                blocks.append("options:")
                for option in _normalize_options(options):
                    blocks.append(f"  {option['option_id']}: {option['text']}")
            premises = _normalize_premises(record.get("premises"))
            blocks.append(f"premises: {', '.join(premises) if premises else 'none'}")
            children = used_by.get(record_id, [])
            blocks.append(f"used_by: {', '.join(children) if children else 'none'}")
            artifacts = record.get("related_artifacts")
            if isinstance(artifacts, list) and artifacts:
                blocks.append("related_artifacts:")
                for artifact in _as_related_artifacts(artifacts):
                    description = artifact.get("description", "")
                    blocks.append(f"  {artifact['path']}: {description}")
        return "\n".join(blocks)

    @staticmethod
    def validate(
        record: Dict[str, Any],
        *,
        existing_ids: Optional[set[str]] = None,
    ) -> None:
        required = [
            "idea_id",
            "timestamp",
            "pipeline_stage",
            "hitl_stage",
            "level",
            "actor",
            "idea_type",
            "context",
            "raised",
        ]
        missing = [k for k in required if k not in record]
        if missing:
            raise HitlValidationError(f"Missing HITL idea field(s): {missing}")
        if record["pipeline_stage"] not in PIPELINE_STAGES:
            raise HitlValidationError(f"Invalid pipeline_stage: {record['pipeline_stage']}")
        if record["hitl_stage"] not in HITL_STAGES:
            raise HitlValidationError(f"Invalid hitl_stage: {record['hitl_stage']}")
        if record["level"] not in LEVELS:
            raise HitlValidationError(f"Invalid level: {record['level']}")
        if record["idea_type"] not in IDEA_TYPES:
            raise HitlValidationError(f"Invalid idea_type: {record['idea_type']}")
        idea_id = str(record["idea_id"]).strip()
        if not idea_id.startswith("I") or not idea_id[1:].isdigit():
            raise HitlValidationError("HITL idea_id must use the runtime format I<N>")
        if existing_ids is not None and idea_id in existing_ids:
            raise HitlValidationError(f"HITL idea_id already exists: {idea_id}")
        premises = _normalize_premises(record.get("premises"))
        _validate_premises(premises, existing_ids)
        if not str(record["context"]).strip():
            raise HitlValidationError("HITL idea context must be non-empty")
        actor = str(record["actor"]).strip()
        if record["level"] == "A" and actor != "human":
            raise HitlValidationError("A-level HITL ideas must be finalized by actor 'human'")
        if record["level"] == "B" and actor != "manager":
            raise HitlValidationError("B-level HITL ideas must be finalized by actor 'manager'")
        if record["level"] == "C" and actor not in HITL_WORKER_ACTORS:
            raise HitlValidationError(
                "C-level HITL ideas must be finalized by a recognized HITL worker actor"
            )
        for field in ("basis", "human_basis"):
            if field in record:
                raise HitlValidationError(
                    f"HITL idea records no longer support `{field}`; use finalized premises instead."
                )
        if "related_artifacts" in record:
            _as_related_artifacts(record["related_artifacts"])

        if record["idea_type"] == "decision":
            _validate_idea_category(record["idea_type"], record.get("idea_category"))
            if "evidence" in record:
                raise HitlValidationError("Decision idea must not include evidence")
            if "proposal" in record:
                raise HitlValidationError("Decision idea must not include proposal fields")
            if not premises:
                raise HitlValidationError("Decision idea requires at least one finalized premise")
            if "decision_needed" not in record or not str(record["decision_needed"]).strip():
                raise HitlValidationError("Decision idea requires non-empty decision_needed")
            _validate_substantive_options(
                record.get("options"),
                error_prefix="Decision idea",
            )
            if "decision" not in record or not str(record["decision"]).strip():
                raise HitlValidationError("Decision idea requires non-empty decision")
            if _decision_record_requires_options(record):
                _validate_substantive_options(
                    record.get("options"),
                    error_prefix="Raised decision idea",
                )
            elif "options" in record and record.get("options") is not None:
                _validate_substantive_options(
                    record.get("options"),
                    error_prefix="C-level decision idea",
                    allow_empty=True,
                )
            if _decision_record_uses_option_id(record) and record["decision"] != "CUSTOM":
                option_ids = {
                    option["option_id"] for option in _normalize_options(record["options"])
                }
                if record["decision"] not in option_ids:
                    raise HitlValidationError(
                        "A/B option-based decision must be an option id or CUSTOM"
                    )
        elif record["idea_type"] == "evidence":
            _validate_idea_category(record["idea_type"], record.get("idea_category"))
            if "proposal" in record:
                raise HitlValidationError("Evidence idea must not include proposal fields")
            forbidden = [
                field
                for field in ("decision_needed", "options", "decision")
                if field in record and record.get(field) not in (None, "", [])
            ]
            if forbidden:
                raise HitlValidationError(
                    f"Evidence idea must not include decision field(s): {forbidden}"
                )
            if "evidence" not in record or not str(record["evidence"]).strip():
                raise HitlValidationError("Evidence idea requires non-empty evidence")
        else:
            forbidden = [
                field
                for field in ("idea_category", "decision_needed", "options", "decision", "evidence")
                if field in record and record.get(field) not in (None, "", [])
            ]
            if forbidden:
                raise HitlValidationError(
                    f"Proposal idea must not include decision/evidence field(s): {forbidden}"
                )
            proposal_type = str(record.get("proposal_type", "")).strip()
            if proposal_type not in PROPOSAL_KINDS:
                raise HitlValidationError(
                    "Proposal idea requires proposal_type 'exploitation' or 'exploration'"
                )
            if not premises:
                raise HitlValidationError("Proposal idea requires at least one finalized premise")
            if not str(record.get("proposal", "")).strip():
                raise HitlValidationError("Proposal idea requires non-empty proposal content")


@dataclass
class HitlPaths:
    work_dir: Path
    pipeline_stage: str

    @property
    def plan_path(self) -> Path:
        return self.work_dir / "plans" / f"{self.pipeline_stage}_plan.md"

    @property
    def hitl_dir(self) -> Path:
        return hitl_state_dir(self.work_dir)

    @property
    def manager_dir(self) -> Path:
        return self.hitl_dir / "manager"

    @property
    def manager_conversation_db_path(self) -> Path:
        return self.manager_dir / "history.sqlite"

    @property
    def tool_bin_dir(self) -> Path:
        return self.hitl_dir / "bin"

    @property
    def report_idea_command(self) -> Path:
        return self.tool_bin_dir / "hitl-report-idea"

    @property
    def raise_idea_command(self) -> Path:
        return self.tool_bin_dir / "hitl-raise-idea"

    @property
    def finish_phase_command(self) -> Path:
        return self.tool_bin_dir / "hitl-finish-phase"

    @property
    def resume_worker_request_command(self) -> Path:
        return self.tool_bin_dir / "hitl-resume-worker-request"

    @property
    def view_ideas_command(self) -> Path:
        return self.tool_bin_dir / "hitl-view-ideas"

    @property
    def submit_proposal_command(self) -> Path:
        return self.tool_bin_dir / "hitl-submit-proposal"

    @property
    def view_current_frontier_command(self) -> Path:
        return self.tool_bin_dir / "view_current_frontier"


class HitlRuntime:
    """Small orchestration helper for one plan-centered HITL stage."""

    def __init__(
        self,
        work_dir: Path,
        pipeline_stage: str,
        *,
        channel: Optional[Any] = None,
        manager: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        use_hitl_autoresearch_whiteboard: bool = False,
        hitl_mode: HitlMode | str = HitlMode.FULL,
    ):
        if pipeline_stage not in PIPELINE_STAGES:
            raise ValueError(f"Unsupported HITL pipeline stage: {pipeline_stage}")
        self.work_dir = Path(work_dir)
        self.pipeline_stage = pipeline_stage
        self.use_hitl_autoresearch_whiteboard = use_hitl_autoresearch_whiteboard
        self.hitl_mode = normalize_hitl_mode(hitl_mode)
        self.paths = HitlPaths(self.work_dir, pipeline_stage)
        self.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.hitl_dir.mkdir(parents=True, exist_ok=True)
        self.log = HitlIdeaLog(self.work_dir)
        self.channel = channel or self._default_channel()
        self.manager = manager or self._default_manager(
            config or {},
            work_dir=self.work_dir,
            channel=self.channel,
        )
        self.current_hitl_stage = "execution"
        self._tool_server: Optional[http.server.ThreadingHTTPServer] = None
        self._tool_thread: Optional[threading.Thread] = None
        self._tool_url: str = ""
        self._tool_token: str = ""
        self._tool_context: Dict[str, Any] = {}
        # Optional callback that returns a sanitized scoring-conformance report
        # for the manager's rule-maker review. Set per stage by the orchestrator;
        # None for stages that have no evaluator to report on.
        self._scoring_conformance_reporter: Optional[Callable[[], str]] = None
        self._phase_finish_result: Optional[Dict[str, Any]] = None
        self._phase_finish_request_key: str = ""
        self._phase_finish_response: Optional[Dict[str, Any]] = None
        self._proposal_submit_result: Optional[Dict[str, Any]] = None
        self._raised_idea_results: Dict[str, Dict[str, Any]] = {}
        self._started_scoring_requests: set[str] = set()
        self._tool_lock = threading.RLock()
        # This only serializes concurrent HTTP command handlers inside this
        # runtime process. Cross-process ownership lives in HitlRuntimeState.
        self._worker_request_lock = threading.Lock()

    @staticmethod
    def _default_channel() -> Any:
        from interactive.channel import TerminalChannel

        return TerminalChannel()

    @staticmethod
    def _default_manager(
        config: Dict[str, Any],
        work_dir: Optional[Path] = None,
        channel: Optional[Any] = None,
    ) -> Any:
        from core.hitl_manager_react import HitlManager

        return HitlManager(config, work_dir=work_dir, channel=channel)

    def plan_prompt_block(
        self,
        approved_proposal: str = "",
        *,
        requires_human_approval: Optional[bool] = None,
    ) -> str:
        if requires_human_approval is None:
            requires_human_approval = self.requires_human_plan_approval
        elif requires_human_approval and not self.requires_human_plan_approval:
            requires_human_approval = False
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_plan.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            approved_proposal=approved_proposal,
            requires_human_approval=requires_human_approval,
            hitl_stage="plan",
            allow_raised_ideas=False,
            hitl_mode=self.hitl_mode.value,
        )

    def execution_prompt_block(self, mode: str = "execute", feedback: str = "") -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_execution.txt",
            pipeline_stage=self.pipeline_stage,
            mode=mode,
            plan_path=rel_plan,
            hitl_stage="execution",
            allow_raised_ideas=True,
            feedback=feedback,
            hitl_mode=self.hitl_mode.value,
        )

    def review_prompt_block(self, feedback: str = "") -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_review_revision.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            hitl_stage="review",
            allow_raised_ideas=True,
            feedback=feedback,
            hitl_mode=self.hitl_mode.value,
        )

    def plan_revision_prompt_block(self, feedback: str) -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_plan_revision.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            hitl_stage="plan",
            allow_raised_ideas=False,
            feedback=feedback,
            hitl_mode=self.hitl_mode.value,
        )

    def compose_worker_prompt(self, *, hitl_stage: str, phase_prompt: str) -> str:
        """Join a stage-specific source context with one HITL phase contract.

        Ordinary-stage workers register all three source contexts when they
        enter HITL. Runtime then returns the same complete prompt to the live
        worker and to any runtime-owned replacement worker. Other HITL callers
        that do not have an external stage-worker source prompt keep their
        dedicated prompt contract unchanged.
        """
        contexts = self._tool_context.get("worker_prompt_contexts")
        if not contexts:
            return phase_prompt
        source_context = str(contexts.get(hitl_stage, "")).strip()
        if not source_context:
            raise HitlValidationError(
                f"HITL worker prompt context is missing for phase {hitl_stage!r}."
            )
        return f"{source_context}\n\n{phase_prompt.strip()}\n"

    def proposal_replacement_prompt_block(self, feedback: str) -> str:
        return _load_hitl_template(
            "worker_proposal_replacement.txt",
            feedback=_require_text(feedback, "feedback", "Proposal continuation"),
        )

    def idea_reporting_prompt_block(self, hitl_stage: str) -> str:
        if hitl_stage not in HITL_STAGES:
            raise ValueError(f"Unsupported HITL stage for C-level idea reporting: {hitl_stage}")
        return _load_hitl_template(
            "worker_autonomous_idea_contract.txt",
            pipeline_stage=self.pipeline_stage,
            hitl_stage=hitl_stage,
            allow_raised_ideas=hitl_stage in {"execution", "review"},
            hitl_mode=self.hitl_mode.value,
        )

    @property
    def requires_human_plan_approval(self) -> bool:
        return self.hitl_mode is HitlMode.FULL

    def plan_has_required_approval(self) -> bool:
        if not self.paths.plan_path.exists():
            return False
        from core.hitl_runtime_state import HitlRuntimeState

        levels = ("A",) if self.requires_human_plan_approval else ("A", "B")
        return HitlRuntimeState(self.work_dir).has_plan_approval(
            pipeline_stage=self.pipeline_stage,
            plan_fingerprint=self._current_plan_fingerprint(),
            approval_levels=levels,
        )

    def plan_has_human_approval(self) -> bool:
        if not self.paths.plan_path.exists():
            return False
        from core.hitl_runtime_state import HitlRuntimeState

        return HitlRuntimeState(self.work_dir).has_plan_approval(
            pipeline_stage=self.pipeline_stage,
            plan_fingerprint=self._current_plan_fingerprint(),
        )

    def resolve_raised_payload(
        self,
        payload: Dict[str, Any],
        *,
        provenance: Optional[Dict[str, Any]] = None,
        already_validated: bool = False,
    ) -> Dict[str, Any]:
        raised_idea = dict(payload)
        raised_idea["pipeline_stage"] = self.pipeline_stage
        raised_idea["hitl_stage"] = str(raised_idea.get("hitl_stage") or self.current_hitl_stage)
        if not already_validated:
            self.validate_raised_idea(
                raised_idea,
                existing_ids={
                    str(record.get("idea_id", "")).strip()
                    for record in self.log.records()
                    if str(record.get("idea_id", "")).strip()
                },
            )
        finalized: Dict[str, Dict[str, Any]] = {}

        def persist_resolution(review: Dict[str, Any]) -> Dict[str, Any]:
            decision_options = self._raised_idea_decision_options(raised_idea, review)
            level = str(review.get("level", "")).strip()
            actor = str(review.get("actor", "")).strip()
            if (level, actor) not in {("B", "manager"), ("A", "human")}:
                raise HitlValidationError(
                    "Manager raised-idea resolution must finalize as B/manager or A/human."
                )
            feedback = _require_text(
                review.get("manager_feedback"),
                "manager_feedback",
                "Manager raised-idea resolution",
            )
            if raised_idea["idea_type"] == "decision":
                raw_decision = _require_text(
                    review.get("decision"),
                    "decision",
                    "Finalized raised decision idea",
                )
                decision = (
                    _resolve_option_decision(raw_decision, decision_options)["decision"]
                    if actor == "human"
                    else _resolve_manager_option(raw_decision, decision_options)["decision"]
                )
            else:
                decision = str(review.get("decision", feedback)).strip()

            extra: Dict[str, Any] = {"manager_feedback": feedback}
            if actor == "human":
                extra["human_feedback"] = _require_text(
                    review.get("human_feedback"),
                    "human_feedback",
                    "Human-resolved raised idea",
                )
                extra["manager_escalation_reason"] = str(
                    review.get("manager_escalation_reason", "")
                ).strip()
            if raised_idea["idea_type"] == "decision":
                extra["options"] = decision_options

            record = self._record_from_raised_idea(
                raised_idea=raised_idea,
                level=level,
                actor=actor,
                decision=decision,
                manager_context=str(review.get("context", raised_idea.get("context", ""))),
                extra=extra,
            )
            _apply_runtime_provenance(record, provenance)
            finalized["record"] = self.log.append(record, idempotent=True)
            return review

        self.manager.review_raised_idea(
            pipeline_stage=self.pipeline_stage,
            raised_idea=raised_idea,
            plan_text=self._read_optional(self.paths.plan_path),
            on_finalize=persist_resolution,
            hitl_mode=self.hitl_mode,
        )
        try:
            return finalized["record"]
        except KeyError as exc:
            raise RuntimeError(
                "Raised HITL worker request finalized without an audit record."
            ) from exc

    def prepare_idea_tool_context(
        self,
        *,
        hitl_stage: str,
        actor: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        requires_human_approval: Optional[bool] = None,
        allow_scoring_approval: bool = False,
        proposal_submission_validator: Optional[Callable[[], Dict[str, Any]]] = None,
        proposal_review_path: Optional[Path] = None,
        plan_finish_validator: Optional[Callable[[], Dict[str, Any]]] = None,
        phase_finish_validator: Optional[Callable[[], Dict[str, Any]]] = None,
        scoring_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
        worker_prompt_contexts: Optional[Dict[str, str]] = None,
    ) -> None:
        if hitl_stage not in HITL_STAGES:
            raise HitlValidationError(f"Invalid HITL idea tool hitl_stage: {hitl_stage}")
        if worker_prompt_contexts is not None:
            required_context_phases = {"plan", "execution", "review"}
            missing_contexts = sorted(
                phase
                for phase in required_context_phases
                if not str(worker_prompt_contexts.get(phase, "")).strip()
            )
            if missing_contexts:
                raise HitlValidationError(
                    "HITL worker prompt contexts must define plan, execution, and review; "
                    f"missing: {', '.join(missing_contexts)}."
                )
        if requires_human_approval is None:
            requires_human_approval = (
                hitl_stage == "plan" and self.requires_human_plan_approval
            )
        elif requires_human_approval and not self.requires_human_plan_approval:
            requires_human_approval = False
        self.stop_idea_tool_server()
        self.paths.hitl_dir.mkdir(parents=True, exist_ok=True)
        self.paths.tool_bin_dir.mkdir(parents=True, exist_ok=True)
        if hitl_stage == "proposal" and proposal_submission_validator is None:
            from core.hitl_workspace_guard import HitlWorkspaceWriteGuard

            proposal_guard = HitlWorkspaceWriteGuard.capture_public(self.work_dir)
            proposal_submission_validator = proposal_guard.require_unchanged
        allowed_worker_commands = self._worker_commands_for_stage(hitl_stage)
        from core.hitl_runtime_state import HitlRuntimeState, worker_command_requires_resume

        pending_command = HitlRuntimeState(self.work_dir).pending_worker_command()
        if worker_command_requires_resume(pending_command):
            allowed_worker_commands.add("hitl-resume-worker-request")

        self._tool_context = {
            "work_dir": str(self.work_dir.resolve()),
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": hitl_stage,
            "actor": actor or self.pipeline_stage,
            "level": "C",
            "provenance": provenance or {},
            "requires_human_approval": requires_human_approval,
            "hitl_mode": self.hitl_mode.value,
            "allow_scoring_approval": allow_scoring_approval,
            "proposal_submission_validator": proposal_submission_validator,
            "proposal_review_path": str(Path(proposal_review_path).resolve())
            if proposal_review_path is not None
            else "",
            "supplied_plan_finish_validator": plan_finish_validator,
            "supplied_phase_finish_validator": phase_finish_validator,
            "scoring_handler": scoring_handler,
            "worker_prompt_contexts": dict(worker_prompt_contexts or {}),
            "allowed_worker_commands": allowed_worker_commands,
        }
        self._install_stage_guards(hitl_stage)
        self._phase_finish_result = None
        self._phase_finish_request_key = ""
        self._phase_finish_response = None
        self._proposal_submit_result = None
        self._raised_idea_results = {}
        self._started_scoring_requests = set()
        self._start_idea_tool_server()
        self._write_idea_tool_commands()

    def _install_stage_guards(self, hitl_stage: str) -> None:
        """Install the runtime-owned validation boundary for one worker stage."""
        from core.hitl_workspace_guard import HitlWorkspaceWriteGuard

        self._tool_context["plan_finish_validator"] = None
        self._tool_context["phase_finish_validator"] = None
        if hitl_stage == "plan":
            supplied = self._tool_context.get("supplied_plan_finish_validator")
            if callable(supplied):
                self._tool_context["plan_finish_validator"] = supplied
                return
            plan_guard = HitlWorkspaceWriteGuard.capture_public(self.work_dir)
            plan_path = self.paths.plan_path.relative_to(self.work_dir).as_posix()

            def validate_plan_finish() -> Dict[str, Any]:
                guard_result = plan_guard.allow_only([plan_path])
                if not bool(guard_result.get("valid")):
                    return guard_result
                return self._validate_living_plan_file()

            self._tool_context["plan_finish_validator"] = validate_plan_finish
            return
        if hitl_stage not in {"execution", "review"}:
            return

        protected_paths = ["scoring/results.json", ".neurico/autoresearch_state.json"]
        if self.pipeline_stage != "rule_maker":
            # Evaluator internals are runtime/rule-maker owned. Their absence
            # from a worker workspace is part of the protected boundary too,
            # so a worker-created replacement is retryable at finish time and
            # can never become the evaluator for a later attempt.
            from core.scoring_seal import SEALED_PATHS

            protected_paths = [
                "scoring/interface.md",
                *(relative.rstrip("/") for relative in SEALED_PATHS),
                *protected_paths,
            ]
        protected_guard = HitlWorkspaceWriteGuard.capture_paths(
            self.work_dir,
            protected_paths,
        )
        supplied = self._tool_context.get("supplied_phase_finish_validator")

        def combined_phase_finish_validator() -> Dict[str, Any]:
            protection = protected_guard.require_unchanged()
            if not bool(protection.get("valid")):
                return protection
            if callable(supplied):
                return supplied()
            return {"valid": True, "issues": []}

        self._tool_context["phase_finish_validator"] = combined_phase_finish_validator

    def _validate_living_plan_file(self) -> Dict[str, Any]:
        """Require the worker-owned plan to remain a regular workspace file."""
        try:
            plan = self.paths.plan_path
            relative = plan.relative_to(self.work_dir.resolve())
            if not relative.parts:
                raise ValueError("missing workspace-relative plan path")
            stats = plan.lstat()
            if stat.S_ISLNK(stats.st_mode) or not stat.S_ISREG(stats.st_mode):
                raise ValueError("living plan must be a regular file")
            if not plan.read_text(encoding="utf-8").strip():
                raise ValueError("living plan must not be empty")
        except (OSError, ValueError) as exc:
            return {"valid": False, "issues": [f"Invalid living plan: {exc}"]}
        return {"valid": True, "issues": []}

    def transition_worker_stage(self, to_stage: str, *, prompt_block: str = "") -> None:
        """Move one live worker session to its next runtime-owned HITL stage.

        A stage prompt and command surface are a single protocol boundary.  This
        method is deliberately the only in-session transition path so a worker
        cannot receive execution instructions while plan guards remain active.
        """
        from_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
        allowed = {"plan": {"execution"}, "execution": {"review"}}
        if to_stage not in allowed.get(from_stage, set()):
            raise HitlValidationError(
                f"Invalid HITL worker stage transition: {from_stage} -> {to_stage}."
            )
        self._tool_context["hitl_stage"] = to_stage
        self.current_hitl_stage = to_stage
        self._tool_context["requires_human_approval"] = False
        self._tool_context["allowed_worker_commands"] = self._worker_commands_for_stage(to_stage)
        self._install_stage_guards(to_stage)
        self._write_idea_tool_commands()
        if prompt_block:
            from core.hitl_runtime_state import HitlRuntimeState

            HitlRuntimeState(self.work_dir).update_worker_continuation(
                hitl_stage=to_stage,
                prompt_block=prompt_block,
                status="running",
            )

    @staticmethod
    def _worker_commands_for_stage(hitl_stage: str) -> set[str]:
        """Return the command surface owned by one worker invocation.

        The worker receives read/reporting commands plus the one workflow
        transition appropriate to its stage.  Runtime can later add the resume
        command only when it launches a replacement against a held request.
        """
        commands = {"hitl-report-idea", "hitl-view-ideas"}
        if hitl_stage == "proposal":
            commands.update({"hitl-submit-proposal", "view_current_frontier"})
        elif hitl_stage in {"execution", "review"}:
            commands.update({"hitl-raise-idea", "hitl-finish-phase"})
        else:
            commands.add("hitl-finish-phase")
        return commands

    def _enable_worker_command(self, command_name: str) -> None:
        if command_name not in _WORKER_COMMAND_MODULES:
            raise HitlValidationError(f"Unknown HITL worker command: {command_name}")
        commands = self._tool_context.get("allowed_worker_commands")
        if not isinstance(commands, set):
            commands = set(commands or [])
            self._tool_context["allowed_worker_commands"] = commands
        if command_name not in commands:
            commands.add(command_name)
            self._write_idea_tool_commands()

    def _require_worker_command(self, command_name: str) -> None:
        commands = self._tool_context.get("allowed_worker_commands")
        allowed = set(commands or [])
        if command_name in allowed:
            return
        stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
        available = ", ".join(f"`{name}`" for name in sorted(allowed)) or "none"
        raise HitlValidationError(
            "HITL_ERROR command_unavailable\n"
            f"`{command_name}` is not available during the current {stage} worker invocation.\n"
            f"Runtime currently allows: {available}.\n"
            "Follow the current runtime instruction and retry only with an available command."
        )

    def register_worker_prompt(self, prompt_block: str) -> None:
        """Persist the runtime-owned continuation point for the active worker.

        A provider process can exit after receiving feedback or phase approval.
        The worker never owns this state: runtime records the exact already-rendered
        prompt and may launch a continuation worker against the same tool server.
        """
        prompt = _require_text(prompt_block, "prompt_block", "HITL worker continuation")
        from core.hitl_runtime_state import HitlRuntimeState

        HitlRuntimeState(self.work_dir).record_worker_continuation(
            {
                "pipeline_stage": self.pipeline_stage,
                "hitl_stage": str(self._tool_context.get("hitl_stage", self.current_hitl_stage)),
                "actor": str(self._tool_context.get("actor", self.pipeline_stage)),
                "provenance": dict(self._tool_context.get("provenance") or {}),
                "hitl_mode": self.hitl_mode.value,
                "prompt_block": prompt,
                "replacement_count": 0,
                "status": "running",
            }
        )

    def _update_worker_continuation(
        self,
        *,
        prompt_block: Optional[str] = None,
        hitl_stage: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        updates: Dict[str, Any] = {}
        if prompt_block:
            updates["prompt_block"] = prompt_block
        if hitl_stage:
            updates["hitl_stage"] = hitl_stage
        if status:
            updates["status"] = status
        if updates:
            from core.hitl_runtime_state import HitlRuntimeState

            HitlRuntimeState(self.work_dir).update_worker_continuation(**updates)

    def _clear_worker_continuation(self) -> None:
        from core.hitl_runtime_state import HitlRuntimeState

        HitlRuntimeState(self.work_dir).clear_worker_continuation()

    def set_scoring_result(self, scorer_result: Dict[str, Any]) -> None:
        """Attach a runtime-owned initial-stage scoring result to phase completion."""
        if not isinstance(scorer_result, dict):
            raise HitlValidationError("Runtime scorer result must be a JSON object.")
        self._tool_context["scorer_result"] = dict(scorer_result)

    def set_scored_candidate(self, candidate: Dict[str, Any]) -> None:
        """Attach the finalized AutoResearch candidate to the held finish request."""
        if not isinstance(candidate, dict):
            raise HitlValidationError("Runtime scored candidate must be a JSON object.")
        self._tool_context["scored_candidate"] = dict(candidate)

    def worker_continuation(self) -> Optional[Dict[str, Any]]:
        """Return the runtime-owned replacement-worker state, when present."""
        from core.hitl_runtime_state import HitlRuntimeState

        continuation = HitlRuntimeState(self.work_dir).worker_continuation()
        return dict(continuation) if isinstance(continuation, dict) else None

    def resolved_worker_response(self) -> Optional[Dict[str, Any]]:
        """Return the response retained for an idempotent worker-command retry."""
        from core.hitl_runtime_state import HitlRuntimeState

        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") != "resolved":
            return None
        response = pending.get("response")
        return dict(response) if isinstance(response, dict) else None

    def _pending_worker_request_replacement(
        self,
        *,
        phase: str,
        worker_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Reconnect a replacement worker to one durable held command."""
        from core.hitl_runtime_state import HitlRuntimeState, worker_command_requires_resume

        state = HitlRuntimeState(self.work_dir)
        pending = state.pending_worker_command()
        continuation = state.worker_continuation()
        if not worker_command_requires_resume(pending) or not isinstance(continuation, dict):
            return None
        if not str(continuation.get("prompt_block", "")).strip():
            return None

        prompt_block = _load_hitl_template("worker_resume_pending_request.txt")
        self._update_worker_continuation(
            prompt_block=prompt_block,
            hitl_stage=str(continuation.get("hitl_stage", "")).strip() or None,
            status="replacement_pending",
        )
        state.mark_worker_replacement()
        self._enable_worker_command("hitl-resume-worker-request")
        return {
            "status": "replacement",
            "approved": False,
            "replacement": True,
            "prompt_block": prompt_block,
            "phase": phase,
            "worker_exit_warning": (
                f"{worker_name} exited while a runtime-held request still required replay. "
                "Runtime terminated its remaining processes and will reconnect a "
                "replacement worker to the preserved request."
            ),
        }

    def _join_live_worker_request_handler(self, *, expected_kind: str) -> bool:
        """Wait for the in-process owner of a durable worker request."""
        from core.hitl_runtime_state import HitlRuntimeState

        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        if (
            not isinstance(pending, dict)
            or str(pending.get("kind", "")).strip() != expected_kind
            or not self._worker_request_lock.locked()
        ):
            return False

        # The HTTP handler owns this lock across manager/human review and all
        # runtime transition work. Joining it preserves the single ordered
        # completion path when the provider exits before its command child.
        self._worker_request_lock.acquire()
        self._worker_request_lock.release()
        return True

    def idea_tool_env(self, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = dict(base_env or os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["NEURICO_HITL_URL"] = self._tool_url
        env["NEURICO_HITL_TOKEN"] = self._tool_token
        env["NEURICO_PROJECT_ROOT"] = str(Path(__file__).resolve().parents[2])
        env["NEURICO_PYTHON"] = sys.executable
        env["NEURICO_HITL_MODE"] = self.hitl_mode.value
        env["PATH"] = f"{self.paths.tool_bin_dir}{os.pathsep}{env.get('PATH', '')}"
        if self.use_hitl_autoresearch_whiteboard:
            from core.hitl_whiteboard import hitl_whiteboard_env

            env.update(hitl_whiteboard_env())
        return env

    def clear_idea_tool_context(self) -> None:
        self.stop_idea_tool_server()
        self._tool_context = {}
        self._phase_finish_result = None
        self._phase_finish_request_key = ""
        self._phase_finish_response = None
        self._proposal_submit_result = None
        self._raised_idea_results = {}

    def reload_manager_after_state_restore(self) -> None:
        """Refresh long-lived manager caches after private HITL rollback."""
        reloader = getattr(self.manager, "reload_after_runtime_restore", None)
        if callable(reloader):
            reloader()

    def abandon_pending_worker_request_for_rollback(self, reason: str) -> None:
        """Cancel a held command before restoring its failed attempt boundary."""
        canceller = getattr(self.manager, "abandon_worker_request_for_rollback", None)
        if callable(canceller):
            canceller(reason)

    def stop_idea_tool_server(self) -> None:
        server = self._tool_server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._tool_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)
        self._tool_server = None
        self._tool_thread = None
        self._tool_url = ""
        self._tool_token = ""

    def log_reported_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._tool_lock:
            record = self._record_from_tool_payload(payload, raised=False)
            existing = self.log.find_equivalent(record)
            if existing is not None:
                return existing
            return self.log.append(record)

    def submit_proposal_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._worker_request_lock.acquire(blocking=False):
            raise HitlActiveWorkerRequestError(self._pending_worker_command())
        try:
            return self._submit_proposal_payload_locked(payload)
        finally:
            self._worker_request_lock.release()

    def _submit_proposal_payload_locked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._tool_lock:
            validator = self._tool_context.get("proposal_submission_validator")
            if callable(validator):
                validation = validator()
                if not bool(validation.get("valid")):
                    issues = validation.get("issues", [])
                    if not isinstance(issues, list):
                        issues = [str(issues)]
                    raise HitlValidationError(
                        "HITL_ERROR proposal_workspace_boundary\n"
                        "Runtime rejected this proposal because proposal generation changed public "
                        "workspace files before approval:\n"
                        + "\n".join(f"- {str(issue)}" for issue in issues if str(issue).strip())
                        + "\nDo not make further public workspace changes in this proposer session. "
                        "Runtime will discard this invalid attempt."
                    )
            record = self._record_from_proposal_tool_payload(payload)
            submission_key = self._proposal_submission_key(record)
            prior_result = self._proposal_submit_result
            if isinstance(prior_result, dict):
                prior_idea_id = str(prior_result.get("proposal_idea_id", "")).strip()
                prior_record = self._proposal_record(prior_idea_id)
                if (
                    prior_record is not None
                    and self._proposal_submission_key(prior_record) == submission_key
                ):
                    return dict(prior_result)
            proposal_record = self.log.append(record, idempotent=True)
            prior_admission = self._terminal_proposal_admission(proposal_record)
            if prior_admission is not None:
                self._proposal_submit_result = prior_admission
                return dict(prior_admission)
            finalized: Dict[str, Dict[str, Any]] = {}

            def persist_admission(review: Dict[str, Any]) -> Dict[str, Any]:
                manager_record = self._log_proposal_manager_review(
                    proposal_record=proposal_record,
                    review=review,
                )
                if review["status"] == "rejected_illegal":
                    feedback = str(review["manager_feedback"]).strip()
                    finalized["result"] = {
                        "status": "feedback",
                        "feedback": feedback,
                        "instruction": (
                            "This proposal is rejected. Do not edit or resubmit it. Create a "
                            "new proposal that follows this feedback, then submit that new proposal "
                            "with `hitl-submit-proposal` in this same proposer session."
                        ),
                        "proposal_idea_id": proposal_record["idea_id"],
                        "manager_idea_id": manager_record["idea_id"],
                    }
                elif self.hitl_mode is HitlMode.AUTO:
                    finalized["result"] = self._finalize_proposal_manager_admission(
                        proposal_record=proposal_record,
                        manager_record=manager_record,
                        review=review,
                    )
                else:
                    finalized["result"] = self._finalize_proposal_human_admission(
                        proposal_record=proposal_record,
                        manager_record=manager_record,
                        review=review,
                    )
                self._write_proposal_review_artifact(
                    proposal_record=proposal_record,
                    manager_record=manager_record,
                    admission=finalized["result"],
                )
                return review

            self.manager.review_proposal(
                pipeline_stage=self.pipeline_stage,
                proposal_text=str(proposal_record["proposal"]),
                on_finalize=persist_admission,
                request_context={
                    "proposal_idea_id": proposal_record["idea_id"],
                    "proposal_submission_key": submission_key,
                    "proposal_payload": {
                        "proposal_type": proposal_record["proposal_type"],
                        "premises": proposal_record["premises"],
                        "proposal": proposal_record["proposal"],
                    },
                },
                hitl_mode=self.hitl_mode,
            )
            try:
                result = finalized["result"]
            except KeyError as exc:
                raise RuntimeError(
                    "Proposal HITL worker request finalized without admission records."
                ) from exc
            self._proposal_submit_result = result
            if result.get("status") == "feedback":
                self._update_worker_continuation(
                    prompt_block=self.proposal_replacement_prompt_block(
                        str(result.get("feedback", ""))
                    ),
                    hitl_stage="proposal",
                    status="running",
                )
            return result

    @staticmethod
    def _proposal_submission_key(record: Dict[str, Any]) -> str:
        """Identify one proposal command retry without exposing runtime request ids."""
        return hashlib.sha256(
            _compact_json(
                {
                    "proposal_type": record.get("proposal_type"),
                    "premises": record.get("premises", []),
                    "proposal": record.get("proposal"),
                    "provenance": {
                        key: record.get(key)
                        for key in ("parent_node_id", "attempt_id")
                        if str(record.get(key, "")).strip()
                    },
                }
            ).encode("utf-8")
        ).hexdigest()

    def _write_proposal_review_artifact(
        self,
        *,
        proposal_record: Dict[str, Any],
        manager_record: Dict[str, Any],
        admission: Dict[str, Any],
    ) -> None:
        """Materialize the runtime-owned public review trace for one proposal."""
        raw_path = str(self._tool_context.get("proposal_review_path", "")).strip()
        if not raw_path:
            return
        path = Path(raw_path)
        payload = {
            "proposal_idea_id": proposal_record["idea_id"],
            "proposal_type": proposal_record["proposal_type"],
            "proposal": proposal_record["proposal"],
            "premises": proposal_record["premises"],
            "parent_node_sha": proposal_record.get("parent_node_id", ""),
            "attempt_id": proposal_record.get("attempt_id", ""),
            "manager_legality_decision_idea_id": manager_record["idea_id"],
            "admission_status": admission.get("status", ""),
            "manager_feedback": admission.get("feedback", ""),
        }
        if admission.get("human_idea_id"):
            payload["human_admission_decision_idea_id"] = admission["human_idea_id"]
        if admission.get("manager_admission_idea_id"):
            payload["manager_admission_decision_idea_id"] = admission[
                "manager_admission_idea_id"
            ]
        atomic_write_json(
            path,
            payload,
            ensure_ascii=False,
            indent=2,
            fsync_parent=False,
        )

    @staticmethod
    def _raised_idea_request_key(record: Dict[str, Any]) -> str:
        """Identify one blocking command retry within the current worker session."""
        return hashlib.sha256(
            _compact_json(HitlIdeaLog.logical_payload(record)).encode("utf-8")
        ).hexdigest()

    def _phase_finish_request_key_for(
        self,
        *,
        hitl_stage: str,
        plan_fingerprint: str,
        workspace_fingerprint: str,
        summary: str,
        related_artifacts: List[Dict[str, str]],
    ) -> str:
        return hashlib.sha256(
            _compact_json(
                {
                    "pipeline_stage": self.pipeline_stage,
                    "hitl_stage": hitl_stage,
                    "plan_fingerprint": plan_fingerprint,
                    "workspace_fingerprint": workspace_fingerprint,
                    "summary": summary,
                    "related_artifacts": related_artifacts,
                    "actor": self._tool_context.get("actor", self.pipeline_stage),
                    "provenance": self._tool_context.get("provenance", {}),
                }
            ).encode("utf-8")
        ).hexdigest()

    def _current_plan_fingerprint(self) -> str:
        """Fingerprint the worker-owned control artifact for finish-command retries."""
        try:
            stats = self.paths.plan_path.lstat()
        except FileNotFoundError:
            return "missing"
        if stat.S_ISLNK(stats.st_mode) or not stat.S_ISREG(stats.st_mode):
            return "invalid"
        return hashlib.sha256(self.paths.plan_path.read_bytes()).hexdigest()

    def _proposal_record(self, idea_id: str) -> Optional[Dict[str, Any]]:
        for candidate in reversed(self.log.records()):
            if candidate.get("idea_id") != idea_id:
                continue
            if candidate.get("idea_type") != "proposal":
                return None
            return candidate
        return None

    def _terminal_proposal_admission(
        self,
        proposal_record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Return the terminal admission already recorded for one proposal.

        An exact retry after runtime has finalized an illegal or human-rejected
        proposal must not reopen the proposal-review request. The worker must
        create a new proposal instead. An approved retry is harmless and
        returns the original approval.
        """
        proposal_id = str(proposal_record.get("idea_id", "")).strip()
        if not proposal_id:
            return None
        for record in reversed(self.log.records()):
            if record.get("idea_type") != "decision":
                continue
            premises = _normalize_premises(record.get("premises"))
            if proposal_id not in premises:
                continue
            decision_needed = str(record.get("decision_needed", "")).strip()
            if (
                record.get("level") == "A"
                and decision_needed
                == "Should this AutoResearch proposal be admitted to experiment execution?"
            ):
                if record.get("decision") == "O1":
                    return {
                        "status": "approved",
                        "instruction": "The proposal is already admitted. Stop proposal generation now.",
                        "proposal_idea_id": proposal_id,
                        "proposal": proposal_record.get("proposal", ""),
                    }
                return {
                    "status": "feedback",
                    "feedback": str(record.get("manager_feedback", "")).strip(),
                    "human_feedback": str(record.get("human_feedback", "")).strip(),
                    "instruction": (
                        "This proposal was already rejected. Create a new proposal using "
                        "the returned feedback, then submit that new proposal in this same session."
                    ),
                    "proposal_idea_id": proposal_id,
                }
            if (
                record.get("level") == "B"
                and record.get("actor") == "manager"
                and decision_needed
                == "Should this AutoResearch proposal be admitted to experiment execution?"
            ):
                if record.get("decision") == "O1":
                    return {
                        "status": "approved",
                        "instruction": "The proposal is already admitted. Stop proposal generation now.",
                        "proposal_idea_id": proposal_id,
                        "proposal": proposal_record.get("proposal", ""),
                    }
                return {
                    "status": "feedback",
                    "feedback": str(record.get("manager_feedback", "")).strip(),
                    "instruction": (
                        "This proposal was already rejected. Create a new proposal using "
                        "the returned feedback, then submit that new proposal in this same session."
                    ),
                    "proposal_idea_id": proposal_id,
                }
            if (
                record.get("level") == "B"
                and record.get("actor") == "manager"
                and decision_needed
                in {
                    "Is this AutoResearch proposal legal to show to the human for approval?",
                    "Is this AutoResearch proposal legal for admission review?",
                }
                and record.get("decision") == "O2"
            ):
                return {
                    "status": "feedback",
                    "feedback": str(record.get("manager_feedback", "")).strip(),
                    "instruction": (
                        "This proposal was already rejected. Create a new proposal using "
                        "the returned feedback, then submit that new proposal in this same session."
                    ),
                    "proposal_idea_id": proposal_id,
                }
        return None

    def proposal_submit_result_after_worker_exit(
        self,
        result: Dict[str, Any],
        *,
        worker_name: str,
    ) -> Dict[str, Any]:
        self._join_live_worker_request_handler(expected_kind="proposal")
        cancelled = self._cancelled_worker_command_result(
            result,
            phase="proposal",
            worker_name=worker_name,
        )
        if cancelled is not None:
            return cancelled
        submitted = self._proposal_submit_result
        if submitted and submitted.get("status") == "approved":
            validator = self._tool_context.get("proposal_submission_validator")
            if callable(validator):
                validation = validator()
                if not bool(validation.get("valid")):
                    issues = validation.get("issues", [])
                    if not isinstance(issues, list):
                        issues = [str(issues)]
                    return {
                        "success": False,
                        "hitl": True,
                        "phase": "proposal",
                        "error": (
                            f"{worker_name} changed the public workspace after proposal admission. "
                            "Runtime discarded the proposal:\n"
                            + "\n".join(
                                f"- {str(issue)}" for issue in issues if str(issue).strip()
                            )
                        ),
                    }
            self._clear_worker_continuation()
            return {
                **submitted,
                "worker_exit_warning": (
                    f"{worker_name} exited after runtime admitted the proposal. "
                    "Runtime retained the admitted proposal because no proposer action remained."
                    if not result.get("success")
                    else ""
                ),
            }
        if submitted and submitted.get("status") == "feedback":
            continuation = self.worker_continuation()
            prompt_block = str((continuation or {}).get("prompt_block", "")).strip()
            if prompt_block:
                self._update_worker_continuation(status="replacement_pending")
                from core.hitl_runtime_state import HitlRuntimeState

                HitlRuntimeState(self.work_dir).mark_worker_replacement()
                return {
                    **submitted,
                    "replacement": True,
                    "prompt_block": prompt_block,
                    "worker_exit_warning": (
                        f"{worker_name} exited after proposal feedback. Runtime will launch "
                        "a proposer continuation with the same HITL state."
                    ),
                }
            return {
                **result,
                "success": False,
                "hitl": True,
                "phase": "proposal",
                "error": (
                    f"{worker_name} exited after proposal feedback, but runtime has no "
                    "continuation prompt to launch safely."
                ),
            }
        pending_replacement = self._pending_worker_request_replacement(
            phase="proposal",
            worker_name=worker_name,
        )
        if pending_replacement is not None:
            return pending_replacement
        if result.get("background_processes_terminated"):
            return {
                **result,
                "success": False,
                "hitl": True,
                "phase": "proposal",
                "error": (
                    f"{worker_name} left background processes without a durable "
                    "proposal decision or resumable request. Runtime terminated them "
                    "and will not advance proposal admission."
                ),
            }
        continuation = HitlRuntime.worker_continuation(self)
        prompt_block = str((continuation or {}).get("prompt_block", "")).strip()
        if prompt_block:
            self._update_worker_continuation(status="replacement_pending")
            from core.hitl_runtime_state import HitlRuntimeState

            HitlRuntimeState(self.work_dir).mark_worker_replacement()
            return {
                "status": "replacement",
                "replacement": True,
                "prompt_block": prompt_block,
                "worker_exit_warning": (
                    f"{worker_name} exited before proposal admission. Runtime will launch "
                    "a proposer continuation from the preserved HITL state."
                ),
            }
        return {
            **result,
            "success": False,
            "hitl": True,
            "phase": "proposal",
            "error": (
                f"{worker_name} exited without an approved hitl-submit-proposal result. "
                "AutoResearch proposal admission must be runtime-mediated through "
                "hitl-submit-proposal."
            ),
        }

    def view_ideas_for_tool(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._tool_lock:
            idea_id = str((payload or {}).get("idea_id", "")).strip()
            if idea_id:
                try:
                    return {
                        "ideas": [
                            record
                            for record in self.log.records()
                            if record.get("idea_id") == idea_id
                        ],
                        "text": self.log.render_for_agent(idea_id=idea_id),
                    }
                except HitlValidationError as exc:
                    raise HitlValidationError(
                        "HITL_ERROR unknown_idea_id\n"
                        f"{exc}\n"
                        "Run `hitl-view-ideas` to inspect available finalized idea ids, then retry."
                    ) from exc
            return {
                "ideas": self.log.records(),
                "text": self.log.render_for_agent(),
            }

    def view_current_frontier_for_tool(self) -> Dict[str, Any]:
        if (
            self.pipeline_stage != "experiment_runner"
            or self._tool_context.get("hitl_stage") != "proposal"
        ):
            raise HitlValidationError(
                "HITL_ERROR frontier_wrong_context\n"
                "`view_current_frontier` is available only during AutoResearch HITL proposal generation.\n"
                "Continue with the command appropriate for the current HITL phase."
            )
        from core.hitl_frontier import HitlFrontierStore

        current = HitlFrontierStore(self.work_dir).current_for_worker()
        return {"frontier": current, "text": json.dumps(current, ensure_ascii=False, indent=2)}

    def resolve_tool_raised_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._worker_request_lock.acquire(blocking=False):
            raise HitlActiveWorkerRequestError(self._pending_worker_command())
        try:
            with self._tool_lock:
                raised_idea = self._record_from_tool_payload(payload, raised=True)
                raised_idea["reason_for_escalation"] = _require_text(
                    payload.get("reason_for_escalation"),
                    "reason_for_escalation",
                    "Raised HITL idea",
                )
                request_key = self._raised_idea_request_key(raised_idea)
                prior = self._raised_idea_results.get(request_key)
                if prior is not None:
                    return dict(prior)
                logged = self.resolve_raised_payload(
                    raised_idea,
                    provenance=self._tool_context.get("provenance"),
                )
                feedback = str(
                    logged.get("manager_feedback")
                    or logged.get("human_feedback")
                    or logged.get("decision")
                    or ""
                ).strip()
                hitl_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
                if hitl_stage == "review":
                    prompt_block = self.compose_worker_prompt(
                        hitl_stage="review",
                        phase_prompt=self.review_prompt_block(feedback),
                    )
                else:
                    prompt_block = self.compose_worker_prompt(
                        hitl_stage="execution",
                        phase_prompt=self.execution_prompt_block(
                            mode="continue",
                            feedback=feedback,
                        ),
                    )
                self._update_worker_continuation(
                    prompt_block=prompt_block,
                    hitl_stage=hitl_stage,
                    status="running",
                )
                result = {
                    "idea_id": logged.get("idea_id"),
                    "decision": logged.get("decision", ""),
                    "feedback": feedback,
                    "prompt_block": prompt_block,
                }
                self._raised_idea_results[request_key] = dict(result)
                return result
        finally:
            self._worker_request_lock.release()

    def log_frontier_decision(
        self,
        *,
        proposal_idea_id: str,
        accepted: bool,
        reason: str,
        provenance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Finalize the manager's strategic scored-candidate decision."""
        parent_node_id = str(provenance.get("parent_node_id", "")).strip()
        attempt_id = str(provenance.get("attempt_id", "")).strip()
        for existing in self.log.records():
            if (
                parent_node_id
                and attempt_id
                and existing.get("parent_node_id") == parent_node_id
                and existing.get("attempt_id") == attempt_id
                and existing.get("idea_type") == "decision"
                and existing.get("actor") == "manager"
                and existing.get("decision_needed")
                == "Should the scored candidate be retained in the HITL research frontier?"
            ):
                return existing
        premises = [proposal_idea_id]
        pending_request = self._pending_worker_command()
        scoring_review_idea_id = str(
            (pending_request or {}).get("scoring_review_idea_id", "")
        ).strip()
        if scoring_review_idea_id and scoring_review_idea_id not in premises:
            premises.append(scoring_review_idea_id)
        record = {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "method_choice",
            "level": "B",
            "actor": "manager",
            "premises": premises,
            "context": "Manager reviewed the scored AutoResearch candidate against its active frontier direction.",
            "related_artifacts": [],
            "decision_needed": "Should the scored candidate be retained in the HITL research frontier?",
            "options": [
                "Accept candidate into the frontier.",
                "Reject candidate and restore its parent frontier node.",
            ],
            "decision": "O1" if accepted else "O2",
            "manager_feedback": str(reason).strip(),
            "raised": False,
        }
        _apply_runtime_provenance(record, provenance)
        return self.log.append(record, idempotent=True)

    def log_frontier_maintenance_decision(
        self,
        *,
        action: str,
        node_sha: str,
        active_node_shas: List[str],
        reason: str,
        premise_idea_id: str,
    ) -> Dict[str, Any]:
        """Log one runtime-constrained manager frontier decision.

        The manager chooses a node SHA and supplies its rationale. Runtime owns
        the complete option set and translates the selected SHA into the
        schema's stable ``O<n>`` decision id.
        """
        if action not in {"prune", "select"}:
            raise HitlValidationError("Frontier maintenance action must be prune or select")
        chosen = str(node_sha).strip()
        options = [
            {"option_id": f"O{index}", "text": f"Frontier node {sha}"}
            for index, sha in enumerate(active_node_shas, start=1)
        ]
        decision = next(
            (option["option_id"] for option in options if option["text"] == f"Frontier node {chosen}"),
            "",
        )
        if not decision:
            raise HitlValidationError("Manager selected a node outside the runtime frontier options")
        rationale = _require_text(reason, "reason", "Frontier maintenance decision")
        premise = _require_text(
            premise_idea_id, "premise_idea_id", "Frontier maintenance decision"
        )
        decision_needed = (
            "Which active frontier node should be removed from the portfolio?"
            if action == "prune"
            else "Which remaining active frontier node should be the workspace basis for the next proposal?"
        )
        context = (
            "Runtime enforced the active-frontier capacity before the next proposal."
            if action == "prune"
            else "Runtime requested the manager to choose the workspace basis for the next proposal."
        )
        for existing in reversed(self.log.records()):
            if (
                existing.get("idea_type") == "decision"
                and existing.get("level") == "B"
                and existing.get("actor") == "manager"
                and existing.get("decision_needed") == decision_needed
                and existing.get("premises") == [premise]
                and existing.get("decision") == decision
            ):
                return existing
        provenance: Dict[str, Any] = {}
        for record in reversed(self.log.records()):
            if str(record.get("idea_id", "")).strip() == premise:
                provenance = _runtime_provenance(record)
                break
        record = {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "other",
            "level": "B",
            "actor": "manager",
            "premises": [premise],
            "context": context,
            "related_artifacts": [],
            "decision_needed": decision_needed,
            "options": options,
            "decision": decision,
            "manager_feedback": rationale,
            "raised": False,
        }
        _apply_runtime_provenance(record, provenance)
        return self.log.append(record, idempotent=True)

    def log_scoring_recovery_decision(
        self,
        *,
        scoring_review_idea_id: str,
        context: str,
        manager_feedback: str,
        provenance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Finalize manager scoring-repair feedback as one idempotent B-level idea."""
        premise = _require_text(
            scoring_review_idea_id,
            "scoring_review_idea_id",
            "AutoResearch scoring-recovery decision",
        )
        feedback = _require_text(
            manager_feedback,
            "manager_feedback",
            "AutoResearch scoring-recovery decision",
        )
        for existing in reversed(self.log.records()):
            if (
                existing.get("pipeline_stage") == "experiment_runner"
                and existing.get("hitl_stage") == "review"
                and existing.get("idea_type") == "decision"
                and existing.get("level") == "B"
                and existing.get("actor") == "manager"
                and existing.get("premises") == [premise]
                and existing.get("decision_needed")
                == "Must this candidate be repaired before objective scoring can continue?"
            ):
                return existing
        record = {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "evaluation_choice",
            "level": "B",
            "actor": "manager",
            "premises": [premise],
            "context": _require_text(
                context,
                "context",
                "AutoResearch scoring-recovery decision",
            ),
            "related_artifacts": [
                {
                    "path": "scoring/results.json",
                    "description": "Runtime-derived scoring output that required repair.",
                }
            ],
            "decision_needed": "Must this candidate be repaired before objective scoring can continue?",
            "options": ["Return the candidate to the worker for repair and rescore."],
            "decision": "O1",
            "manager_feedback": feedback,
            "raised": True,
        }
        _apply_runtime_provenance(record, provenance)
        return self.log.append(record, idempotent=True)

    def log_initial_scoring_decision(
        self,
        *,
        scoring_review_idea_id: str,
        approved: bool,
        context: str,
        manager_feedback: str,
    ) -> Dict[str, Any]:
        """Record the manager's final initial-score readiness decision."""
        premise = _require_text(
            scoring_review_idea_id,
            "scoring_review_idea_id",
            "Initial AutoResearch scoring decision",
        )
        feedback = str(manager_feedback).strip()
        if not approved:
            feedback = _require_text(
                feedback,
                "manager_feedback",
                "Initial AutoResearch scoring repair decision",
            )
        record = {
            "pipeline_stage": "experiment_runner",
            "hitl_stage": "review",
            "idea_type": "decision",
            "idea_category": "evaluation_choice",
            "level": "B",
            "actor": "manager",
            "premises": [premise],
            "context": _require_text(
                context,
                "context",
                "Initial AutoResearch scoring decision",
            ),
            "related_artifacts": [
                {
                    "path": "scoring/results.json",
                    "description": "Runtime-produced objective scoring result for the initial experiment.",
                }
            ],
            "decision_needed": "Is the scored initial experiment ready to become the AutoResearch root node?",
            "options": [
                "Accept the error-free scored initial experiment as the root node.",
                "Return repair feedback and score the initial experiment again.",
            ],
            "decision": "O1" if approved else "O2",
            "manager_feedback": feedback,
            "raised": not approved,
        }
        return self.log.append(record, idempotent=True)

    def scoring_repair_response(
        self,
        *,
        context: str,
        manager_feedback: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return one held finish request from scoring to review for repair."""
        feedback = _require_text(
            manager_feedback,
            "manager_feedback",
            "Runtime scoring repair response",
        )
        pending = self._pending_worker_command()
        manager_request_key = str((pending or {}).get("request_key", "")).strip()
        if not manager_request_key:
            raise HitlValidationError(
                "Runtime scoring repair has no pending phase-finish request to resume."
            )
        request_key = self._phase_finish_request_key_for(
            hitl_stage=str((pending or {}).get("hitl_stage", "")).strip(),
            plan_fingerprint=str((pending or {}).get("plan_fingerprint", "")).strip(),
            workspace_fingerprint=str(
                (pending or {}).get("workspace_fingerprint", "")
            ).strip(),
            summary=str((pending or {}).get("finish_summary", "")).strip(),
            related_artifacts=_as_related_artifacts(
                (pending or {}).get("related_artifacts")
            ),
        )
        prompt_block = self.compose_worker_prompt(
            hitl_stage="review",
            phase_prompt=self.review_prompt_block(feedback),
        )
        current_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
        if current_stage == "execution":
            self.transition_worker_stage("review", prompt_block=prompt_block)
        elif current_stage == "review":
            # A second scoring repair is a new review revision, not an invalid
            # execution-to-review transition.
            self._install_stage_guards("review")
            self._write_idea_tool_commands()
            self._update_worker_continuation(
                prompt_block=prompt_block,
                hitl_stage="review",
                status="running",
            )
        else:
            raise HitlValidationError(
                f"Runtime scoring repair is invalid during HITL stage {current_stage!r}."
            )
        self._phase_finish_result = {
            "called": True,
            "status": "feedback",
            "hitl_stage": "review",
            "manager_feedback": feedback,
            "context": _require_text(context, "context", "Runtime scoring repair response"),
            "record": dict(record),
            "next_phase": "review",
            "final": False,
        }
        return self._remember_phase_finish_response(
            request_key,
            {
                "status": "feedback",
                "feedback": feedback,
                "next_phase": "review",
                "instruction": (
                    "Objective scoring found repairable issues. Apply the manager feedback, "
                    "update the living plan and affected artifacts, then call "
                    "hitl-finish-phase again."
                ),
                "prompt_block": prompt_block,
                "final": False,
                "record": dict(record),
            },
        )

    def set_scoring_conformance_reporter(
        self, reporter: Optional[Callable[[], str]]
    ) -> None:
        """Provide the sanitized scoring-conformance reporter for manager review.

        The report is advisory evidence for the rule-maker review, never a gate.
        A falsy reporter clears it.
        """
        self._scoring_conformance_reporter = reporter or None

    def _scoring_conformance_report_for_review(self, hitl_stage: str) -> str:
        """Produce the manager-facing conformance report for this finish, if any.

        Only runs past the plan phase, where the evaluator exists. A reporter
        that raises degrades to an ``UNAVAILABLE`` note rather than failing the
        review, so a verifier fault never blocks the rule maker.
        """
        reporter = self._scoring_conformance_reporter
        if not callable(reporter) or hitl_stage == "plan":
            return ""
        try:
            return str(reporter() or "")
        except Exception as exc:
            print(f"⚠️  Scoring conformance report unavailable: {exc}")
            return (
                "Automated conformance check: UNAVAILABLE (the verifier errored). "
                "Decide from your own review of the public design."
            )

    def _durable_conformance_report(self, request_key: str, hitl_stage: str) -> str:
        """Return the conformance report for this phase-finish request, once.

        The report is part of the durable phase-finish request. A resumed request
        replays the report persisted on its pending command instead of rerunning
        the model verifier, so recovery continues from the same evidence and does
        not repeat an expensive verifier call. It is generated only the first
        time this request is raised, then persisted by ``review_phase_finish``.
        """
        pending = self._pending_worker_command()
        if (
            isinstance(pending, dict)
            and str(pending.get("request_key", "")) == request_key
            and "verifier_report" in pending
        ):
            return str(pending.get("verifier_report") or "")
        return self._scoring_conformance_report_for_review(hitl_stage)

    def finish_tool_phase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._worker_request_lock.acquire(blocking=False):
            raise HitlActiveWorkerRequestError(self._pending_worker_command())
        try:
            return self._finish_tool_phase_locked(payload)
        finally:
            self._worker_request_lock.release()

    def _terminal_phase_finish_response(self) -> Optional[Dict[str, Any]]:
        """Replay the terminal result for this runtime-owned worker invocation."""
        if (
            isinstance(self._phase_finish_result, dict)
            and bool(self._phase_finish_result.get("final"))
            and isinstance(self._phase_finish_response, dict)
            and bool(self._phase_finish_response.get("final"))
        ):
            return dict(self._phase_finish_response)

        pending = self._pending_worker_command()
        if (
            not isinstance(pending, dict)
            or pending.get("kind") != "phase_finish"
            or pending.get("status") != "resolved"
            or pending.get("pipeline_stage") != self.pipeline_stage
        ):
            return None
        response = pending.get("response")
        if not isinstance(response, dict) or not bool(response.get("final")):
            return None
        pending_provenance = pending.get("provenance")
        current_provenance = self._tool_context.get("provenance")
        if (
            not isinstance(pending_provenance, dict)
            or not isinstance(current_provenance, dict)
            or pending_provenance != current_provenance
        ):
            return None
        return dict(response)

    def _phase_finish_response_for_retry(
        self,
        request_key: str,
        *,
        hitl_stage: str,
        plan_fingerprint: str,
        workspace_fingerprint: str,
        summary: str,
        related_artifacts: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if (
            self._phase_finish_request_key == request_key
            and self._phase_finish_response is not None
        ):
            return dict(self._phase_finish_response)
        # A terminal response advances the live tool context to ``complete``
        # (or ``scoring``).  An exact retry after the command response was
        # lost must receive that terminal result, not initiate a fictional
        # review of the terminal state.  Non-terminal feedback remains bound
        # to the plan fingerprint below so a worker revision starts a new
        # review as intended.
        previous = self._phase_finish_result
        if (
            self._phase_finish_response is not None
            and isinstance(previous, dict)
            and bool(previous.get("final"))
            and hitl_stage in {"complete", "scoring"}
            and previous.get("plan_fingerprint") == plan_fingerprint
            and previous.get("workspace_fingerprint") == workspace_fingerprint
            and previous.get("summary") == summary
            and previous.get("related_artifacts") == related_artifacts
        ):
            return dict(self._phase_finish_response)
        # A prior response may have advanced the runtime stage (for example,
        # plan approval enters execution). The worker's exact retry must still
        # receive that prior response rather than start another review.
        if (
            self._phase_finish_response is not None
            and isinstance(previous, dict)
            and previous.get("hitl_stage") == hitl_stage
            and previous.get("plan_fingerprint") == plan_fingerprint
            and previous.get("workspace_fingerprint") == workspace_fingerprint
            and previous.get("summary") == summary
            and previous.get("related_artifacts") == related_artifacts
        ):
            return dict(self._phase_finish_response)
        return None

    def _remember_phase_finish_response(
        self,
        request_key: str,
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._phase_finish_request_key = request_key
        self._phase_finish_response = dict(response)
        prompt_block = str(response.get("prompt_block", "")).strip()
        if prompt_block:
            self._update_worker_continuation(
                prompt_block=prompt_block,
                hitl_stage=str(response.get("next_phase", "")).strip() or None,
                status="running",
            )
        return response

    def _pending_worker_command(self) -> Optional[Dict[str, Any]]:
        from core.hitl_runtime_state import HitlRuntimeState

        return HitlRuntimeState(self.work_dir).pending_worker_command()

    def _cancelled_worker_command_result(
        self,
        result: Dict[str, Any],
        *,
        phase: str,
        worker_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Turn a cancelled manager request into a non-replaceable worker failure."""
        pending = self._pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") != "cancelled":
            return None
        self._clear_worker_continuation()
        reason = str(pending.get("cancellation_reason", "")).strip()
        manager_backend_failure = (
            str(pending.get("cancellation_kind", "")).strip() == "manager_backend_failure"
            or "bounded retry budget" in reason
        )
        return {
            **result,
            "success": False,
            "approved": False,
            "replacement": False,
            "hitl": True,
            "phase": phase,
            "hitl_terminal_failure": manager_backend_failure,
            "manager_backend_failure": manager_backend_failure,
            "error": reason
            or (
                f"{worker_name} cannot continue because runtime cancelled its held "
                "HITL manager request."
            ),
        }

    @staticmethod
    def _validate_runtime_scoring_failure(data: Dict[str, Any]) -> Dict[str, Any]:
        if str(data.get("status", "")).strip() != "feedback":
            raise HitlValidationError("A runtime scoring failure requires status='feedback'.")
        return {
            "status": "feedback",
            "context": _require_text(
                data.get("context"),
                "context",
                "Runtime scoring failure",
            ),
            "manager_feedback": _require_text(
                data.get("manager_feedback"),
                "manager_feedback",
                "Runtime scoring failure",
            ),
        }

    def _run_protected_scoring_handler(
        self,
        handler: Callable[[Dict[str, Any]], None],
        approval: Dict[str, Any],
        *,
        finalize_failure: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        """Run one scoring handoff without stranding its held worker request."""
        try:
            handler(approval)
        except Exception as exc:
            pending = self._pending_worker_command()
            if isinstance(pending, dict) and pending.get("status") == "cancelled":
                return
            try:
                self.manager.resume_worker_request(
                    prompt=_load_hitl_template(
                        "manager_runtime_scoring_failure.txt",
                        error=str(exc),
                    ),
                    validate=self._validate_runtime_scoring_failure,
                    finalize=finalize_failure,
                    manager_review_kind="scoring_failure",
                )
            except Exception:
                pending = self._pending_worker_command()
                if isinstance(pending, dict) and pending.get("status") == "cancelled":
                    return
                raise

    def _finalize_resumed_scoring_failure(
        self,
        review: Dict[str, Any],
        *,
        pending: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Rebuild the normal repair response when the original finish stack is gone."""
        hitl_stage = _require_text(
            pending.get("hitl_stage"),
            "hitl_stage",
            "Resumed runtime scoring failure",
        )
        if hitl_stage not in {"execution", "review"}:
            raise HitlValidationError(
                f"Runtime scoring failure cannot resume from HITL stage {hitl_stage!r}."
            )
        summary = _require_text(
            pending.get("finish_summary"),
            "finish_summary",
            "Resumed runtime scoring failure",
        )
        related_artifacts = _as_related_artifacts(pending.get("related_artifacts"))
        feedback = _require_text(
            review.get("manager_feedback"),
            "manager_feedback",
            "Resumed runtime scoring failure",
        )
        record = self.log.append(
            self._finish_review_record(
                hitl_stage="review",
                summary=summary,
                related_artifacts=related_artifacts,
                review=review,
                decision="O2",
                raised=True,
                manager_feedback=feedback,
            ),
            idempotent=True,
        )
        return self.scoring_repair_response(
            context=_require_text(
                review.get("context"),
                "context",
                "Resumed runtime scoring failure",
            ),
            manager_feedback=feedback,
            record=record,
        )

    def _resume_pending_scoring_handler(
        self,
        *,
        request_key: str,
        pending: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Reconnect one held command to its persisted scoring lifecycle."""
        handler = self._tool_context.get("scoring_handler")
        if not callable(handler):
            raise HitlValidationError(
                "Runtime resumed a scoring handoff without its scoring handler. "
                "Keep the workspace unchanged and retry after the HITL controller restarts recovery."
            )
        record = self._complete_pending_scoring_approval(
            request_key=request_key,
            pending=pending,
        )
        approval = {
            "status": "approved_for_scoring",
            "context": str(pending.get("scoring_context", "")).strip(),
            "scoring_review_idea_id": str(record["idea_id"]),
        }
        if request_key not in self._started_scoring_requests:
            self._started_scoring_requests.add(request_key)

            def finalize_failure(review: Dict[str, Any]) -> Dict[str, Any]:
                return self._finalize_resumed_scoring_failure(
                    review,
                    pending=pending,
                )

            threading.Thread(
                target=self._run_protected_scoring_handler,
                args=(handler, approval),
                kwargs={"finalize_failure": finalize_failure},
                daemon=True,
                name="neurico-hitl-resumed-scoring",
            ).start()
        return self.manager.wait_for_worker_request(request_key)

    def resume_pending_worker_command(self) -> Dict[str, Any]:
        """Reconnect a replacement worker to the one runtime-held command.

        The worker provides no workflow data here. Runtime reuses the validated
        request it persisted before the earlier worker process disappeared.
        """
        from core.hitl_runtime_state import HitlRuntimeState

        pending = HitlRuntimeState(self.work_dir).pending_worker_command()
        if not isinstance(pending, dict):
            raise HitlValidationError(
                "HITL_ERROR no_pending_worker_request\n"
                "There is no unresolved runtime worker request to resume. Continue with the current phase instructions."
            )
        request_key = str(pending.get("request_key", "")).strip()
        if not request_key:
            raise HitlValidationError("Pending HITL worker request has no request key.")
        kind = str(pending.get("kind", "")).strip()
        if pending.get("status") == "resolved":
            response = pending.get("response")
            if not isinstance(response, dict):
                raise HitlValidationError("Resolved HITL worker request has no runtime response.")
            if (
                kind == "phase_finish"
                and str(response.get("status", "")).strip() == "feedback"
                and not str(response.get("feedback", "")).strip()
            ):
                return self._normalize_phase_finish_feedback(
                    request_key=request_key,
                    hitl_stage=_require_text(
                        pending.get("hitl_stage"),
                        "hitl_stage",
                        "Resolved HITL phase-finish request",
                    ),
                    plan_fingerprint=str(pending.get("plan_fingerprint", "")).strip(),
                    workspace_fingerprint=str(
                        pending.get("workspace_fingerprint", "")
                    ).strip(),
                    summary=str(pending.get("finish_summary", "")).strip(),
                    related_artifacts=_as_related_artifacts(
                        pending.get("related_artifacts")
                    ),
                    review=response,
                    record=response.get("record"),
                )
            return dict(response)
        if kind == "phase_finish":
            from core.hitl_runtime_state import MANAGER_REVIEW_FINALIZERS

            manager_review_kind = str(pending.get("manager_review_kind", "")).strip()
            if manager_review_kind and manager_review_kind not in MANAGER_REVIEW_FINALIZERS:
                raise HitlValidationError(
                    f"Pending HITL worker request has an unsupported manager review kind: "
                    f"{manager_review_kind}."
                )
            if manager_review_kind:
                expected_finalizer = MANAGER_REVIEW_FINALIZERS[manager_review_kind]
                manager_finalizer = str(pending.get("manager_finalizer", "")).strip()
                if manager_finalizer != expected_finalizer:
                    raise HitlValidationError(
                        f"Pending {manager_review_kind} review requires {expected_finalizer}, "
                        f"not {manager_finalizer or '<missing>'}."
                    )
            if pending.get("status") in {"scoring_approval_pending", "scoring"} or (
                pending.get("status") == "pending" and manager_review_kind
            ):
                return self._resume_pending_scoring_handler(
                    request_key=request_key,
                    pending=pending,
                )
            return self.finish_tool_phase(
                {
                    "summary": pending.get("finish_summary", ""),
                    "related_artifacts": pending.get("related_artifacts", []),
                }
            )
        if kind == "raised_idea":
            raised_idea = pending.get("raised_idea")
            if not isinstance(raised_idea, dict):
                raise HitlValidationError("Pending raised idea request has no worker payload.")
            return self.resolve_tool_raised_payload(raised_idea)
        if kind == "proposal":
            proposal_payload = pending.get("proposal_payload")
            if not isinstance(proposal_payload, dict):
                raise HitlValidationError(
                    "Pending proposal request has no submitted proposal payload."
                )
            return self.submit_proposal_payload(proposal_payload)
        raise HitlValidationError(
            f"Unsupported pending HITL worker request kind: {kind or '<missing>'}."
        )

    def _complete_pending_scoring_approval(
        self,
        *,
        request_key: str,
        pending: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Commit a persisted scoring approval into the idea log exactly once."""
        review = pending.get("scoring_review")
        if not isinstance(review, dict):
            existing_id = str(pending.get("scoring_review_idea_id", "")).strip()
            if existing_id:
                record = next(
                    (
                        candidate
                        for candidate in reversed(self.log.records())
                        if candidate.get("idea_id") == existing_id
                    ),
                    None,
                )
                if isinstance(record, dict):
                    return record
            raise HitlValidationError(
                "Runtime cannot resume scoring because its persisted manager approval is incomplete. "
                "Keep the workspace unchanged and retry after HITL recovery."
            )
        hitl_stage = _require_text(
            pending.get("hitl_stage"), "hitl_stage", "Persisted scoring approval"
        )
        summary = _require_text(
            pending.get("finish_summary"), "finish_summary", "Persisted scoring approval"
        )
        related_artifacts = _as_related_artifacts(pending.get("related_artifacts"))
        record = self.log.append(
            self._finish_review_record(
                hitl_stage=hitl_stage,
                summary=summary,
                related_artifacts=related_artifacts,
                review=review,
                decision="O1",
                raised=False,
                manager_feedback="",
            ),
            idempotent=True,
        )
        from core.hitl_runtime_state import HitlRuntimeState

        HitlRuntimeState(self.work_dir).complete_scoring_handoff(
            request_key,
            scoring_review_idea_id=str(record["idea_id"]),
        )
        return record

    def _finish_tool_phase_locked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._tool_lock:
            pending = self._pending_worker_command()
            if (
                isinstance(pending, dict)
                and pending.get("kind") == "phase_finish"
                and pending.get("status") == "cancelled"
            ):
                from core.hitl_runtime_state import HitlRuntimeStateError

                reason = str(pending.get("cancellation_reason", "")).strip()
                raise HitlRuntimeStateError(
                    "Runtime cancelled the held worker command while rolling back its failed attempt."
                    + (f" {reason}" if reason else "")
                )
            terminal_response = self._terminal_phase_finish_response()
            if terminal_response is not None:
                return terminal_response
            summary = _require_text(payload.get("summary"), "summary", "HITL phase finish")
            related_artifacts = _as_related_artifacts(payload.get("related_artifacts"))
            hitl_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
            plan_fingerprint = self._current_plan_fingerprint()
            from core.hitl_workspace_guard import HitlWorkspaceWriteGuard

            workspace_fingerprint = HitlWorkspaceWriteGuard.public_fingerprint(self.work_dir)
            request_key = self._phase_finish_request_key_for(
                hitl_stage=hitl_stage,
                plan_fingerprint=plan_fingerprint,
                workspace_fingerprint=workspace_fingerprint,
                summary=summary,
                related_artifacts=related_artifacts,
            )
            prior_response = self._phase_finish_response_for_retry(
                request_key,
                hitl_stage=hitl_stage,
                plan_fingerprint=plan_fingerprint,
                workspace_fingerprint=workspace_fingerprint,
                summary=summary,
                related_artifacts=related_artifacts,
            )
            if prior_response is not None:
                return prior_response
            validator = (
                self._tool_context.get("plan_finish_validator")
                if hitl_stage == "plan"
                else self._tool_context.get("phase_finish_validator")
            )
            if callable(validator):
                validation = validator()
                if not bool(validation.get("valid")):
                    issues = validation.get("issues", [])
                    if not isinstance(issues, list):
                        issues = [str(issues)]
                    issue_text = "\n".join(
                        f"- {str(issue)}" for issue in issues if str(issue).strip()
                    )
                    next_stage = "plan" if hitl_stage == "plan" else "review"
                    feedback = (
                        "Runtime validation found work outside the allowed HITL boundary. "
                        "Correct only these issues, preserve completed permitted work, then call "
                        "hitl-finish-phase again:\n"
                        + (issue_text or "- Recheck the active HITL workspace boundary.")
                    )
                    self._tool_context["hitl_stage"] = next_stage
                    self.current_hitl_stage = next_stage
                    self._phase_finish_result = {
                        "called": True,
                        "status": "feedback",
                        "hitl_stage": next_stage,
                        "plan_fingerprint": plan_fingerprint,
                        "workspace_fingerprint": workspace_fingerprint,
                        "summary": summary,
                        "related_artifacts": related_artifacts,
                        "manager_feedback": feedback,
                        "context": "Runtime validation rejected the phase boundary before manager review.",
                        "next_phase": next_stage,
                        "final": False,
                    }
                    prompt_block = self.compose_worker_prompt(
                        hitl_stage=next_stage,
                        phase_prompt=(
                            self.plan_revision_prompt_block(feedback)
                            if next_stage == "plan"
                            else self.review_prompt_block(feedback)
                        ),
                    )
                    return self._remember_phase_finish_response(
                        request_key,
                        {
                            "status": "feedback",
                            "feedback": feedback,
                            "next_phase": next_stage,
                            "instruction": (
                                "Correct the listed runtime validation issues in this same worker "
                                "session, then call hitl-finish-phase again."
                            ),
                            "prompt_block": prompt_block,
                        },
                    )
            if hitl_stage == "plan" and not self._latest_worker_plan_idea_id():
                raise HitlValidationError(
                    "HITL_ERROR plan_requires_c_level_idea\n"
                    "Before requesting plan review, report at least one material C-level plan "
                    "evidence or decision with `hitl-report-idea`.\n"
                    "Use `hitl-view-ideas` if prior ideas inform it, then retry hitl-finish-phase."
                )
            finalized: Dict[str, Dict[str, Any]] = {}

            def persist_phase_review(review: Dict[str, Any]) -> Dict[str, Any]:
                status = str(review.get("status", "")).strip()
                human_resolved_plan = bool(
                    hitl_stage == "plan"
                    and self._tool_context.get("requires_human_approval")
                    and str(review.get("human_feedback", "")).strip()
                )
                if status == "feedback" and human_resolved_plan:
                    finalized["record"] = self._finish_human_plan_admission_from_review(review)[
                        "record"
                    ]
                elif status == "feedback":
                    feedback = _require_text(
                        review.get("manager_feedback"),
                        "manager_feedback",
                        "Manager phase finish review with status='feedback'",
                    )
                    next_stage = "review" if hitl_stage == "execution" else hitl_stage
                    finalized["record"] = self.log.append(
                        self._finish_review_record(
                            hitl_stage=next_stage,
                            summary=summary,
                            related_artifacts=related_artifacts,
                            review=review,
                            decision="O2",
                            raised=True,
                            manager_feedback=feedback,
                        ),
                        idempotent=True,
                    )
                elif (
                    status == "approved"
                    and hitl_stage == "plan"
                    and self._tool_context.get("requires_human_approval")
                ):
                    finalized["record"] = self._finish_human_plan_admission_from_review(review)[
                        "record"
                    ]
                elif status == "approved":
                    finalized["record"] = self.log.append(
                        self._finish_review_record(
                            hitl_stage=hitl_stage,
                            summary=summary,
                            related_artifacts=related_artifacts,
                            review=review,
                            decision="O1",
                            raised=False,
                            manager_feedback="",
                        ),
                        idempotent=True,
                    )
                else:
                    raise HitlValidationError(
                        "Manager phase finish review must return status 'approved' or 'feedback'."
                    )
                return review

            def persist_scoring_approval(review: Dict[str, Any]) -> Dict[str, Any]:
                handler = self._tool_context.get("scoring_handler")
                if not callable(handler):
                    raise HitlValidationError(
                        "AutoResearch HITL scoring approval has no runtime scoring handler. "
                        "Preserve this review and retry approve_for_scoring after runtime recovers it."
                    )
                from core.hitl_runtime_state import HitlRuntimeState

                state = HitlRuntimeState(self.work_dir)
                pending = state.pending_worker_command()
                if not isinstance(pending, dict) or not str(pending.get("request_key", "")).strip():
                    raise HitlValidationError(
                        "AutoResearch scoring approval has no held phase-finish request. "
                        "Keep the workspace unchanged and retry approval after runtime recovery."
                    )
                request_key = str(pending["request_key"])
                if pending.get("status") != "scoring_approval_pending":
                    raise HitlValidationError(
                        "AutoResearch scoring approval is missing its persisted handoff state. "
                        "Keep the workspace unchanged and retry approval."
                    )
                record = self._complete_pending_scoring_approval(
                    request_key=request_key,
                    pending=pending,
                )
                finalized["record"] = record
                payload = {**review, "scoring_review_idea_id": record["idea_id"]}

                threading.Thread(
                    target=self._run_protected_scoring_handler,
                    args=(handler, payload),
                    kwargs={"finalize_failure": persist_phase_review},
                    daemon=True,
                    name="neurico-hitl-scoring",
                ).start()
                self._started_scoring_requests.add(request_key)
                return payload

            review = self.manager.review_phase_finish(
                pipeline_stage=self.pipeline_stage,
                hitl_stage=hitl_stage,
                plan_text=self._read_optional(self.paths.plan_path),
                plan_fingerprint=plan_fingerprint,
                workspace_fingerprint=workspace_fingerprint,
                finish_summary=summary,
                related_artifacts=related_artifacts,
                request_key=request_key,
                requires_human_approval=bool(self._tool_context.get("requires_human_approval")),
                allow_scoring_approval=bool(self._tool_context.get("allow_scoring_approval"))
                and hitl_stage in {"execution", "review"},
                scoring_handoff_context=dict(self._tool_context.get("provenance") or {}),
                verifier_report=self._durable_conformance_report(request_key, hitl_stage),
                on_finalize=persist_phase_review,
                on_scoring_approval=persist_scoring_approval,
                hitl_mode=self.hitl_mode,
            )
            if (
                self._phase_finish_request_key == request_key
                and isinstance(self._phase_finish_response, dict)
            ):
                return dict(self._phase_finish_response)
            status = str(review.get("status", "")).strip()
            if status == "feedback":
                logged = finalized.get("record")
                if not logged:
                    raise RuntimeError("Manager feedback was finalized without an audit record.")
                return self._normalize_phase_finish_feedback(
                    request_key=request_key,
                    hitl_stage=hitl_stage,
                    plan_fingerprint=plan_fingerprint,
                    workspace_fingerprint=workspace_fingerprint,
                    summary=summary,
                    related_artifacts=related_artifacts,
                    review=review,
                    record=logged,
                )

            if status != "approved":
                raise HitlValidationError(
                    "Manager phase finish review must return status 'approved' or 'feedback'."
                )

            if hitl_stage == "plan" and self._tool_context.get("requires_human_approval"):
                logged = finalized.get("record")
                if not logged:
                    raise RuntimeError("Human plan approval was finalized without an audit record.")
            else:
                logged = finalized.get("record")
                if not logged:
                    raise RuntimeError("Manager approval was finalized without an audit record.")

            next_phase = "complete"
            final = True
            instruction = "Reviewer approved this stage. Stop this worker session now."
            prompt_block = ""
            if hitl_stage == "plan":
                from core.hitl_runtime_state import HitlRuntimeState

                HitlRuntimeState(self.work_dir).mark_plan_approved(
                    pipeline_stage=self.pipeline_stage,
                    plan_fingerprint=plan_fingerprint,
                    approval_level=(
                        "A"
                        if bool(self._tool_context.get("requires_human_approval"))
                        else "B"
                    ),
                )
                next_phase = "execution"
                final = False
                instruction = (
                    "Plan approved. Do not stop. Continue into execution in this "
                    "same worker session using the execution instructions below."
                )
                prompt_block = self.compose_worker_prompt(
                    hitl_stage="execution",
                    phase_prompt=self.execution_prompt_block(mode="execute"),
                )
                self.transition_worker_stage("execution", prompt_block=prompt_block)
            else:
                self._tool_context["hitl_stage"] = "complete"
                self.current_hitl_stage = "complete"

            self._phase_finish_result = {
                "called": True,
                "status": "approved",
                "hitl_stage": hitl_stage,
                "plan_fingerprint": plan_fingerprint,
                "workspace_fingerprint": workspace_fingerprint,
                "summary": summary,
                "related_artifacts": related_artifacts,
                "manager_feedback": "",
                "context": str(review.get("context", "")),
                "record": logged,
                "next_phase": next_phase,
                "final": final,
                **(
                    {"scored_candidate": dict(self._tool_context["scored_candidate"])}
                    if isinstance(self._tool_context.get("scored_candidate"), dict)
                    else {}
                ),
                **(
                    {"scorer_result": dict(self._tool_context["scorer_result"])}
                    if isinstance(self._tool_context.get("scorer_result"), dict)
                    else {}
                ),
            }
            response = {
                "status": "approved",
                "feedback": "",
                "next_phase": next_phase,
                "instruction": instruction,
                "prompt_block": prompt_block,
                "final": final,
                "record": logged,
            }
            if isinstance(self._tool_context.get("scored_candidate"), dict):
                response["scored_candidate"] = dict(self._tool_context["scored_candidate"])
            if isinstance(self._tool_context.get("scorer_result"), dict):
                response["scorer_result"] = dict(self._tool_context["scorer_result"])
            return self._remember_phase_finish_response(request_key, response)

    def phase_finish_result(self) -> Optional[Dict[str, Any]]:
        return dict(self._phase_finish_result) if self._phase_finish_result else None

    def finish_was_approved(self) -> bool:
        return bool(
            self._phase_finish_result and self._phase_finish_result.get("status") == "approved"
        )

    def handle_worker_exit_after_finish(
        self,
        result: Dict[str, Any],
        *,
        phase: str,
        worker_name: str,
    ) -> Dict[str, Any]:
        """Interpret a provider return and request one runtime-owned replacement.

        The normal protocol remains one worker session. This recovery path only
        activates after that external session exits unexpectedly. It preserves the
        live tool-server and request state and gives a continuation worker the runtime
        prompt that the lost worker should have continued from.
        """
        self._join_live_worker_request_handler(expected_kind="phase_finish")
        cancelled = self._cancelled_worker_command_result(
            result,
            phase=phase,
            worker_name=worker_name,
        )
        if cancelled is not None:
            return cancelled
        finish = self.phase_finish_result()
        resolved = self.resolved_worker_response()
        if resolved and (
            bool(resolved.get("final"))
            or isinstance(resolved.get("scored_candidate"), dict)
            or isinstance(resolved.get("scorer_result"), dict)
        ):
            self._clear_worker_continuation()
            return {
                "approved": True,
                "worker_exit_warning": (
                    f"{worker_name} exited after runtime finalized the held worker request. "
                    "Runtime retained the finalized state because no worker action remained."
                    if not result.get("success")
                    else ""
                ),
            }
        if finish and finish.get("status") == "approved" and finish.get("final"):
            self._clear_worker_continuation()
            return {
                "approved": True,
                "worker_exit_warning": (
                    (
                        f"{worker_name} exited with a provider error after final HITL approval. "
                        "Runtime retained the already-approved state because no worker action remained."
                    )
                    if not result.get("success")
                    else ""
                ),
            }

        pending_replacement = self._pending_worker_request_replacement(
            phase=phase,
            worker_name=worker_name,
        )
        if pending_replacement is not None:
            return pending_replacement
        if result.get("background_processes_terminated") and finish is None and resolved is None:
            return {
                **result,
                "approved": False,
                "success": False,
                "hitl": True,
                "phase": phase,
                "error": (
                    f"{worker_name} left background processes without a durable "
                    "HITL result or resumable request. Runtime terminated them and "
                    "will not accept or score this workspace."
                ),
            }

        continuation = self.worker_continuation()
        if continuation is not None:
            prompt_block = str(
                (finish or {}).get("prompt_block") or continuation.get("prompt_block", "")
            ).strip()
            if prompt_block:
                self._update_worker_continuation(
                    prompt_block=prompt_block,
                    hitl_stage=str(
                        (finish or {}).get("next_phase") or continuation.get("hitl_stage", "")
                    ).strip()
                    or None,
                    status="replacement_pending",
                )
                from core.hitl_runtime_state import HitlRuntimeState

                HitlRuntimeState(self.work_dir).mark_worker_replacement()
                return {
                    "approved": False,
                    "replacement": True,
                    "prompt_block": prompt_block,
                    "phase": phase,
                    "worker_exit_warning": (
                        f"{worker_name} exited before a final HITL result. Runtime will "
                        "launch a continuation worker from the preserved HITL state."
                    ),
                }

            error = (
                f"{worker_name} exited before final HITL approval, but runtime has no "
                "continuation prompt to launch safely."
            )
        else:
            if finish and finish.get("status") == "feedback":
                error = (
                    "HITL worker exited after reviewer feedback instead of "
                    "continuing in the same session and calling hitl-finish-phase again."
                )
            elif not result.get("success"):
                error = (
                    f"{worker_name} failed before approved HITL finish. Raised HITL "
                    "ideas must be resolved through hitl-raise-idea inside "
                    "the same worker session."
                )
            else:
                error = (
                    f"{worker_name} exited during {phase} without an approved "
                    "hitl-finish-phase result. HITL phase completion must be "
                    "runtime-mediated through hitl-finish-phase."
                )
        return {**result, "success": False, "hitl": True, "phase": phase, "error": error}

    def _finish_feedback_prompt_block(self, *, hitl_stage: str, feedback: str) -> str:
        if hitl_stage == "plan":
            phase_prompt = self.plan_revision_prompt_block(feedback)
        else:
            phase_prompt = self.review_prompt_block(feedback)
        return self.compose_worker_prompt(hitl_stage=hitl_stage, phase_prompt=phase_prompt)

    def _normalize_phase_finish_feedback(
        self,
        *,
        request_key: str,
        hitl_stage: str,
        plan_fingerprint: str,
        workspace_fingerprint: str,
        summary: str,
        related_artifacts: List[Dict[str, str]],
        review: Dict[str, Any],
        record: Any = None,
    ) -> Dict[str, Any]:
        """Convert a manager phase review into the worker-facing continuation."""
        feedback = _require_text(
            review.get("manager_feedback"),
            "manager_feedback",
            "Manager phase finish review with status='feedback'",
        )
        human_resolved_plan = bool(
            hitl_stage == "plan" and str(review.get("human_feedback", "")).strip()
        )
        next_phase = "plan" if human_resolved_plan else (
            "review" if hitl_stage == "execution" else hitl_stage
        )
        prompt_block = self._finish_feedback_prompt_block(
            hitl_stage=next_phase,
            feedback=feedback,
        )
        current_stage = str(
            self._tool_context.get("hitl_stage", self.current_hitl_stage)
        ).strip()
        if next_phase != current_stage:
            self.transition_worker_stage(next_phase, prompt_block=prompt_block)
        else:
            self._update_worker_continuation(
                prompt_block=prompt_block,
                hitl_stage=next_phase,
                status="running",
            )

        normalized_record = dict(record) if isinstance(record, dict) else None
        self._phase_finish_result = {
            "called": True,
            "status": "feedback",
            "hitl_stage": next_phase,
            "plan_fingerprint": plan_fingerprint,
            "workspace_fingerprint": workspace_fingerprint,
            "summary": summary,
            "related_artifacts": related_artifacts,
            "manager_feedback": feedback,
            "context": str(review.get("context", "")),
            "next_phase": next_phase,
            "final": False,
            **({"record": normalized_record} if normalized_record is not None else {}),
        }
        instruction = (
            "Apply this plan feedback, update the living plan, then "
            "call hitl-finish-phase again."
            if human_resolved_plan
            else (
                "Apply this feedback in the current phase, update the living "
                "plan/current artifacts, then call hitl-finish-phase again."
            )
        )
        response = {
            "status": "feedback",
            "feedback": feedback,
            "next_phase": next_phase,
            "instruction": instruction,
            "prompt_block": prompt_block,
            "final": False,
            **({"record": normalized_record} if normalized_record is not None else {}),
        }
        return self._remember_phase_finish_response(request_key, response)

    def _record_from_tool_payload(
        self,
        payload: Dict[str, Any],
        *,
        raised: bool,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise HitlValidationError("HITL tool payload must be a JSON object.")
        idea_type = _require_text(payload.get("idea_type"), "idea_type", "HITL tool idea")
        if idea_type not in {"decision", "evidence"}:
            raise HitlValidationError(f"Invalid HITL tool idea_type: {idea_type}")
        hitl_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
        actor = str(self._tool_context.get("actor", self.pipeline_stage))
        record: Dict[str, Any] = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": hitl_stage,
            "idea_type": idea_type,
            "idea_category": _validate_idea_category(
                idea_type,
                payload.get("idea_category"),
            ),
            "level": "C",
            "actor": actor,
            "premises": _with_runtime_premises(
                _normalize_premises(payload.get("premises")),
                self._tool_context.get("provenance"),
            ),
            "context": _require_text(payload.get("context"), "context", "HITL tool idea"),
            "related_artifacts": _as_related_artifacts(payload.get("related_artifacts")),
            "raised": raised,
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        if idea_type == "decision":
            record["decision_needed"] = _require_text(
                payload.get("decision_needed"),
                "decision_needed",
                "HITL decision idea",
            )
            record["options"] = payload.get("options")
            if raised:
                _validate_substantive_options(
                    record.get("options"),
                    error_prefix="Raised HITL decision idea",
                )
            else:
                _validate_substantive_options(
                    record.get("options"),
                    error_prefix="C-level HITL decision idea",
                )
                record["decision"] = _require_text(
                    payload.get("decision"),
                    "decision",
                    "C-level HITL decision idea",
                )
        else:
            record["evidence"] = _require_text(
                payload.get("evidence"),
                "evidence",
                "HITL evidence idea",
            )
        return record

    def _record_from_proposal_tool_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise HitlValidationError("HITL proposal tool payload must be a JSON object.")
        hitl_stage = str(self._tool_context.get("hitl_stage", self.current_hitl_stage))
        actor = str(self._tool_context.get("actor", self.pipeline_stage))
        if self.pipeline_stage != "experiment_runner" or hitl_stage != "proposal":
            raise HitlValidationError(
                "HITL_ERROR proposal_wrong_context\n"
                "`hitl-submit-proposal` can only be used during experiment_runner proposal generation.\n"
                "Continue with the command appropriate for the current HITL phase."
            )
        proposal_type = _require_text(
            payload.get("proposal_type"),
            "proposal_type",
            "HITL proposal idea",
        )
        if proposal_type not in PROPOSAL_KINDS:
            raise HitlValidationError(
                "HITL_ERROR invalid_proposal_type\n"
                "Proposal type must be exactly `exploitation` or `exploration`.\n"
                "Rerun `hitl-submit-proposal` with `--proposal-type exploitation` or `--proposal-type exploration`."
            )
        record: Dict[str, Any] = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": hitl_stage,
            "idea_type": "proposal",
            "proposal_type": proposal_type,
            "level": "C",
            "actor": actor,
            "premises": _normalize_premises(payload.get("premises")),
            "context": "AutoResearch proposer submitted the next experiment proposal.",
            "related_artifacts": [],
            "proposal": _require_text(payload.get("proposal"), "proposal", "HITL proposal idea"),
            "raised": False,
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        return record

    def _log_proposal_manager_review(
        self,
        *,
        proposal_record: Dict[str, Any],
        review: Dict[str, Any],
    ) -> Dict[str, Any]:
        options = _normalize_options(
            [
                "Approve proposal as legal.",
                "Reject illegal proposal and request a new proposal.",
            ]
        )
        legal = review["status"] != "rejected_illegal"
        record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": "proposal",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "level": "B",
            "actor": "manager",
            "premises": [proposal_record["idea_id"]],
            "context": str(
                review.get("context", "Manager reviewed AutoResearch proposal legality.")
            ).strip(),
            "related_artifacts": [],
            "decision_needed": (
                "Is this AutoResearch proposal legal for admission review?"
                if self.hitl_mode is HitlMode.AUTO
                else "Is this AutoResearch proposal legal to show to the human for approval?"
            ),
            "options": options,
            "decision": "O1" if legal else "O2",
            "manager_feedback": "" if legal else str(review["manager_feedback"]).strip(),
            "raised": False,
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        return self.log.append(record, idempotent=True)

    def _finalize_proposal_manager_admission(
        self,
        *,
        proposal_record: Dict[str, Any],
        manager_record: Dict[str, Any],
        review: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Record Auto HITL's manager-owned scientific admission decision."""

        status = str(review.get("status", "")).strip()
        if status == "approved":
            approved = True
            manager_feedback = ""
        elif status == "feedback":
            approved = False
            manager_feedback = str(review["manager_feedback"]).strip()
        else:
            raise RuntimeError(
                "Validated Auto HITL proposal admission reached finalization with an "
                f"unexpected status: {status or '<empty>'}."
            )
        record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": "proposal",
            "idea_type": "decision",
            "idea_category": "method_choice",
            "level": "B",
            "actor": "manager",
            "premises": [proposal_record["idea_id"], manager_record["idea_id"]],
            "context": str(
                review.get("context", "Manager reviewed AutoResearch proposal admission.")
            ).strip(),
            "related_artifacts": [],
            "decision_needed": (
                "Should this AutoResearch proposal be admitted to experiment execution?"
            ),
            "options": _normalize_options(["Approve proposal.", "Request a new proposal."]),
            "decision": "O1" if approved else "O2",
            "manager_feedback": manager_feedback,
            "raised": False,
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        admission_record = self.log.append(record, idempotent=True)
        if approved:
            return {
                "status": "approved",
                "instruction": "The proposal is admitted. Stop proposal generation now.",
                "proposal_idea_id": proposal_record["idea_id"],
                "manager_idea_id": manager_record["idea_id"],
                "manager_admission_idea_id": admission_record["idea_id"],
                "proposal": proposal_record["proposal"],
            }
        return {
            "status": "feedback",
            "feedback": manager_feedback,
            "instruction": (
                "This proposal is rejected. Create a new proposal using this feedback, "
                "then submit the new proposal with `hitl-submit-proposal` in this same session."
            ),
            "proposal_idea_id": proposal_record["idea_id"],
            "manager_idea_id": manager_record["idea_id"],
            "manager_admission_idea_id": admission_record["idea_id"],
        }

    def _finalize_proposal_human_admission(
        self,
        *,
        proposal_record: Dict[str, Any],
        manager_record: Dict[str, Any],
        review: Dict[str, Any],
    ) -> Dict[str, Any]:
        options = _normalize_options(["Approve proposal.", "Provide feedback."])
        human_feedback = _require_text(
            review.get("human_feedback"),
            "human_feedback",
            "Human-resolved AutoResearch proposal admission",
        )
        human_decision = _resolve_human_decision(human_feedback, options)
        decision = human_decision["decision"]
        approved = decision == "O1"
        if not approved and _is_feedback_placeholder(human_feedback):
            raise RuntimeError(
                "HITL proposal feedback must contain concrete instructions for the next proposal."
            )
        expected_status = "approved" if approved else "feedback"
        if review.get("status") != expected_status:
            raise HitlValidationError(
                "Manager proposal admission status does not match the human response returned "
                "through ask_human."
            )
        manager_feedback = ""
        if not approved:
            manager_feedback = _require_text(
                review.get("manager_feedback"),
                "manager_feedback",
                "Manager translation of human proposal feedback",
            )
        record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": "proposal",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "level": "A",
            "actor": "human",
            "premises": [proposal_record["idea_id"], manager_record["idea_id"]],
            "context": str(
                review.get("context", "Human reviewed a legal AutoResearch proposal.")
            ).strip(),
            "related_artifacts": [],
            "decision_needed": "Should this AutoResearch proposal be admitted to experiment execution?",
            "options": options,
            "decision": decision,
            "human_feedback": human_feedback,
            "manager_feedback": manager_feedback,
            "raised": True,
            "manager_escalation_reason": str(review["manager_escalation_reason"]).strip(),
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        human_record = self.log.append(record, idempotent=True)
        if approved:
            return {
                "status": "approved",
                "instruction": "The proposal is admitted. Stop proposal generation now.",
                "proposal_idea_id": proposal_record["idea_id"],
                "manager_idea_id": manager_record["idea_id"],
                "human_idea_id": human_record["idea_id"],
                "proposal": proposal_record["proposal"],
            }
        return {
            "status": "feedback",
            "feedback": manager_feedback,
            "human_feedback": human_feedback,
            "instruction": (
                "This proposal is rejected. Create a new proposal using this feedback, "
                "then submit the new proposal with `hitl-submit-proposal` in this same session."
            ),
            "proposal_idea_id": proposal_record["idea_id"],
            "manager_idea_id": manager_record["idea_id"],
            "human_idea_id": human_record["idea_id"],
        }

    def _finish_review_record(
        self,
        *,
        hitl_stage: str,
        summary: str,
        related_artifacts: List[Dict[str, str]],
        review: Dict[str, Any],
        decision: str,
        raised: bool,
        manager_feedback: str,
    ) -> Dict[str, Any]:
        record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": hitl_stage,
            "level": "B",
            "actor": "manager",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "context": str(
                review.get(
                    "context",
                    f"Manager reviewed a {hitl_stage} finish request.",
                )
            ),
            "premises": [self._manager_phase_premise_id(hitl_stage)],
            "decision_needed": "Is this HITL phase ready to accept?",
            "options": ["Approve phase.", "Return feedback."],
            "decision": decision,
            "manager_feedback": manager_feedback,
            "raised": raised,
            "worker_context": summary,
            "related_artifacts": related_artifacts or self._plan_artifact(),
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        return record

    def _finish_human_plan_admission_from_review(self, review: Dict[str, Any]) -> Dict[str, Any]:
        """Log a manager-mediated human plan decision from one finish request."""
        manager_ready_record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": "plan",
            "level": "B",
            "actor": "manager",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "context": str(review.get("context", "Manager reviewed the plan.")),
            "premises": [self._manager_phase_premise_id("plan")],
            "decision_needed": "Is this HITL plan ready for human approval?",
            "options": [
                "Accept current plan as ready for human approval.",
                "Return feedback before human approval.",
            ],
            "decision": "O1",
            "raised": False,
            "manager_feedback": "",
            "related_artifacts": self._plan_artifact(),
        }
        _apply_runtime_provenance(manager_ready_record, self._tool_context.get("provenance"))
        manager_ready_record = self.log.append(manager_ready_record, idempotent=True)

        plan_options = _normalize_options(["Approve plan.", "Provide feedback."])
        human_feedback = _require_text(
            review.get("human_feedback"),
            "human_feedback",
            "Human-resolved HITL plan finish",
        )
        human_decision = _resolve_human_decision(human_feedback, plan_options)
        decision = human_decision["decision"]
        approved = decision == "O1"
        manager_feedback = (
            ""
            if approved
            else _require_text(
                review.get("manager_feedback"),
                "manager_feedback",
                "Manager translation of human plan feedback",
            )
        )
        record = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": "plan",
            "level": "A",
            "actor": "human",
            "idea_type": "decision",
            "idea_category": "artifact_boundary_choice",
            "context": str(review.get("context", "Manager presented the plan for approval.")),
            "premises": [manager_ready_record["idea_id"]],
            "decision_needed": "Should this HITL plan be approved for execution?",
            "options": plan_options,
            "decision": decision,
            "raised": True,
            "human_feedback": human_feedback,
            "manager_escalation_reason": _require_text(
                review.get("manager_escalation_reason"),
                "manager_escalation_reason",
                "Human-resolved HITL plan finish",
            ),
            "manager_feedback": manager_feedback,
            "related_artifacts": self._plan_artifact(),
        }
        _apply_runtime_provenance(record, self._tool_context.get("provenance"))
        logged = self.log.append(record, idempotent=True)
        return {
            "approved": approved,
            "feedback": manager_feedback or human_feedback,
            "record": logged,
        }

    def _latest_worker_plan_idea_id(self) -> str:
        expected_provenance = _runtime_provenance(self._tool_context.get("provenance"))
        expected_actor = str(self._tool_context.get("actor", self.pipeline_stage)).strip()
        for record in reversed(self.log.records()):
            if (
                record.get("pipeline_stage") == self.pipeline_stage
                and record.get("hitl_stage") == "plan"
                and record.get("level") == "C"
                and record.get("actor") == expected_actor
                and all(
                    str(record.get(key, "")) == value for key, value in expected_provenance.items()
                )
            ):
                return str(record.get("idea_id", "")).strip()
        return ""

    def _manager_phase_premise_id(self, hitl_stage: str) -> str:
        if hitl_stage == "plan":
            premise = self._latest_worker_plan_idea_id()
            if premise:
                return premise
        expected_provenance = _runtime_provenance(self._tool_context.get("provenance"))
        for record in reversed(self.log.records()):
            idea_id = str(record.get("idea_id", "")).strip()
            if (
                idea_id
                and record.get("pipeline_stage") == self.pipeline_stage
                and all(
                    str(record.get(key, "")) == value for key, value in expected_provenance.items()
                )
            ):
                return idea_id
        raise HitlValidationError(
            "A manager decision requires an earlier finalized HITL idea premise from "
            "this pipeline stage and runtime invocation."
        )

    def _start_idea_tool_server(self) -> None:
        runtime = self
        token = secrets.token_urlsafe(24)
        max_request_bytes = 1_000_000

        class ToolHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:
                try:
                    if self.headers.get("Authorization", "") != f"Bearer {token}":
                        self._send_json(403, {"error": "Invalid HITL tool token."})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > max_request_bytes:
                        self._send_json(
                            413,
                            {
                                "error": (
                                    "HITL_ERROR request_too_large\n"
                                    "This HITL command payload exceeds the 1 MB runtime limit. "
                                    "Provide the required information concisely and retry the same command."
                                )
                            },
                        )
                        return
                    raw = self.rfile.read(length)
                    payload = json.loads(raw.decode("utf-8") or "{}")
                    if self.path == "/idea/report":
                        runtime._require_worker_command("hitl-report-idea")
                        record = runtime.log_reported_payload(payload)
                        self._send_json(
                            200,
                            {"ok": True, "idea_id": record["idea_id"]},
                        )
                        return
                    if self.path == "/proposal/submit":
                        runtime._require_worker_command("hitl-submit-proposal")
                        result = runtime.submit_proposal_payload(payload)
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "status": result.get("status"),
                                "proposal_idea_id": result.get("proposal_idea_id", ""),
                                "feedback": result.get("feedback", ""),
                                "instruction": result.get("instruction", ""),
                            },
                        )
                        return
                    if self.path == "/idea/raise":
                        runtime._require_worker_command("hitl-raise-idea")
                        result = runtime.resolve_tool_raised_payload(payload)
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "idea_id": result.get("idea_id"),
                                "decision": result.get("decision", ""),
                                "feedback": result.get("feedback", ""),
                            },
                        )
                        return
                    if self.path == "/idea/view":
                        runtime._require_worker_command("hitl-view-ideas")
                        result = runtime.view_ideas_for_tool(payload)
                        self._send_json(200, {"ok": True, "text": result["text"]})
                        return
                    if self.path == "/frontier/current":
                        runtime._require_worker_command("view_current_frontier")
                        result = runtime.view_current_frontier_for_tool()
                        self._send_json(200, {"ok": True, "text": result["text"]})
                        return
                    if self.path == "/phase/finish":
                        runtime._require_worker_command("hitl-finish-phase")
                        result = runtime.finish_tool_phase(payload)
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "status": result.get("status"),
                                "feedback": result.get("feedback", ""),
                                "next_phase": result.get("next_phase", ""),
                                "instruction": result.get("instruction", ""),
                                "prompt_block": result.get("prompt_block", ""),
                                "final": bool(result.get("final")),
                            },
                        )
                        return
                    if self.path == "/worker/resume":
                        runtime._require_worker_command("hitl-resume-worker-request")
                        result = runtime.resume_pending_worker_command()
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "status": result.get("status"),
                                "feedback": result.get("feedback", ""),
                                "next_phase": result.get("next_phase", ""),
                                "instruction": result.get("instruction", ""),
                                "prompt_block": result.get("prompt_block", ""),
                                "final": bool(result.get("final")),
                            },
                        )
                        return
                    self._send_json(404, {"error": f"Unknown HITL endpoint: {self.path}"})
                except HitlActiveWorkerRequestError as exc:
                    self._send_json(
                        409,
                        {"error": str(exc)},
                    )
                except HitlValidationError as exc:
                    self._send_json(
                        400,
                        {
                            "error": (
                                "HITL_ERROR command_rejected\n"
                                f"{exc}\n"
                                "Correct the command arguments and run the same command again "
                                "in this worker session."
                            )
                        },
                    )
                except Exception:
                    LOGGER.exception("HITL runtime tool request failed for %s", self.path)
                    self._send_json(
                        503,
                        {
                            "error": (
                                "HITL_RUNTIME_ERROR runtime_request_failed\n"
                                "Runtime could not process this command. Retry the same "
                                "command in this worker session without changing the workspace."
                            )
                        },
                    )

            def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # Runtime processing is already complete. A provider that
                    # exits before its blocking command only loses delivery of
                    # this response; durable state remains authoritative.
                    self.close_connection = True
                    LOGGER.info(
                        "HITL runtime response client disconnected for %s",
                        self.path,
                    )

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ToolHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        self._tool_server = server
        self._tool_thread = thread
        self._tool_url = f"http://{host}:{port}"
        self._tool_token = token

    def _write_idea_tool_commands(self) -> None:
        commands = set(self._tool_context.get("allowed_worker_commands") or [])
        for command_name in _WORKER_COMMAND_MODULES:
            command_path = self.paths.tool_bin_dir / command_name
            if command_path.exists():
                command_path.unlink()
        for command_name in sorted(commands):
            module_file = _WORKER_COMMAND_MODULES.get(command_name)
            if module_file is None:
                raise HitlValidationError(f"Unknown HITL worker command: {command_name}")
            self._write_tool_command(command_name, module_file)

    def _write_tool_command(self, command_name: str, module_file: str) -> None:
        script = "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'export PYTHONPATH="${NEURICO_PROJECT_ROOT}/src:${PYTHONPATH:-}"',
                'exec "${NEURICO_PYTHON:-python}" '
                f'"${{NEURICO_PROJECT_ROOT}}/src/core/{module_file}" "$@"',
                "",
            ]
        )
        command_path = self.paths.tool_bin_dir / command_name
        command_path.write_text(script, encoding="utf-8")
        command_path.chmod(0o755)

    @staticmethod
    def validate_raised_idea(
        raised_idea: Dict[str, Any],
        *,
        existing_ids: Optional[set[str]] = None,
    ) -> None:
        for field in [
            "pipeline_stage",
            "hitl_stage",
            "idea_type",
            "idea_category",
            "context",
            "reason_for_escalation",
        ]:
            if not str(raised_idea.get(field, "")).strip():
                raise HitlValidationError(f"Raised idea missing required field: {field}")
        if raised_idea["idea_type"] not in {"decision", "evidence"}:
            raise HitlValidationError(f"Invalid raised idea_type: {raised_idea['idea_type']}")
        _validate_idea_category(raised_idea["idea_type"], raised_idea.get("idea_category"))
        if raised_idea["hitl_stage"] not in HITL_STAGES:
            raise HitlValidationError(
                f"Invalid raised idea hitl_stage: {raised_idea['hitl_stage']}"
            )
        if raised_idea["pipeline_stage"] not in PIPELINE_STAGES:
            raise HitlValidationError(
                f"Invalid raised idea pipeline_stage: {raised_idea['pipeline_stage']}"
            )
        _validate_premises(
            _normalize_premises(raised_idea.get("premises")),
            existing_ids,
        )
        if raised_idea["idea_type"] == "decision":
            if not _normalize_premises(raised_idea.get("premises")):
                raise HitlValidationError(
                    "Raised decision idea requires at least one finalized premise. "
                    "Use `hitl-view-ideas`, report missing supporting evidence first if needed, then retry."
                )
            if not str(raised_idea.get("decision_needed", "")).strip():
                raise HitlValidationError("Raised decision idea needs decision_needed")
            _validate_substantive_options(
                raised_idea.get("options"),
                error_prefix="Raised decision idea",
            )
        else:
            if not str(raised_idea.get("evidence", "")).strip():
                raise HitlValidationError("Raised evidence idea needs evidence")

    def _record_from_raised_idea(
        self,
        *,
        raised_idea: Dict[str, Any],
        level: str,
        actor: str,
        decision: str,
        manager_context: str,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        idea_type = raised_idea["idea_type"]
        record_extra = dict(extra)
        record: Dict[str, Any] = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": raised_idea.get("hitl_stage", "execution"),
            "level": level,
            "actor": actor,
            "idea_type": idea_type,
            "idea_category": raised_idea["idea_category"],
            "premises": _normalize_premises(raised_idea.get("premises")),
            "context": manager_context,
            "raised": True,
            "worker_context": raised_idea.get("context", ""),
            "worker_escalation_reason": raised_idea.get("reason_for_escalation", ""),
            "related_artifacts": _as_related_artifacts(raised_idea.get("related_artifacts")),
            **record_extra,
        }
        if idea_type == "decision":
            options = record_extra.pop(
                "options",
                _normalize_options(raised_idea.get("options", [])),
            )
            record.update(
                {
                    "decision_needed": raised_idea.get("decision_needed", ""),
                    "options": options,
                    "decision": decision,
                }
            )
        else:
            record.update(
                {
                    "evidence": raised_idea.get("evidence", ""),
                }
            )
        return record

    def _raised_idea_decision_options(
        self,
        raised_idea: Dict[str, Any],
        review: Dict[str, Any],
    ) -> List[str]:
        if raised_idea["idea_type"] != "decision":
            return []
        raw_options = review.get("options", raised_idea.get("options"))
        return _validate_substantive_options(
            raw_options,
            error_prefix="Manager-reviewed decision",
        )

    def _plan_artifact(self) -> List[Dict[str, str]]:
        rel = self.paths.plan_path.relative_to(self.work_dir)
        return [{"path": str(rel), "description": f"Living HITL plan for {self.pipeline_stage}."}]

    @staticmethod
    def _read_required(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Required HITL plan not found: {path}")
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _read_optional(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return read_jsonl_objects(path, record_label="finalized HITL idea record")


@dataclass(frozen=True)
class RequiredArtifact:
    path: str
    purpose: str
    required: bool


def parse_required_artifacts(interface_path: Path) -> List[RequiredArtifact]:
    """Parse the strict `## Files to produce` table from scoring/interface.md."""
    text = Path(interface_path).read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Files to produce")
    except StopIteration as exc:
        raise HitlValidationError("scoring/interface.md missing `## Files to produce`.") from exc

    idx = start + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx + 1 >= len(lines):
        raise HitlValidationError("`## Files to produce` must be followed by a Markdown table.")

    header = _markdown_table_cells(lines[idx])
    if header != ["Path", "Purpose", "Required"]:
        raise HitlValidationError(
            "Files-to-produce header must be exactly `Path | Purpose | Required`."
        )
    alignment = _markdown_table_cells(lines[idx + 1])
    if len(alignment) != 3 or any(not _is_alignment_cell(cell) for cell in alignment):
        raise HitlValidationError("Files-to-produce table has invalid alignment row.")

    artifacts: List[RequiredArtifact] = []
    seen: set[str] = set()
    row_idx = idx + 2
    while row_idx < len(lines) and lines[row_idx].strip().startswith("|"):
        cells = _markdown_table_cells(lines[row_idx])
        if len(cells) != 3:
            raise HitlValidationError("Files-to-produce rows must have exactly three cells.")
        rel_path = _normalize_required_artifact_path(cells[0])
        if rel_path in seen:
            raise HitlValidationError(f"Duplicate required artifact path: {rel_path}")
        seen.add(rel_path)
        required_text = cells[2].strip().lower()
        if required_text not in {"yes", "no", "recommended"}:
            raise HitlValidationError(f"Unknown Required value for {rel_path}: {cells[2]}")
        artifacts.append(
            RequiredArtifact(
                path=rel_path,
                purpose=cells[1].strip(),
                required=required_text == "yes",
            )
        )
        row_idx += 1

    if not any(artifact.required for artifact in artifacts):
        raise HitlValidationError(
            "Files-to-produce table must include at least one required artifact."
        )
    return artifacts


def verify_required_artifacts(work_dir: Path, artifacts: Iterable[RequiredArtifact]) -> None:
    root = Path(work_dir).resolve()
    for artifact in artifacts:
        if not artifact.required:
            continue
        path = root / artifact.path
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise HitlValidationError(
                f"Required artifact escapes the workspace: {artifact.path}"
            ) from exc
        if path.is_symlink():
            raise HitlValidationError(
                f"Required artifact cannot be a symlink: {artifact.path}"
            )
        if not path.exists():
            raise HitlValidationError(f"Required artifact missing: {artifact.path}")
        if artifact.path.endswith("/"):
            if not path.is_dir():
                raise HitlValidationError(
                    f"Required artifact should be a directory: {artifact.path}"
                )
            if not any(path.iterdir()):
                raise HitlValidationError(f"Required artifact directory is empty: {artifact.path}")
            continue
        if not path.is_file():
            raise HitlValidationError(f"Required artifact should be a file: {artifact.path}")
        if path.stat().st_size == 0:
            raise HitlValidationError(f"Required artifact is empty: {artifact.path}")
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".csv":
            import csv

            with path.open(newline="", encoding="utf-8") as f:
                next(csv.reader(f), None)


def validate_required_artifact_contract(work_dir: Path) -> Dict[str, Any]:
    """Return a worker-retryable validation result for the rule-maker contract."""
    try:
        artifacts = load_hitl_required_artifact_contract(work_dir)
        verify_required_artifacts(work_dir, artifacts)
    except (OSError, ValueError, json.JSONDecodeError, HitlValidationError) as exc:
        return {"valid": False, "issues": [str(exc)]}
    return {"valid": True, "issues": []}


def _artifact_contract_path(work_dir: Path) -> Path:
    return hitl_artifact_contract_path(work_dir)


def persist_hitl_required_artifact_contract(work_dir: Path) -> List[RequiredArtifact]:
    """Freeze the evaluator-owned required-artifact grammar for HITL execution."""
    root = Path(work_dir)
    interface_path = root / "scoring" / "interface.md"
    artifacts = parse_required_artifacts(interface_path)
    payload = {
        "version": 1,
        "interface_sha256": _sha256_file(interface_path),
        "artifacts": [
            {"path": artifact.path, "purpose": artifact.purpose, "required": artifact.required}
            for artifact in artifacts
        ],
    }
    path = _artifact_contract_path(root)
    atomic_write_json(
        path,
        payload,
        ensure_ascii=False,
        indent=2,
        fsync_parent=False,
    )
    return artifacts


def load_hitl_required_artifact_contract(work_dir: Path) -> List[RequiredArtifact]:
    """Load the runtime-frozen contract, verifying its evaluator source did not change."""
    root = Path(work_dir)
    path = _artifact_contract_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HitlValidationError(
            "Runtime-required artifact contract is missing or unreadable; rerun rule-maker HITL."
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise HitlValidationError("Runtime-required artifact contract has an invalid version.")
    interface_path = root / "scoring" / "interface.md"
    if _sha256_file(interface_path) != payload.get("interface_sha256"):
        raise HitlValidationError(
            "scoring/interface.md changed after runtime froze the rule-maker contract."
        )
    entries = payload.get("artifacts")
    if not isinstance(entries, list):
        raise HitlValidationError("Runtime-required artifact contract has no artifact list.")
    artifacts: List[RequiredArtifact] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("required"), bool):
            raise HitlValidationError("Runtime-required artifact contract has an invalid entry.")
        artifacts.append(
            RequiredArtifact(
                path=_normalize_required_artifact_path(str(entry.get("path", ""))),
                purpose=str(entry.get("purpose", "")).strip(),
                required=entry["required"],
            )
        )
    if not artifacts:
        raise HitlValidationError("Runtime-required artifact contract is empty.")
    return artifacts


def snapshot_path_state(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"state": "missing", "sha256": None}
    if path.is_file():
        return {"state": "file", "sha256": _sha256_file(path)}
    if path.is_dir():
        return {"state": "directory", "sha256": None}
    return {"state": "other", "sha256": None}


def assert_path_state_unchanged(path: Path, expected: Dict[str, Any], label: str) -> None:
    actual = snapshot_path_state(path)
    if actual != expected:
        raise HitlValidationError(
            f"{label} changed unexpectedly: expected {expected}, got {actual}"
        )


def _markdown_table_cells(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_alignment_cell(cell: str) -> bool:
    return bool(cell) and set(cell) <= {"-", ":"} and "-" in cell


def _normalize_required_artifact_path(value: str) -> str:
    path = value.strip()
    if path.startswith("`") and path.endswith("`") and path.count("`") == 2:
        path = path[1:-1].strip()
    wants_directory = path.endswith("/")
    if not path or path.startswith("/") or "://" in path or "*" in path:
        raise HitlValidationError(f"Unsafe artifact path: {value}")
    parts = Path(path).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HitlValidationError(f"Unsafe artifact path: {value}")
    normalized = Path(path).as_posix()
    return f"{normalized}/" if wants_directory and not normalized.endswith("/") else normalized
