"""
Plan-centered human-in-the-loop runtime.

HITL v1 keeps the stage worker responsible for stage work and its living plan.
Managers and humans resolve raised ideas; the stage worker receives feedback,
updates the plan, and resumes from the current workspace state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PIPELINE_STAGES = {
    "resource_finder",
    "rule_maker",
    "experiment_runner",
    "scorer",
    "paper_writer",
}
HITL_STAGES = {"plan", "execution", "review"}
LEVELS = {"A", "B", "C"}
IDEA_TYPES = {"decision", "evidence"}
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
    "worker_context",
    "context",
    "related_artifacts",
    "decision_needed",
    "evidence",
    "options",
    "decision",
    "human_feedback",
    "basis",
    "manager_feedback",
    "raised",
    "worker_escalation_reason",
    "manager_escalation_reason",
]

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def _as_related_artifacts(value: Any) -> List[Dict[str, str]]:
    artifacts: List[Dict[str, str]] = []
    if not isinstance(value, list):
        return artifacts
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        description = str(item.get("description", "")).strip()
        if path:
            artifacts.append({"path": path, "description": description})
    return artifacts


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


def _checkpoint_text(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key in ("recommended_option", "recommendation", "evidence", "basis", "text"):
            text = str(value.get(key, "")).strip()
            if text:
                parts.append(text)
        return " ".join(parts)
    return str(value or "").strip()


def _canonicalize_checkpoint(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    canonical = dict(checkpoint)
    if not str(canonical.get("context", "")).strip():
        for key in ("worker_context", "raised_decision", "explicit_signoff_question", "title"):
            value = _checkpoint_text(canonical.get(key))
            if value:
                canonical["context"] = value
                break
    if not str(canonical.get("basis", "")).strip():
        for key in ("basis", "evidence_backed_recommendation", "recommendation"):
            value = _checkpoint_text(canonical.get(key))
            if value:
                canonical["basis"] = value
                break
    if not str(canonical.get("reason_for_escalation", "")).strip():
        for key in ("reason_for_escalation", "blocks", "explicit_signoff_question"):
            value = _checkpoint_text(canonical.get(key))
            if value:
                canonical["reason_for_escalation"] = value
                break
    if canonical.get("idea_type") == "decision":
        if not str(canonical.get("decision_needed", "")).strip():
            for key in ("decision_needed", "raised_decision", "explicit_signoff_question"):
                value = _checkpoint_text(canonical.get(key))
                if value:
                    canonical["decision_needed"] = value
                    break
        if "options" not in canonical and "options_considered" in canonical:
            canonical["options"] = canonical["options_considered"]
    return canonical


def _option_texts(options: List[Dict[str, str]]) -> List[str]:
    return [option["text"] for option in options]


def _resolve_option_decision(response: str, options: List[Dict[str, str]]) -> Dict[str, str]:
    raw = response.strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            option = options[idx]
            return {"decision": option["option_id"], "feedback": option["text"]}
    for option in options:
        if raw == option["option_id"] or raw == option["text"]:
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


def _resolve_manager_option(response: str, options: List[Dict[str, str]]) -> Dict[str, str]:
    resolved = _resolve_option_decision(response, options)
    if resolved["decision"] == "CUSTOM":
        raise HitlValidationError(
            "Manager-resolved decision must match a substantive option"
        )
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
    """Raised when a HITL idea/checkpoint is malformed."""


class HitlIdeaLog:
    """Append-only finalized HITL idea log stored at logs/hitl/idea.jsonl."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.hitl_dir = self.work_dir / "logs" / "hitl"
        self.hitl_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.hitl_dir / "idea.jsonl"

    def append(self, idea: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(idea)
        record.setdefault("idea_id", self._next_id())
        record.setdefault("timestamp", _now())
        if record.get("idea_type") == "decision" and "options" in record:
            record["options"] = _normalize_options(record.get("options"))
        self.validate(record)
        record = _ordered_idea_record(record)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(_compact_json(record) + "\n")
        return record

    def _next_id(self) -> str:
        if not self.path.exists():
            return "I1"
        count = 0
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return f"I{count + 1}"

    def records(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return read_jsonl(self.path)

    @staticmethod
    def validate(record: Dict[str, Any]) -> None:
        required = [
            "idea_id",
            "timestamp",
            "pipeline_stage",
            "hitl_stage",
            "level",
            "actor",
            "idea_type",
            "context",
            "basis",
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
        if not str(record["context"]).strip():
            raise HitlValidationError("HITL idea context must be non-empty")
        if not str(record["basis"]).strip():
            raise HitlValidationError("HITL basis must be non-empty")

        if record["idea_type"] == "decision":
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
            if (
                _decision_record_uses_option_id(record)
                and record["decision"] != "CUSTOM"
            ):
                option_ids = {option["option_id"] for option in _normalize_options(record["options"])}
                if record["decision"] not in option_ids:
                    raise HitlValidationError(
                        "A/B option-based decision must be an option id or CUSTOM"
                    )
        else:
            if "evidence" not in record or not str(record["evidence"]).strip():
                raise HitlValidationError("Evidence idea requires non-empty evidence")


@dataclass
class HitlPaths:
    work_dir: Path
    pipeline_stage: str

    @property
    def plan_path(self) -> Path:
        return self.work_dir / "plans" / f"{self.pipeline_stage}_plan.md"

    @property
    def checkpoints_dir(self) -> Path:
        return self.work_dir / ".neurico" / "hitl" / "checkpoints"

    @property
    def current_checkpoint(self) -> Path:
        return self.checkpoints_dir / "pending_idea.json"


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
    ):
        if pipeline_stage not in PIPELINE_STAGES:
            raise ValueError(f"Unsupported HITL pipeline stage: {pipeline_stage}")
        self.work_dir = Path(work_dir)
        self.pipeline_stage = pipeline_stage
        self.paths = HitlPaths(self.work_dir, pipeline_stage)
        self.paths.plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.log = HitlIdeaLog(self.work_dir)
        self.channel = channel or self._default_channel()
        self.manager = manager or self._default_manager(config or {})
        self.current_hitl_stage = "execution"
        self._loaded_checkpoint_path: Optional[Path] = None

    @staticmethod
    def _default_channel() -> Any:
        from interactive.channel import TerminalChannel

        return TerminalChannel()

    @staticmethod
    def _default_manager(config: Dict[str, Any]) -> "LLMHitlManager":
        return LLMHitlManager(config)

    def plan_prompt_block(self) -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_plan.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
        )

    def execution_prompt_block(self, mode: str = "execute") -> str:
        self.current_hitl_stage = "execution"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_execution.txt",
            pipeline_stage=self.pipeline_stage,
            mode=mode,
            plan_path=rel_plan,
            checkpoint_path=rel_checkpoint,
        )

    def review_prompt_block(self) -> str:
        self.current_hitl_stage = "review"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_review_revision.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            checkpoint_path=rel_checkpoint,
        )

    def plan_revision_prompt_block(self, feedback: str) -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_plan_revision.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            feedback=feedback,
        )

    def feedback_continuation_prompt_block(self, feedback: str) -> str:
        self.current_hitl_stage = "execution"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        return _load_hitl_template(
            "worker_feedback_continuation.txt",
            pipeline_stage=self.pipeline_stage,
            plan_path=rel_plan,
            checkpoint_path=rel_checkpoint,
            feedback=feedback,
        )

    def approve_plan_loop(
        self,
        max_rounds: int = 5,
    ) -> Dict[str, Any]:
        for round_idx in range(1, max_rounds + 1):
            plan_text = self._read_required(self.paths.plan_path)
            review = self.manager.review_plan(
                pipeline_stage=self.pipeline_stage,
                plan_path=self.paths.plan_path,
                plan_text=plan_text,
                workspace_summary=self.workspace_summary(),
            )
            if review.get("status") == "not_ready":
                feedback = _require_text(
                    review.get("manager_feedback"),
                    "manager_feedback",
                    "Manager plan review with status='not_ready'",
                )
                self.log.append(
                    {
                        "pipeline_stage": self.pipeline_stage,
                        "hitl_stage": "plan",
                        "level": "B",
                        "actor": "manager",
                        "idea_type": "decision",
                        "context": str(review.get("context", "Manager reviewed the plan.")),
                        "basis": "Manager review of the materialized plan showed missing or unclear execution details.",
                        "options": [
                            "Accept current plan as ready for execution approval.",
                            "Revise current plan before execution approval.",
                        ],
                        "decision": "O2",
                        "raised": True,
                        "manager_feedback": feedback,
                        "related_artifacts": self._plan_artifact(),
                    }
                )
                return {
                    "approved": False,
                    "level": "B",
                    "actor": "manager",
                    "feedback": feedback,
                }

            request = self._plan_approval_message(review)
            plan_options = _normalize_options(["Approve plan.", "Provide feedback."])
            response = self.channel.prompt(
                message=request,
                options=_option_texts(plan_options),
            )
            if response is None:
                raise RuntimeError("HITL plan approval ended without a response.")
            human_decision = _resolve_human_decision(response, plan_options)
            decision = human_decision["decision"]
            human_feedback = human_decision["human_feedback"]
            approved = decision == "O1"
            manager_feedback = ""
            if not approved:
                if decision == "O2":
                    feedback_response = self.channel.prompt(
                        message=(
                            "Please provide concrete feedback for revising "
                            f"`{self.paths.plan_path.relative_to(self.work_dir)}`."
                        )
                    )
                    if feedback_response is None:
                        raise RuntimeError("HITL plan feedback ended without a response.")
                    human_feedback = feedback_response.strip()
                if _is_feedback_placeholder(human_feedback):
                    raise RuntimeError(
                        "HITL plan feedback must contain concrete revision instructions."
                    )
                manager_feedback = self.manager.feedback_from_human(
                    pipeline_stage=self.pipeline_stage,
                    hitl_stage="plan",
                    human_response=human_feedback,
                    context=str(review.get("context", "")),
                    plan_text=plan_text,
                )
            self.log.append(
                {
                    "pipeline_stage": self.pipeline_stage,
                    "hitl_stage": "plan",
                    "level": "A",
                    "actor": "human",
                    "idea_type": "decision",
                    "context": str(review.get("context", "Manager presented the plan for approval.")),
                    "basis": "The human made this plan approval or feedback decision.",
                    "options": plan_options,
                    "decision": decision,
                    "raised": True,
                    "human_feedback": human_feedback,
                    "manager_escalation_reason": "Human approval is required before worker execution begins.",
                    "manager_feedback": manager_feedback,
                    "related_artifacts": self._plan_artifact(),
                }
            )
            if approved:
                return {"approved": True, "level": "A", "actor": "human"}
            return {
                "approved": False,
                "level": "A",
                "actor": "human",
                "feedback": manager_feedback or human_feedback,
            }
        raise RuntimeError("HITL plan approval did not converge within max rounds.")

    def plan_has_human_approval(self) -> bool:
        if not self.paths.plan_path.exists():
            return False
        for record in reversed(self.log.records()):
            if (
                record.get("pipeline_stage") == self.pipeline_stage
                and record.get("hitl_stage") == "plan"
                and record.get("idea_type") == "decision"
                and record.get("level") == "A"
                and record.get("actor") == "human"
                and record.get("decision") == "O1"
            ):
                return True
        return False

    def resolve_checkpoint(
        self,
        hitl_stage: Optional[str] = None,
        *,
        require_pending: bool = False,
    ) -> Optional[Dict[str, Any]]:
        checkpoint = self.load_checkpoint(hitl_stage=hitl_stage, require_pending=require_pending)
        if checkpoint is None:
            return None
        review = self.manager.review_checkpoint(
            pipeline_stage=self.pipeline_stage,
            checkpoint=checkpoint,
            plan_text=self._read_optional(self.paths.plan_path),
            workspace_summary=self.workspace_summary(),
        )
        decision_options = self._checkpoint_decision_options(checkpoint, review)
        if review.get("requires_human"):
            response = self.channel.prompt(
                message=self._human_checkpoint_message(checkpoint, review),
                options=_option_texts(decision_options) or None,
            )
            if response is None:
                raise RuntimeError("HITL checkpoint resolution ended without a response.")
            if checkpoint["idea_type"] == "decision":
                human_decision = _resolve_human_decision(response, decision_options)
                decision = human_decision["decision"]
                human_feedback = human_decision["human_feedback"]
            else:
                decision = response.strip()
                human_feedback = decision
            feedback = self.manager.feedback_from_human(
                pipeline_stage=self.pipeline_stage,
                hitl_stage=str(checkpoint.get("hitl_stage", "execution")),
                human_response=human_feedback,
                context=str(review.get("context", checkpoint.get("context", ""))),
                plan_text=self._read_optional(self.paths.plan_path),
            )
            level = "A"
            actor = "human"
            extra = {
                "manager_escalation_reason": str(review.get("manager_escalation_reason", "")),
                "manager_feedback": feedback,
                "human_feedback": human_feedback,
            }
            if checkpoint["idea_type"] == "decision":
                extra["options"] = decision_options
        else:
            feedback = _require_text(
                review.get("manager_feedback"),
                "manager_feedback",
                "Manager checkpoint resolution",
            )
            if checkpoint["idea_type"] == "decision":
                raw_decision = _require_text(
                    review.get("decision"),
                    "decision",
                    "Manager-resolved decision checkpoint",
                )
                decision = _resolve_manager_option(raw_decision, decision_options)["decision"]
            else:
                raw_decision = str(review.get("decision", feedback)).strip()
                decision = raw_decision
            level = "B"
            actor = "manager"
            extra = {
                "manager_feedback": feedback,
                "basis": str(review.get("basis", "")).strip(),
            }
            if checkpoint["idea_type"] == "decision":
                extra["options"] = decision_options

        record = self._record_from_checkpoint(
            checkpoint=checkpoint,
            level=level,
            actor=actor,
            decision=decision,
            manager_context=str(review.get("context", checkpoint.get("context", ""))),
            extra=extra,
        )
        logged = self.log.append(record)
        self.archive_checkpoint(logged)
        return logged

    def log_review_feedback(self, feedback: str) -> None:
        self.log.append(
            {
                "pipeline_stage": self.pipeline_stage,
                "hitl_stage": "review",
                "level": "B",
                "actor": "manager",
                "idea_type": "decision",
                "context": "Manager reviewed stage artifacts against the living plan.",
                "basis": "Manager artifact review found gaps between the completed artifacts and the living plan.",
                "options": [
                    "Accept current artifacts as complete.",
                    "Revise artifacts to match the living plan.",
                ],
                "decision": "O2",
                "raised": True,
                "manager_feedback": feedback,
                "related_artifacts": self._plan_artifact(),
            }
        )

    def review_stage(self) -> Dict[str, Any]:
        return self.manager.review_stage(
            pipeline_stage=self.pipeline_stage,
            plan_path=self.paths.plan_path,
            plan_text=self._read_optional(self.paths.plan_path),
            workspace_summary=self.workspace_summary(),
        )

    def log_stage_approval(self, context: str) -> None:
        self.log.append(
            {
                "pipeline_stage": self.pipeline_stage,
                "hitl_stage": "review",
                "level": "B",
                "actor": "manager",
                "idea_type": "decision",
                "context": context or "Manager approved completed stage artifacts.",
                "basis": "Manager artifact review found the completed stage aligned with the living plan.",
                "options": ["Approve stage completion.", "Request revision."],
                "decision": "O1",
                "raised": False,
                "related_artifacts": self._plan_artifact(),
            }
        )

    def prepare_checkpoint_target(self) -> None:
        self._clear_checkpoint_dir()
        self.paths.current_checkpoint.write_text("", encoding="utf-8")
        self._loaded_checkpoint_path = None

    def has_pending_checkpoint_payload(self, hitl_stage: Optional[str] = None) -> bool:
        return self.load_checkpoint(hitl_stage=hitl_stage, require_pending=False) is not None

    def load_checkpoint(
        self,
        hitl_stage: Optional[str] = None,
        *,
        require_pending: bool = False,
    ) -> Optional[Dict[str, Any]]:
        path = self._pending_checkpoint_path(require_pending=require_pending)
        if path is None:
            return None
        with open(path, encoding="utf-8") as f:
            try:
                checkpoint = _canonicalize_checkpoint(json.load(f))
            except json.JSONDecodeError as exc:
                raise HitlValidationError(
                    f"Invalid HITL checkpoint JSON in {path.relative_to(self.work_dir)}: {exc}"
                ) from exc
        effective_hitl_stage = hitl_stage or self.current_hitl_stage
        self.current_hitl_stage = effective_hitl_stage
        checkpoint["pipeline_stage"] = self.pipeline_stage
        checkpoint["hitl_stage"] = effective_hitl_stage
        self.validate_checkpoint(checkpoint)
        self._loaded_checkpoint_path = path
        return checkpoint

    def archive_checkpoint(self, record: Dict[str, Any]) -> None:
        path = self._loaded_checkpoint_path or self._pending_checkpoint_path()
        if path is None:
            return
        hitl_stage = str(record.get("hitl_stage", "execution"))
        idea_id = str(record.get("idea_id", "")).strip()
        if not idea_id:
            raise HitlValidationError("Cannot archive resolved checkpoint without idea_id")
        archive_dir = (
            self.work_dir
            / "logs"
            / "hitl"
            / "resolve_checkpoint"
            / self.pipeline_stage
            / hitl_stage
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        dst = archive_dir / f"{idea_id}.json"
        os.replace(path, dst)
        self.prepare_checkpoint_target()

    def _pending_checkpoint_path(self, *, require_pending: bool = False) -> Optional[Path]:
        exact = self.paths.current_checkpoint
        if exact.exists() and exact.stat().st_size > 0:
            return exact

        candidates = sorted(
            p
            for p in self.paths.checkpoints_dir.glob("*.json")
            if p.is_file() and p.name != exact.name and p.stat().st_size > 0
        )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            rels = ", ".join(str(p.relative_to(self.work_dir)) for p in candidates)
            raise HitlValidationError(
                "Ambiguous HITL checkpoint files. Expected non-empty "
                f"{exact.relative_to(self.work_dir)} or exactly one recoverable JSON file. "
                f"Found: {rels}"
            )
        if require_pending:
            raise HitlValidationError(
                "HITL worker stopped without completion marker, but no pending idea was found. "
                f"Expected non-empty {exact.relative_to(self.work_dir)} or exactly one "
                f"recoverable JSON file in {self.paths.checkpoints_dir.relative_to(self.work_dir)}."
            )
        return None

    def _clear_checkpoint_dir(self) -> None:
        self.paths.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        for path in self.paths.checkpoints_dir.iterdir():
            if path.is_file():
                path.unlink()

    @staticmethod
    def validate_checkpoint(checkpoint: Dict[str, Any]) -> None:
        checkpoint = _canonicalize_checkpoint(checkpoint)
        for field in [
            "pipeline_stage",
            "hitl_stage",
            "idea_type",
            "context",
            "basis",
            "reason_for_escalation",
        ]:
            if not str(checkpoint.get(field, "")).strip():
                raise HitlValidationError(f"Checkpoint missing required field: {field}")
        if checkpoint["idea_type"] not in IDEA_TYPES:
            raise HitlValidationError(f"Invalid checkpoint idea_type: {checkpoint['idea_type']}")
        if checkpoint["hitl_stage"] not in HITL_STAGES:
            raise HitlValidationError(f"Invalid checkpoint hitl_stage: {checkpoint['hitl_stage']}")
        if checkpoint["pipeline_stage"] not in PIPELINE_STAGES:
            raise HitlValidationError(
                f"Invalid checkpoint pipeline_stage: {checkpoint['pipeline_stage']}"
            )
        if checkpoint["idea_type"] == "decision":
            if not str(checkpoint.get("decision_needed", "")).strip():
                raise HitlValidationError("Raised decision checkpoint needs decision_needed")
            _validate_substantive_options(
                checkpoint.get("options"),
                error_prefix="Raised decision checkpoint",
            )
        else:
            if not str(checkpoint.get("evidence", "")).strip():
                raise HitlValidationError("Raised evidence checkpoint needs evidence")

    def workspace_summary(self) -> str:
        interesting = [
            "plans",
            "literature_review.md",
            "resources.md",
            "papers",
            "datasets",
            "code",
            "logs",
        ]
        lines = [f"Workspace: {self.work_dir}"]
        for rel in interesting:
            path = self.work_dir / rel
            if path.is_dir():
                files = sum(1 for p in path.rglob("*") if p.is_file())
                lines.append(f"- {rel}/ ({files} files)")
            elif path.exists():
                lines.append(f"- {rel} ({path.stat().st_size} bytes)")
            else:
                lines.append(f"- {rel} (missing)")
        return "\n".join(lines)

    def _record_from_checkpoint(
        self,
        *,
        checkpoint: Dict[str, Any],
        level: str,
        actor: str,
        decision: str,
        manager_context: str,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        idea_type = checkpoint["idea_type"]
        basis = self._checkpoint_basis(
            checkpoint=checkpoint,
            idea_type=idea_type,
            actor=actor,
            extra=extra,
        )
        record_extra = dict(extra)
        record_extra.pop("basis", None)
        record: Dict[str, Any] = {
            "pipeline_stage": self.pipeline_stage,
            "hitl_stage": checkpoint.get("hitl_stage", "execution"),
            "level": level,
            "actor": actor,
            "idea_type": idea_type,
            "context": manager_context,
            "basis": basis,
            "raised": True,
            "worker_context": checkpoint.get("context", ""),
            "worker_escalation_reason": checkpoint.get("reason_for_escalation", ""),
            "related_artifacts": _as_related_artifacts(checkpoint.get("related_artifacts")),
            **record_extra,
        }
        if idea_type == "decision":
            options = record_extra.pop(
                "options",
                _normalize_options(checkpoint.get("options", [])),
            )
            record.update(
                {
                    "decision_needed": checkpoint.get("decision_needed", ""),
                    "options": options,
                    "decision": decision,
                }
            )
        else:
            record.update(
                {
                    "evidence": checkpoint.get("evidence", ""),
                }
        )
        return record

    def _checkpoint_basis(
        self,
        *,
        checkpoint: Dict[str, Any],
        idea_type: str,
        actor: str,
        extra: Dict[str, Any],
    ) -> str:
        if actor == "human":
            if idea_type == "decision":
                return "The human made this decision."
            return "The human made this evidence idea."
        return (
            str(extra.get("basis", "")).strip()
            or str(checkpoint.get("basis", "")).strip()
            or str(checkpoint.get("reason_for_escalation", "")).strip()
        )

    def _checkpoint_decision_options(
        self,
        checkpoint: Dict[str, Any],
        review: Dict[str, Any],
    ) -> List[str]:
        if checkpoint["idea_type"] != "decision":
            return []
        raw_options = review.get("options", checkpoint.get("options"))
        return _validate_substantive_options(
            raw_options,
            error_prefix="Manager-reviewed decision",
        )

    def _plan_approval_message(self, review: Dict[str, Any]) -> str:
        plan_rel = self.paths.plan_path.relative_to(self.work_dir)
        context = str(review.get("context", "")).strip()
        if not context:
            context = f"Manager reviewed `{plan_rel}` and found it ready for human approval."
        return (
            f"HITL plan approval needed for `{self.pipeline_stage}`.\n\n"
            f"{context}\n\n"
            f"Plan artifact: {plan_rel}\n\n"
            "Approve the plan to let the worker execute it, or provide feedback."
        )

    def _human_checkpoint_message(self, checkpoint: Dict[str, Any], review: Dict[str, Any]) -> str:
        parts = [
            f"HITL input needed for `{self.pipeline_stage}`.",
            "",
            str(review.get("context") or checkpoint.get("context", "")),
            "",
            f"Worker escalation reason: {checkpoint.get('reason_for_escalation', '')}",
        ]
        if checkpoint.get("idea_type") == "decision":
            parts.extend(["", f"Decision needed: {checkpoint.get('decision_needed', '')}"])
        else:
            parts.extend(["", f"Evidence: {checkpoint.get('evidence', '')}"])
        artifacts = _as_related_artifacts(checkpoint.get("related_artifacts"))
        if artifacts:
            parts.append("")
            parts.append("Related artifacts:")
            for artifact in artifacts:
                parts.append(f"- {artifact['path']}: {artifact['description']}")
        return "\n".join(parts)

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


class LLMHitlManager:
    """One-shot manager adapter using NeuriCo's existing manager LLM backend."""

    def __init__(self, config: Dict[str, Any]):
        from interactive.llm_backend import create_backend

        self.backend = create_backend(config)

    @staticmethod
    def _json_output_contract() -> str:
        return _load_hitl_template("json_output_contract.txt")

    def review_plan(
        self,
        *,
        pipeline_stage: str,
        plan_path: Path,
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = _load_hitl_template(
            "manager_review_plan.txt",
            json_output_contract=self._json_output_contract(),
            pipeline_stage=pipeline_stage,
            plan_path=plan_path,
            workspace_summary=workspace_summary,
            plan_text=plan_text,
        )
        data = self._json_call(prompt)
        status = data.get("status")
        if status not in {"ready", "not_ready"}:
            raise HitlValidationError(
                "Manager plan review must return status 'ready' or 'not_ready'."
            )
        if status == "not_ready":
            _require_text(
                data.get("manager_feedback"),
                "manager_feedback",
                "Manager plan review with status='not_ready'",
            )
        return data

    def review_checkpoint(
        self,
        *,
        pipeline_stage: str,
        checkpoint: Dict[str, Any],
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = _load_hitl_template(
            "manager_review_checkpoint.txt",
            json_output_contract=self._json_output_contract(),
            pipeline_stage=pipeline_stage,
            workspace_summary=workspace_summary,
            plan_text=plan_text,
            checkpoint_json=json.dumps(checkpoint, indent=2, ensure_ascii=False),
        )
        data = self._json_call(prompt)
        if not isinstance(data.get("requires_human"), bool):
            raise HitlValidationError(
                "Manager checkpoint review must return boolean `requires_human`."
            )
        if data["requires_human"]:
            _require_text(
                data.get("manager_escalation_reason"),
                "manager_escalation_reason",
                "Manager checkpoint escalation",
            )
        else:
            _require_text(
                data.get("manager_feedback"),
                "manager_feedback",
                "Manager checkpoint resolution",
            )
            if checkpoint.get("idea_type") == "decision":
                _require_text(
                    data.get("decision"),
                    "decision",
                    "Manager-resolved decision checkpoint",
                )
        return data

    def feedback_from_human(
        self,
        *,
        pipeline_stage: str,
        hitl_stage: str,
        human_response: str,
        context: str,
        plan_text: str,
    ) -> str:
        prompt = _load_hitl_template(
            "manager_feedback_from_human.txt",
            json_output_contract=self._json_output_contract(),
            pipeline_stage=pipeline_stage,
            hitl_stage=hitl_stage,
            context=context,
            human_response=human_response,
            plan_text=plan_text,
        )
        data = self._json_call(prompt)
        return _require_text(
            data.get("manager_feedback"),
            "manager_feedback",
            "Manager translation of human HITL feedback",
        )

    def review_stage(
        self,
        *,
        pipeline_stage: str,
        plan_path: Path,
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = _load_hitl_template(
            "manager_review_stage.txt",
            json_output_contract=self._json_output_contract(),
            pipeline_stage=pipeline_stage,
            plan_path=plan_path,
            workspace_summary=workspace_summary,
            plan_text=plan_text,
        )
        data = self._json_call(prompt)
        if data.get("status") not in {"aligned", "not_aligned"}:
            raise HitlValidationError(
                "Manager stage review must return status 'aligned' or 'not_aligned'."
            )
        if data.get("status") == "not_aligned":
            _require_text(
                data.get("manager_feedback"),
                "manager_feedback",
                "Manager stage review with status='not_aligned'",
            )
        return data

    def _json_call(self, prompt: str) -> Dict[str, Any]:
        response = self.backend.send(
            [
                {
                    "role": "system",
                    "content": _load_hitl_template("manager_system.txt"),
                },
                {"role": "user", "content": prompt},
            ]
        )
        text = response.text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start >= 0:
                data, _ = json.JSONDecoder().raw_decode(text[start:])
                if isinstance(data, dict):
                    return data
            raise


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def find_pending_checkpoints(work_dir: Path) -> Iterable[Path]:
    checkpoint_dir = Path(work_dir) / ".neurico" / "hitl" / "checkpoints"
    if not checkpoint_dir.exists():
        return []
    path = checkpoint_dir / "pending_idea.json"
    return [path] if path.is_file() else []
