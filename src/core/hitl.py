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


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _hitl_template_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "templates" / "hitl"


def _load_hitl_template(name: str, **kwargs: Any) -> str:
    template_path = _hitl_template_dir() / name
    text = template_path.read_text(encoding="utf-8")
    return text.format(**kwargs)


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
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HITL PLAN MODE
═══════════════════════════════════════════════════════════════════════════════

You are the stage worker for `{self.pipeline_stage}`. This invocation is only
for planning. The output is a living control artifact, not a final report.

Write or update `{rel_plan}`. The plan must be concrete enough that a manager
can decide whether execution should begin.

Required plan content:
- goal and scope for this stage
- current workspace state and assumptions
- intended artifacts to create or update
- step-by-step execution plan
- decision/evidence criteria for ideas that can be handled autonomously
- escalation criteria for ideas that require manager or human feedback,
  especially choices about research scope, resource strategy, dataset suitability,
  benchmark/source tradeoffs, licensing ambiguity, or evidence quality that could
  change downstream experiments
- known risks, gaps, and stop conditions
- current progress section, initially marking planning as complete

Hard constraints:
- Do not gather resources, download papers, clone repositories, or write stage
  deliverables in planning mode.
- Do not create `.resource_finder_complete`.
- Create `.resource_finder_plan_complete` only after `{rel_plan}` is ready for
  manager review.

The manager will review this plan. If it is good enough, the human will approve
or provide feedback before execution starts.
"""

    def execution_prompt_block(self, mode: str = "execute") -> str:
        self.current_hitl_stage = "execution"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        test_block = ""
        if _env_enabled("NEURICO_HITL_TEST_FORCE_IDEA_MIX"):
            test_block = _load_hitl_template(
                "test_resource_finder_idea_mix.txt",
                pipeline_stage=self.pipeline_stage,
                plan_path=rel_plan,
                checkpoint_path=rel_checkpoint,
            )
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HITL EXECUTION MODE
═══════════════════════════════════════════════════════════════════════════════

You are the stage worker for `{self.pipeline_stage}` in HITL `{mode}` mode.

Before doing new work:
1. Read `{rel_plan}`.
2. Inspect the current workspace state.
3. Continue from recorded progress. Do not restart completed work.

Use `{rel_plan}` as the living control artifact. Keep its progress section
current as you work.

Idea protocol:
- An idea is either `evidence` or `decision`.
- Evidence idea: important information discovered during the stage.
- Decision idea: a choice/action under a specific context.
- C-level autonomous ideas may be recorded in the plan without blocking.
- Raised ideas must block execution until manager/human feedback is resolved.
- Prefer raising a checkpoint when a resource decision would materially affect
  downstream experiment design, evaluation meaning, reproducibility, scope, or
  user-facing research direction. Do not silently choose among plausible dataset,
  benchmark, paper-source, licensing, or evidence-quality alternatives when the
  choice depends on project intent rather than simple technical availability.
- For SciFact-style resource finding, dataset/source selection, train/dev/test
  availability, label mapping, claim/evidence pairing strategy, and whether to
  prioritize canonical releases versus alternate mirrors are all legitimate
  raised decision candidates when there is meaningful ambiguity.

If an idea must be raised, you MUST do all of this before stopping:
1. Update `{rel_plan}` with current progress, the raised idea, why it matters,
   related artifacts, pending next steps, and substantive options if it is a
   decision.
2. Write exactly one unresolved checkpoint packet to `{rel_checkpoint}`.
   Use exactly this path. Do not add timestamps, suffixes, or alternate
   filenames; runtime consumes this canonical current-checkpoint file.
3. Stop immediately without creating `.resource_finder_complete`.

Checkpoint packet schema for raised ideas:
{{
  "idea_type": "decision | evidence",
  "context": "REQUIRED. Worker-provided self-contained context. Use this exact key.",
  "basis": "evidence, reason, or provenance supporting this idea",
  "decision_needed": "required for decision ideas",
  "evidence": "required for evidence ideas",
  "options": ["required substantive workflow choices for raised decision ideas; omit for evidence ideas"],
  "reason_for_escalation": "why manager/human feedback is needed",
  "related_artifacts": [
    {{"path": "relative/path", "description": "why it matters"}}
  ]
}}

Runtime-owned fields:
- Do not write `pipeline_stage` or `hitl_stage` in the checkpoint packet.
- Runtime records `pipeline_stage` as `{self.pipeline_stage}` and `hitl_stage`
  as `execution` when it consumes `{rel_checkpoint}`.

Schema split:
- If `idea_type` is `"decision"`, the checkpoint MUST include
  `decision_needed` and `options`. Put supporting facts/provenance in `basis`.
  Do NOT use top-level `evidence` as a substitute for `decision_needed`.
- If `idea_type` is `"evidence"`, the checkpoint MUST include `evidence` and
  MUST omit `decision_needed` and `options`.

Minimal decision checkpoint example:
{{
  "idea_type": "decision",
  "context": "Current progress and why this decision is blocking.",
  "basis": "Facts/provenance supporting the decision.",
  "decision_needed": "Which dataset framing should be primary?",
  "options": [
    "Use the 3-class SciFact framing.",
    "Use the 2-class SUPPORT-vs-CONTRADICT framing."
  ],
  "reason_for_escalation": "The choice changes downstream evaluation.",
  "related_artifacts": [
    {{"path": "datasets/build_pairs.py", "description": "Current rebuild script."}}
  ]
}}

Use these exact JSON keys. Do not write alias keys such as `raised_decision`,
`options_considered`, `explicit_signoff_question`, `blocks`, or `recommendation`
instead of the schema keys above. Runtime validation requires `context`,
`basis`, and `reason_for_escalation`; decision checkpoints additionally require
`decision_needed` and `options`. A decision checkpoint without `decision_needed`
is invalid and will stop the run.

Only create `.resource_finder_complete` when all stage deliverables are complete
and no unresolved checkpoint exists.
{test_block}
"""

    def review_prompt_block(self) -> str:
        self.current_hitl_stage = "review"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HITL REVIEW REVISION MODE
═══════════════════════════════════════════════════════════════════════════════

You are revising `{self.pipeline_stage}` artifacts after manager review.

Read `{rel_plan}` and the current workspace state. Continue from recorded
progress; do not redo completed work unless the plan explicitly requires it.

Implement only the revisions required by the living plan. Keep `{rel_plan}`
updated with progress and remaining gaps.

If another idea requires manager/human feedback, update `{rel_plan}`, write a
checkpoint packet to `{rel_checkpoint}`, and stop without creating
`.resource_finder_complete`. Use exactly this path; do not add timestamps,
suffixes, or alternate filenames.

Do not write `pipeline_stage` or `hitl_stage` in the checkpoint packet. Runtime
records `pipeline_stage` as `{self.pipeline_stage}` and `hitl_stage` as
`review` when it consumes `{rel_checkpoint}`.
"""

    def plan_revision_prompt_block(self, feedback: str) -> str:
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HITL PLAN REVISION MODE
═══════════════════════════════════════════════════════════════════════════════

You are revising your own `{self.pipeline_stage}` living plan at `{rel_plan}`.

This is plan revision only. Do not perform stage work.

Required behavior:
1. Read the existing plan and current workspace state.
2. Preserve useful completed reasoning and progress.
3. Apply only the manager/human feedback below.
4. Make the plan concrete enough for another manager review.
5. Update the progress section to explain what changed.

Manager/human feedback to apply:

{feedback}

Hard constraints:
- Do not gather resources or modify stage output artifacts.
- Do not create `.resource_finder_complete`.
- Create `.resource_finder_plan_complete` only after `{rel_plan}` is revised.
"""

    def feedback_continuation_prompt_block(self, feedback: str) -> str:
        self.current_hitl_stage = "execution"
        rel_plan = self.paths.plan_path.relative_to(self.work_dir)
        rel_checkpoint = self.paths.current_checkpoint.relative_to(self.work_dir)
        return f"""
═══════════════════════════════════════════════════════════════════════════════
                         HITL FEEDBACK CONTINUATION MODE
═══════════════════════════════════════════════════════════════════════════════

You are resuming `{self.pipeline_stage}` after a raised HITL item was resolved.

Before doing new work:
1. Read `{rel_plan}`.
2. Inspect current workspace artifacts.
3. Locate the last recorded progress and continue from there.
4. Do not restart completed work.

Resolved feedback:

{feedback}

First update `{rel_plan}` with the resolution, current progress, and next
steps. Then continue execution from the revised plan.

If the feedback changes previous assumptions, revise the plan before modifying
stage artifacts. If another raised idea appears, write a checkpoint to
`{rel_checkpoint}` and stop. Use exactly this path; do not add timestamps,
suffixes, or alternate filenames.
"""

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
                feedback = str(review.get("manager_feedback", "")).strip()
                if not feedback:
                    feedback = "Revise the plan to make concrete next steps, risks, and outputs explicit."
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
            raw_decision = str(review.get("decision", review.get("manager_feedback", ""))).strip()
            if checkpoint["idea_type"] == "decision":
                decision = _resolve_manager_option(raw_decision, decision_options)["decision"]
            else:
                decision = raw_decision
            feedback = str(review.get("manager_feedback", raw_decision)).strip()
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

    def review_plan(
        self,
        *,
        pipeline_stage: str,
        plan_path: Path,
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = f"""Review this NeuriCo HITL stage plan as the manager.

Your job is to decide whether the materialized plan is ready for human
approval. Be strict: a vague plan should be marked not_ready even if the goal
sounds reasonable.

Return strict JSON only:
{{
  "status": "ready | not_ready",
  "context": "neutral self-contained manager context for the decision",
  "manager_feedback": "worker-facing feedback if not_ready; empty string if ready"
}}

Ready means the plan contains:
- stage goal and scope
- concrete execution steps
- expected artifacts
- progress/status section
- risks or gaps
- criteria for autonomous ideas
- criteria for raised ideas/checkpoints

If not_ready, manager_feedback must be actionable instructions for the stage
worker to revise the living plan. Do not ask the worker to execute stage work
during plan revision.

Pipeline stage: {pipeline_stage}
Plan path: {plan_path}

Workspace summary:
{workspace_summary}

Plan:
{plan_text}
"""
        data = self._json_call(prompt)
        status = data.get("status")
        if status not in {"ready", "not_ready"}:
            data["status"] = "not_ready"
        return data

    def review_checkpoint(
        self,
        *,
        pipeline_stage: str,
        checkpoint: Dict[str, Any],
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = f"""Resolve or escalate this NeuriCo HITL checkpoint as manager.

The worker has stopped. It cannot proceed until this checkpoint is resolved.
You must either resolve the idea at B level as manager, or escalate it to the
human at A level when the decision/evidence depends on human research intent.

Return strict JSON only:
{{
  "requires_human": true,
  "context": "neutral self-contained manager context",
  "basis": "evidence, reason, or provenance supporting the manager-resolved idea; empty string if human must decide",
  "options": ["optional manager-refined substantive workflow choices for decision ideas; omit for evidence ideas"],
  "manager_escalation_reason": "why human input is needed, if true",
  "decision": "selected option_id or selected option text if resolving without human",
  "manager_feedback": "worker-facing feedback to put into the plan"
}}

For decision ideas, preserve the worker's substantive options unless they need
neutral wording or clearer boundaries. Do not create routing options such as
"ask human" or "ask manager". If resolving without human, the decision must
match one returned option exactly. For evidence ideas, do not return options.

Escalate to human only when the issue depends on author intent, research scope,
preference, risk tolerance, or another judgment the manager should not decide.
When the worker raises a resource strategy, dataset suitability, benchmark
choice, source priority, or evidence-quality tradeoff with more than one
reasonable option, treat it as human-scoped unless the living plan already
settles that preference clearly.
If resolving as manager, manager_feedback must tell the worker how to update the
living plan and continue without losing progress.

{self._checkpoint_test_prompt_block()}

Pipeline stage: {pipeline_stage}
Workspace summary:
{workspace_summary}

Living plan:
{plan_text}

Checkpoint:
{json.dumps(checkpoint, indent=2, ensure_ascii=False)}
"""
        data = self._json_call(prompt)
        data["requires_human"] = bool(data.get("requires_human"))
        return data

    def _checkpoint_test_prompt_block(self) -> str:
        if not _env_enabled("NEURICO_HITL_TEST_FORCE_MANAGER_SPLIT"):
            return ""
        return _load_hitl_template("test_manager_split.txt")

    def feedback_from_human(
        self,
        *,
        pipeline_stage: str,
        hitl_stage: str,
        human_response: str,
        context: str,
        plan_text: str,
    ) -> str:
        prompt = f"""Convert human HITL feedback into worker-facing plan-edit instructions.

The human response is authoritative. Preserve its intent. Your task is only to
translate it into precise instructions the stage worker can apply to the living
plan and current workspace state.

Return strict JSON only:
{{"manager_feedback": "concise instruction for updating the living plan"}}

The instruction must:
- state what to change in the living plan
- state what the worker should do next
- preserve completed progress unless the human explicitly changes direction
- avoid adding new decisions not present in the human response

Pipeline stage: {pipeline_stage}
HITL stage: {hitl_stage}
Context shown to human:
{context}

Human response:
{human_response}

Current living plan:
{plan_text}
"""
        data = self._json_call(prompt)
        return str(data.get("manager_feedback", human_response)).strip()

    def review_stage(
        self,
        *,
        pipeline_stage: str,
        plan_path: Path,
        plan_text: str,
        workspace_summary: str,
    ) -> Dict[str, Any]:
        prompt = f"""Review completed NeuriCo stage artifacts against the living HITL plan.

Your job is to decide whether the stage artifacts satisfy the approved living
plan. Be concrete and artifact-based.

Return strict JSON only:
{{
  "status": "aligned | not_aligned",
  "context": "neutral self-contained artifact-based review context",
  "manager_feedback": "worker-facing revision feedback if not_aligned"
}}

Aligned means the expected artifacts exist, the plan's promised work is done,
known limitations are documented, and no unresolved checkpoint remains.

If not_aligned, manager_feedback must tell the stage worker exactly how to
revise the living plan and artifacts while preserving completed progress.

{self._review_test_prompt_block()}

Pipeline stage: {pipeline_stage}
Plan path: {plan_path}
Workspace summary:
{workspace_summary}

Living plan:
{plan_text}
"""
        data = self._json_call(prompt)
        if data.get("status") not in {"aligned", "not_aligned"}:
            data["status"] = "not_aligned"
        return data

    def _review_test_prompt_block(self) -> str:
        if not _env_enabled("NEURICO_HITL_TEST_FORCE_REVIEW_REVISION"):
            return ""
        return _load_hitl_template("test_review_revision.txt")

    def _json_call(self, prompt: str) -> Dict[str, Any]:
        response = self.backend.send(
            [
                {
                    "role": "system",
                    "content": "You are NeuriCo's HITL manager. Return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        text = response.text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
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
