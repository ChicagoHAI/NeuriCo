"""Interactive ReAct manager for the HITL runtime.

The manager has one chronological conversation and one tool loop.  Runtime
workflow state is deliberately kept in :mod:`core.hitl_runtime_state`; a
blocking worker command is not a manager mode.
"""

from __future__ import annotations

import json
import hashlib
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.hitl_runtime_state import HitlRuntimeState, HitlRuntimeStateError
from core.hitl_workspace_inspection import HitlWorkspaceInspector


class _StaleManagerTurn(RuntimeError):
    """Internal signal that rollback invalidated an in-flight manager turn."""


@dataclass
class _Turn:
    speaker: str
    content: str
    requires_worker_resolution: bool = False
    done: Optional[threading.Event] = None
    reply: str = ""
    error: Optional[BaseException] = None
    input_recorded: bool = False
    retry_count: int = 0
    generation: int = 0


@dataclass
class _Resolution:
    validate: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]
    finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]
    approve_scoring: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]
    human_inputs: Optional[List[Dict[str, Any]]]
    completed: threading.Event


class HitlManagerToolExecutor:
    """Runtime-mediated tools available to the manager's normal ReAct loop."""

    def __init__(self, manager: "HitlManager") -> None:
        self.manager = manager
        self.workspace = HitlWorkspaceInspector(manager.work_dir)

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        handlers = {
            "list_workspace": self._list_workspace,
            "find_workspace_files": self._find_workspace_files,
            "search_workspace": self._search_workspace,
            "read_workspace_file": self._read_workspace_file,
            "hitl-view-ideas": self._view_ideas,
            "recall_manager_conversation": self._recall,
            "list_frontier": self._list_frontier,
            "view_node": self._view_node,
            "select_frontier": self._select_frontier,
            "answer_to_human": self._answer_to_human,
            "ask_human": self._ask_human,
            "update_research_state": self._update_research_state,
            "design_panel": self._design_panel,
            "finalize_worker_request": self._finalize_worker_request,
            "approve_for_scoring": self._approve_for_scoring,
            "finalize_frontier_decision": self._finalize_frontier_decision,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return f"Error: Unknown HITL manager tool '{tool_name}'. Inspect the available tools and retry."
        try:
            return handler(arguments)
        except Exception as exc:
            return (
                f"Error executing {tool_name}: {exc}. Correct the request and retry this tool call."
            )

    def _list_workspace(self, args: Dict[str, Any]) -> str:
        return self.workspace.list_workspace(str(args.get("path", ".")))

    def _find_workspace_files(self, args: Dict[str, Any]) -> str:
        return self.workspace.find_workspace_files(
            str(args.get("pattern", "")), str(args.get("path", "."))
        )

    def _search_workspace(self, args: Dict[str, Any]) -> str:
        return self.workspace.search_workspace(
            str(args.get("pattern", "")),
            str(args.get("path", ".")),
            args.get("glob"),
            args.get("case_insensitive", False),
        )

    def _read_workspace_file(self, args: Dict[str, Any]) -> str:
        return self.workspace.read_workspace_file(
            str(args.get("path", "")),
            args.get("offset", 1),
            args.get("limit", 200),
        )

    def _view_ideas(self, args: Dict[str, Any]) -> str:
        from core.hitl import HitlIdeaLog, HitlValidationError

        idea_id = str(args.get("idea_id", "")).strip()
        try:
            return HitlIdeaLog(self.manager.work_dir).render_for_agent(idea_id=idea_id or None)
        except HitlValidationError as exc:
            return f"Error: {exc}. Call hitl-view-ideas without an id to inspect available records."

    def _recall(self, args: Dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "Error: recall_manager_conversation requires a concrete query. Retry with relevant terms."
        return self.manager.conversation.recall(query, limit=int(args.get("limit", 4)))

    def _list_frontier(self, _args: Dict[str, Any]) -> str:
        from core.hitl_frontier import HitlFrontierStore

        return json.dumps(
            HitlFrontierStore(self.manager.work_dir).state(), ensure_ascii=False, indent=2
        )

    def _view_node(self, args: Dict[str, Any]) -> str:
        from core.hitl_frontier import HitlFrontierStore

        node_sha = str(args.get("node_sha", "")).strip()
        if not node_sha:
            return "Error: view_node requires node_sha. Call list_frontier, then retry."
        return json.dumps(
            HitlFrontierStore(self.manager.work_dir).node(node_sha), ensure_ascii=False, indent=2
        )

    def _select_frontier(self, args: Dict[str, Any]) -> str:
        node_sha = str(args.get("node_sha", "")).strip()
        if not node_sha:
            return "Error: select_frontier requires node_sha. Call list_frontier, then retry."
        return self.manager.select_frontier(node_sha)

    def _answer_to_human(self, args: Dict[str, Any]) -> str:
        message = str(args.get("message", "")).strip()
        if not message:
            return "Error: answer_to_human requires a non-empty message. Retry with the message to send."
        self.manager.channel.send(message, kind="manager")
        self.manager.conversation.append("manager", message)
        return "Manager message delivered. A later human message will begin a normal manager turn."

    def _ask_human(self, args: Dict[str, Any]) -> str:
        message = str(args.get("message", "")).strip()
        if not message:
            return "Error: ask_human requires a non-empty question. Retry with a concise question."
        options = args.get("options") or []
        if not isinstance(options, list):
            return (
                "Error: ask_human options must be an array of strings. Correct the call and retry."
            )
        return self.manager.ask_human(message, [str(value) for value in options])

    def _update_research_state(self, args: Dict[str, Any]) -> str:
        from core.hitl_world_model import HitlWorldModelSync

        with HitlWorldModelSync(self.manager.work_dir).synchronized_research_state() as research:
            research.set_fields(
                narrative=str(args.get("narrative", "")) or None,
                crux=str(args.get("crux", "")) or None,
            )
            hypotheses = args.get("hypotheses") or []
            if isinstance(hypotheses, list):
                for hypothesis in hypotheses:
                    if isinstance(hypothesis, dict):
                        research.upsert_hypothesis(
                            str(hypothesis.get("statement", "")),
                            status=str(hypothesis.get("status", "alive")),
                            evidence=str(hypothesis.get("evidence", "")),
                            hid=str(hypothesis.get("id", "")) or None,
                        )
            if isinstance(args.get("open_questions"), list):
                research.set_open_questions([str(value) for value in args["open_questions"]])
            if isinstance(args.get("resolved_questions"), list):
                research.resolve_questions([str(value) for value in args["resolved_questions"]])
        return "ResearchState synthesis updated. Runtime-derived ideas, frontier, and whiteboard remain synchronized separately."

    def _design_panel(self, args: Dict[str, Any]) -> str:
        from core.hitl_world_model import HitlWorldModelSync

        with HitlWorldModelSync(self.manager.work_dir).synchronized_research_state() as research:
            layout = args.get("layout")
            if layout is not None:
                if not isinstance(layout, list):
                    return (
                        "Error: design_panel layout must be an array. Correct the call and retry."
                    )
                research.set_panel_layout([str(item) for item in layout])
            sections = args.get("sections") or []
            if not isinstance(sections, list):
                return "Error: design_panel sections must be an array. Correct the call and retry."
            for section in sections:
                if not isinstance(section, dict) or not str(section.get("id", "")).strip():
                    return "Error: every design_panel section requires an id. Correct the call and retry."
                research.upsert_section(
                    str(section["id"]),
                    title=section.get("title"),
                    kind=section.get("kind"),
                    data=section.get("data"),
                )
        return "Research panel updated."

    def _finalize_worker_request(self, args: Dict[str, Any]) -> str:
        payload = args.get("result", args)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return "Error: finalize_worker_request requires a JSON result object. Correct it and retry."
        if not isinstance(payload, dict):
            return "Error: finalize_worker_request requires a result object. Correct it and retry."
        return self.manager.finalize_worker_request(dict(payload))

    def _approve_for_scoring(self, args: Dict[str, Any]) -> str:
        return self.manager.approve_for_scoring(str(args.get("context", "")).strip())

    def _finalize_frontier_decision(self, args: Dict[str, Any]) -> str:
        payload = args.get("result", args)
        if not isinstance(payload, dict):
            return "Error: finalize_frontier_decision requires an object. Correct it and retry."
        return self.manager.finalize_worker_request(dict(payload))


class HitlManager:
    """One long-running, queued ReAct manager for an HITL workspace."""

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        work_dir: Optional[Path] = None,
        channel: Optional[Any] = None,
    ):
        from interactive.channel import TerminalChannel
        from interactive.llm_backend import create_backend
        from interactive.research_state import ResearchState
        from core.hitl_manager_context import HitlManagerTranscript
        from core.hitl_world_model import HitlWorldModelSync

        if work_dir is None:
            raise ValueError("HITL manager requires a workspace")
        self.config = config
        self.work_dir = Path(work_dir)
        self.backend = create_backend(config)
        self.channel = channel or TerminalChannel()
        self.runtime_state = HitlRuntimeState(self.work_dir)
        self.conversation = HitlManagerTranscript(
            self.work_dir / ".neurico" / "hitl" / "manager",
            context_tokens=int(
                config.get("manager", {}).get("hitl_manager_conversation_tokens", 16000)
            ),
        )
        self.research = ResearchState(self.work_dir)
        self.world_model = HitlWorldModelSync(self.work_dir)
        self.world_model.reconcile(self.research)
        self.tool_definitions = self._load_tools()
        self.max_react_turns = int(config.get("manager", {}).get("hitl_manager_max_turns", 12))
        self.max_backend_retries = max(
            1, int(config.get("manager", {}).get("hitl_manager_backend_retries", 3))
        )
        self.backend_retry_delay_seconds = max(
            0.1,
            float(config.get("manager", {}).get("hitl_manager_retry_delay_seconds", 1.0)),
        )
        self._turns: "queue.Queue[_Turn]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._resolutions: Dict[str, _Resolution] = {}
        self._resolution_lock = threading.RLock()
        self._turn_lock = threading.RLock()
        self._generation_lock = threading.Lock()
        self._generation = 0
        self._defer_current_turn = False
        register = getattr(self.channel, "set_resolution_reply_handler", None)
        if callable(register):
            register(self.submit_resolution_reply)

    @staticmethod
    def _load_tools() -> List[Dict[str, Any]]:
        import yaml

        path = (
            Path(__file__).resolve().parents[2]
            / "templates"
            / "hitl"
            / "interactive_manager_tools.yaml"
        )
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [
            HitlManager._provider_tool_definition(tool) for tool in list(payload.get("tools") or [])
        ]

    @staticmethod
    def _provider_tool_definition(raw_tool: Dict[str, Any]) -> Dict[str, Any]:
        """Convert HITL's readable YAML fields into provider JSON Schema."""
        if not isinstance(raw_tool, dict):
            raise ValueError("HITL manager tool definitions must be objects.")
        tool = dict(raw_tool)
        parameters = tool.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError("HITL manager tool parameters must be an object.")
        if parameters.get("type") == "object":
            tool["parameters"] = parameters
            return tool

        properties: Dict[str, Any] = {}
        required: List[str] = []
        for name, field in parameters.items():
            if not isinstance(field, dict):
                raise ValueError(f"HITL manager tool field '{name}' must be an object.")
            properties[str(name)] = {
                key: value for key, value in field.items() if key != "required"
            }
            if bool(field.get("required")):
                required.append(str(name))
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        tool["parameters"] = schema
        return tool

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="neurico-hitl-manager")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._turns.put(_Turn("runtime", ""))
        if self._thread is not None:
            self._thread.join(timeout=1)

    def reload_after_runtime_restore(self) -> None:
        """Discard failed-attempt manager caches after private Git rollback."""
        from interactive.research_state import ResearchState

        self._invalidate_turns()
        with self._turn_lock:
            self.conversation.reload()
            self.research = ResearchState(self.work_dir)
            self.world_model.reconcile(self.research)

    def abandon_worker_request_for_rollback(self, reason: str) -> None:
        """Wake a held request before runtime discards its attempt state."""
        # Invalidate first, while the rollback boundary still contains the
        # failed attempt. This prevents an in-flight provider response from
        # writing into the restored private state.
        self._invalidate_turns()
        pending = self.runtime_state.pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") == "resolved":
            return
        request_key = str(pending.get("request_key", "")).strip()
        if not request_key:
            return
        self.runtime_state.cancel_pending_worker_command(request_key, reason=reason)
        clear_request = getattr(self.channel, "clear_resolution_request", None)
        if callable(clear_request):
            clear_request()
        with self._resolution_lock:
            resolution = self._resolutions.get(request_key)
            if resolution is not None:
                resolution.completed.set()

    def chat(self, message: str) -> str:
        turn = self._new_turn("human", str(message), done=threading.Event())
        self.start()
        self._turns.put(turn)
        turn.done.wait()
        if turn.error is not None:
            raise turn.error
        return turn.reply

    def notify_runtime(self, message: str) -> None:
        self.start()
        self._turns.put(self._new_turn("runtime", message, requires_worker_resolution=True))

    def request_worker_resolution(
        self,
        *,
        command: Dict[str, Any],
        prompt: str,
        validate: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        approve_scoring: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        human_inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        pending = self.runtime_state.begin_worker_command(command)
        request_key = str(pending["request_key"])
        if pending.get("status") == "resolved" and isinstance(pending.get("response"), dict):
            return dict(pending["response"])
        with self._resolution_lock:
            if human_inputs is not None and pending.get("human_replies"):
                human_inputs[:] = list(pending.get("human_replies") or [])
            self._resolutions[request_key] = _Resolution(
                validate=validate,
                finalize=finalize,
                approve_scoring=approve_scoring,
                human_inputs=human_inputs,
                completed=threading.Event(),
            )
        human_question = pending.get("human_question")
        if isinstance(human_question, dict):
            presenter = getattr(self.channel, "present_resolution_request", None)
            if callable(presenter):
                presenter(
                    str(human_question.get("message", "")).strip(),
                    list(human_question.get("options") or []),
                )
        else:
            self.notify_runtime(prompt)
        resolution = self._resolutions[request_key]
        resolution.completed.wait()
        completed = self.runtime_state.pending_worker_command()
        if isinstance(completed, dict) and completed.get("request_key") == request_key:
            if completed.get("status") == "cancelled":
                raise HitlRuntimeStateError(
                    "Runtime cancelled the held worker command while rolling back its failed attempt."
                )
        if not isinstance(completed, dict) or completed.get("request_key") != request_key:
            raise HitlRuntimeStateError("Runtime lost the pending worker command before release")
        response = completed.get("response")
        if not isinstance(response, dict):
            raise HitlRuntimeStateError("Worker command was released without a runtime response")
        return dict(response)

    def wait_for_worker_request(self, request_key: str) -> Dict[str, Any]:
        """Wait for an already-attached worker request to receive its response."""
        while True:
            pending = self.runtime_state.pending_worker_command()
            if not isinstance(pending, dict) or pending.get("request_key") != request_key:
                raise HitlRuntimeStateError(
                    "Runtime lost the pending worker command before release."
                )
            if pending.get("status") == "resolved":
                response = pending.get("response")
                if not isinstance(response, dict):
                    raise HitlRuntimeStateError("Worker command was resolved without a response.")
                return dict(response)
            if pending.get("status") == "cancelled":
                raise HitlRuntimeStateError(
                    "Runtime cancelled the held worker command while rolling back its failed attempt."
                )
            threading.Event().wait(0.1)

    @staticmethod
    def _request_key(kind: str, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(f"{kind}:{canonical}".encode("utf-8")).hexdigest()

    @staticmethod
    def _require_text(value: Any, field: str, subject: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{subject} requires non-empty {field}.")
        return text

    @staticmethod
    def _human_reply(human_inputs: List[Dict[str, Any]], subject: str) -> str:
        if not human_inputs:
            raise ValueError(f"{subject} requires ask_human before finalization.")
        return str(human_inputs[-1].get("response", "")).strip()

    def review_raised_idea(
        self,
        *,
        pipeline_stage: str,
        raised_idea: Dict[str, Any],
        plan_text: str,
        on_finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from core.hitl import _load_hitl_template, _validate_substantive_options

        human_inputs: List[Dict[str, Any]] = []

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            level = str(data.get("level", "")).strip()
            actor = str(data.get("actor", "")).strip()
            if (level, actor) not in {("B", "manager"), ("A", "human")}:
                raise ValueError("Resolution must use B/manager or A/human.")
            self._require_text(data.get("context"), "context", "Raised-idea resolution")
            self._require_text(
                data.get("manager_feedback"), "manager_feedback", "Raised-idea resolution"
            )
            if actor == "human":
                feedback = self._require_text(
                    data.get("human_feedback"), "human_feedback", "Human resolution"
                )
                if feedback != self._human_reply(human_inputs, "Human resolution"):
                    raise ValueError(
                        "human_feedback must exactly match the latest ask_human response."
                    )
                self._require_text(
                    data.get("manager_escalation_reason"),
                    "manager_escalation_reason",
                    "Human resolution",
                )
            elif human_inputs:
                raise ValueError(
                    "A manager B-level resolution cannot follow ask_human; finalize as A/human."
                )
            if raised_idea.get("idea_type") == "decision":
                self._require_text(data.get("decision"), "decision", "Decision resolution")
                _validate_substantive_options(
                    data.get("options", raised_idea.get("options")),
                    error_prefix="Decision resolution",
                )
            else:
                data.pop("options", None)
                data.pop("decision", None)
            return data

        prompt = _load_hitl_template(
            "manager_review_raised_idea.txt",
            pipeline_stage=pipeline_stage,
            plan_text=plan_text,
            raised_idea_json=json.dumps(raised_idea, indent=2, ensure_ascii=False),
        )
        return self.request_worker_resolution(
            command={
                "request_key": self._request_key("raised_idea", raised_idea),
                "kind": "raised_idea",
                "pipeline_stage": pipeline_stage,
                "hitl_stage": raised_idea.get("hitl_stage", "execution"),
                "raised_idea": raised_idea,
            },
            prompt=prompt,
            validate=validate,
            finalize=on_finalize,
            human_inputs=human_inputs,
        )

    def review_phase_finish(
        self,
        *,
        pipeline_stage: str,
        hitl_stage: str,
        plan_text: str,
        finish_summary: str,
        related_artifacts: List[Dict[str, str]],
        requires_human_approval: bool,
        plan_fingerprint: str = "",
        allow_scoring_approval: bool = False,
        scoring_handoff_context: Optional[Dict[str, Any]] = None,
        on_finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        on_scoring_approval: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from core.hitl import (
            _is_feedback_placeholder,
            _load_hitl_template,
            _normalize_options,
            _resolve_human_decision,
        )

        human_inputs: List[Dict[str, Any]] = []

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            status = str(data.get("status", "")).strip()
            if status not in {"approved", "feedback"}:
                raise ValueError("Phase review status must be approved or feedback.")
            if allow_scoring_approval and status == "approved":
                raise ValueError(
                    "Use approve_for_scoring for this completed AutoResearch candidate."
                )
            if status == "feedback":
                self._require_text(
                    data.get("manager_feedback"), "manager_feedback", "Phase feedback"
                )
            else:
                data["manager_feedback"] = str(data.get("manager_feedback", ""))
            if not requires_human_approval:
                if human_inputs:
                    raise ValueError(
                        "This phase does not require human approval; do not call ask_human."
                    )
                return data
            if not human_inputs:
                if status == "approved":
                    raise ValueError("Call ask_human before approving this plan.")
                return data
            feedback = self._require_text(
                data.get("human_feedback"), "human_feedback", "Human plan review"
            )
            if feedback != self._human_reply(human_inputs, "Human plan review"):
                raise ValueError("human_feedback must exactly match the latest ask_human response.")
            self._require_text(
                data.get("manager_escalation_reason"),
                "manager_escalation_reason",
                "Human plan review",
            )
            decision = _resolve_human_decision(
                feedback, _normalize_options(["Approve plan.", "Provide feedback."])
            )["decision"]
            expected = "approved" if decision == "O1" else "feedback"
            if status != expected:
                raise ValueError("status must match the latest human plan response.")
            if status == "feedback":
                if _is_feedback_placeholder(feedback):
                    raise ValueError("Ask again for concrete plan feedback before finalizing.")
                self._require_text(
                    data.get("manager_feedback"), "manager_feedback", "Human plan feedback"
                )
            return data

        request = {
            "pipeline_stage": pipeline_stage,
            "hitl_stage": hitl_stage,
            "plan_fingerprint": plan_fingerprint,
            "finish_summary": finish_summary,
            "related_artifacts": related_artifacts,
            "provenance": dict(scoring_handoff_context or {}),
        }
        prompt = _load_hitl_template(
            "manager_review_phase_finish.txt",
            pipeline_stage=pipeline_stage,
            hitl_stage=hitl_stage,
            plan_text=plan_text,
            finish_summary=finish_summary,
            related_artifacts_json=json.dumps(related_artifacts, indent=2, ensure_ascii=False),
            requires_human_approval=requires_human_approval,
            allow_scoring_approval=allow_scoring_approval,
        )
        return self.request_worker_resolution(
            command={
                "request_key": self._request_key("phase_finish", request),
                "kind": "phase_finish",
                **request,
            },
            prompt=prompt,
            validate=validate,
            finalize=on_finalize,
            approve_scoring=on_scoring_approval if allow_scoring_approval else None,
            human_inputs=human_inputs,
        )

    def review_proposal(
        self,
        *,
        pipeline_stage: str,
        proposal_text: str,
        on_finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from core.hitl import (
            _is_feedback_placeholder,
            _load_hitl_template,
            _normalize_options,
            _resolve_human_decision,
        )

        human_inputs: List[Dict[str, Any]] = []

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            status = str(data.get("status", "")).strip()
            if status not in {"approved", "feedback", "rejected_illegal"}:
                raise ValueError(
                    "Proposal review status must be approved, feedback, or rejected_illegal."
                )
            self._require_text(data.get("context"), "context", "Proposal admission")
            if status == "rejected_illegal":
                self._require_text(
                    data.get("manager_feedback"), "manager_feedback", "Illegal proposal review"
                )
            else:
                feedback = self._require_text(
                    data.get("human_feedback"), "human_feedback", "Proposal admission"
                )
                if feedback != self._human_reply(human_inputs, "Proposal admission"):
                    raise ValueError(
                        "human_feedback must exactly match the latest ask_human response."
                    )
                self._require_text(
                    data.get("manager_escalation_reason"),
                    "manager_escalation_reason",
                    "Proposal admission",
                )
                decision = _resolve_human_decision(
                    feedback, _normalize_options(["Approve proposal.", "Provide feedback."])
                )["decision"]
                expected = "approved" if decision == "O1" else "feedback"
                if status != expected:
                    raise ValueError("status must match the latest human proposal response.")
                if status == "feedback":
                    if _is_feedback_placeholder(feedback):
                        raise ValueError(
                            "Ask again for concrete proposal feedback before finalizing."
                        )
                    self._require_text(
                        data.get("manager_feedback"), "manager_feedback", "Proposal feedback"
                    )
            if not isinstance(data.get("violations", []), list):
                raise ValueError("violations must be an array.")
            return data

        request = {
            "pipeline_stage": pipeline_stage,
            "proposal": proposal_text,
            **(request_context or {}),
        }
        prompt = _load_hitl_template(
            "manager_review_proposal.txt",
            pipeline_stage=pipeline_stage,
            proposal_text=proposal_text,
        )
        return self.request_worker_resolution(
            command={
                "request_key": self._request_key("proposal", request),
                "kind": "proposal",
                **request,
            },
            prompt=prompt,
            validate=validate,
            finalize=on_finalize,
            human_inputs=human_inputs,
        )

    def review_frontier_candidate(
        self,
        *,
        parent_node_sha: str,
        candidate_node_sha: str,
        proposal_idea_id: str,
        proposal_type: str,
        objective_score: Dict[str, Any],
        on_finalize: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        from core.hitl import _load_hitl_template

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            action = str(data.get("action", "")).strip()
            if action not in {"accept", "reject"}:
                raise ValueError("Frontier action must be accept or reject.")
            return {
                "action": action,
                "reason": self._require_text(data.get("reason"), "reason", "Frontier decision"),
            }

        prompt = _load_hitl_template(
            "manager_frontier_decision.txt",
            proposal_idea_id=proposal_idea_id,
            proposal_type=proposal_type,
            objective_score_json=json.dumps(objective_score, ensure_ascii=False, indent=2),
        )
        return self.resume_worker_request(prompt=prompt, validate=validate, finalize=on_finalize)

    def review_scoring_failure(
        self,
        *,
        scorer_result: Dict[str, Any],
        score_validation: Dict[str, Any],
        on_finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from core.hitl import _load_hitl_template

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            if str(data.get("status", "")).strip() != "feedback":
                raise ValueError("An invalid objective score requires status='feedback'.")
            return {
                "status": "feedback",
                "context": self._require_text(data.get("context"), "context", "Scoring repair"),
                "manager_feedback": self._require_text(
                    data.get("manager_feedback"), "manager_feedback", "Scoring repair"
                ),
            }

        return self.resume_worker_request(
            prompt=_load_hitl_template(
                "manager_review_scoring_failure.txt",
                scorer_result_json=json.dumps(scorer_result, ensure_ascii=False, indent=2),
                score_validation_json=json.dumps(score_validation, ensure_ascii=False, indent=2),
            ),
            validate=validate,
            finalize=on_finalize,
        )

    def review_initial_scoring_result(
        self,
        *,
        scorer_result: Dict[str, Any],
        on_finalize: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        from core.hitl import _load_hitl_template

        def validate(data: Dict[str, Any]) -> Dict[str, Any]:
            status = str(data.get("status", "")).strip()
            if status not in {"approved", "feedback"}:
                raise ValueError("Initial score review status must be approved or feedback.")
            if status == "approved" and not bool(scorer_result.get("success")):
                raise ValueError("Runtime scorer is invalid; return repair feedback instead.")
            result = {
                "status": status,
                "context": self._require_text(
                    data.get("context"), "context", "Initial score review"
                ),
                "manager_feedback": str(data.get("manager_feedback", "")).strip(),
            }
            if status == "feedback":
                result["manager_feedback"] = self._require_text(
                    result["manager_feedback"], "manager_feedback", "Initial score repair"
                )
            return result

        return self.resume_worker_request(
            prompt=_load_hitl_template(
                "manager_review_initial_scoring.txt",
                scorer_result_json=json.dumps(scorer_result, ensure_ascii=False, indent=2),
            ),
            validate=validate,
            finalize=on_finalize,
        )

    def submit_resolution_reply(self, response: str) -> None:
        pending = self.runtime_state.record_human_reply(response)
        request_key = str(pending["request_key"])
        with self._resolution_lock:
            resolution = self._resolutions.get(request_key)
            if resolution and resolution.human_inputs is not None:
                resolution.human_inputs[:] = list(pending.get("human_replies") or [])
        self.start()
        self._turns.put(
            self._new_turn("human", str(response).strip(), requires_worker_resolution=True)
        )

    def resume_worker_request(
        self,
        *,
        prompt: str,
        validate: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        finalize: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Attach the next runtime step to the same held worker command.

        Objective scoring is asynchronous from the manager's point of view. The
        worker remains inside its original command while runtime later adds a
        score result to the normal conversation and installs the next valid
        finalizer for that same command.
        """
        pending = self.runtime_state.pending_worker_command()
        if not isinstance(pending, dict):
            raise HitlRuntimeStateError("No pending worker command exists to resume.")
        request_key = str(pending.get("request_key", "")).strip()
        if not request_key:
            raise HitlRuntimeStateError("Pending worker command is missing request_key.")
        with self._resolution_lock:
            resolution = self._resolutions.get(request_key)
            if resolution is None:
                resolution = _Resolution(
                    validate=validate,
                    finalize=finalize,
                    approve_scoring=None,
                    human_inputs=list(pending.get("human_replies") or []),
                    completed=threading.Event(),
                )
                self._resolutions[request_key] = resolution
            else:
                resolution.validate = validate
                resolution.finalize = finalize
        self.runtime_state.update_pending_worker_command(request_key, status="pending")
        self.notify_runtime(prompt)
        resolution.completed.wait()
        completed = self.runtime_state.pending_worker_command()
        if isinstance(completed, dict) and completed.get("request_key") == request_key:
            if completed.get("status") == "cancelled":
                raise HitlRuntimeStateError(
                    "Runtime cancelled the resumed worker command while rolling back its failed attempt."
                )
        if not isinstance(completed, dict) or completed.get("request_key") != request_key:
            raise HitlRuntimeStateError("Runtime lost the resumed worker command before release.")
        response = completed.get("response")
        if not isinstance(response, dict):
            raise HitlRuntimeStateError("Resumed worker command was released without a response.")
        return dict(response)

    def ask_human(self, message: str, options: List[str]) -> str:
        pending = self.runtime_state.pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") != "pending":
            return "Error: ask_human is available only while runtime has a pending worker command."
        request_key = str(pending["request_key"])
        self.runtime_state.request_human_reply(request_key, message=message, options=options)
        presenter = getattr(self.channel, "present_resolution_request", None)
        if not callable(presenter):
            return "Error: the current manager interface cannot present an explicit resolution request."
        presenter(message, options or None)
        self.conversation.append("manager", message)
        self._defer_current_turn = True
        return "The explicit human-resolution request was displayed. Continue ordinary conversation; the worker remains held by runtime."

    def finalize_worker_request(self, result: Dict[str, Any]) -> str:
        pending = self.runtime_state.pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") != "pending":
            return "Error: no pending worker command exists to finalize."
        request_key = str(pending["request_key"])
        with self._resolution_lock:
            resolution = self._resolutions.get(request_key)
        if resolution is None:
            return "Error: runtime has not attached a finalizer for this pending command. Preserve the request and retry after runtime recovers it."
        candidate = dict(result)
        try:
            if resolution.validate is not None:
                candidate = resolution.validate(candidate)
            if resolution.finalize is not None:
                candidate = resolution.finalize(candidate)
        except Exception as exc:
            return f"Error: runtime rejected this finalization: {exc}. Correct the result and retry finalize_worker_request."
        self.runtime_state.complete_worker_command(request_key, candidate)
        resolution.completed.set()
        return "Runtime finalized the worker command and released its response."

    def approve_for_scoring(self, context: str) -> str:
        pending = self.runtime_state.pending_worker_command()
        if not isinstance(pending, dict) or pending.get("status") != "pending":
            return "Error: no pending worker command is ready for scoring approval."
        request_key = str(pending["request_key"])
        with self._resolution_lock:
            resolution = self._resolutions.get(request_key)
        if resolution is None or resolution.approve_scoring is None:
            return "Error: scoring approval is unavailable for this pending worker command."
        result = {"status": "approved_for_scoring", "context": context, "manager_feedback": ""}
        try:
            self.runtime_state.begin_scoring_handoff(
                request_key,
                context=context,
                review=result,
            )
            resolution.approve_scoring(result)
        except Exception as exc:
            return (
                f"Error: runtime could not start scoring: {exc}. Keep the same approval and retry."
            )
        current = self.runtime_state.pending_worker_command()
        if (
            not isinstance(current, dict)
            or current.get("request_key") != request_key
            or current.get("status") not in {"scoring", "pending"}
        ):
            return (
                "Error: runtime did not persist a restartable scoring handoff. "
                "Keep the same approval and retry."
            )
        self._defer_current_turn = True
        return "Runtime started objective scoring. The worker remains held until runtime returns the score and you finalize the next step."

    def select_frontier(self, node_sha: str) -> str:
        action = self.runtime_state.snapshot().get("next_autoresearch_action")
        if not isinstance(action, dict) or action.get("kind") != "select_frontier":
            return "Error: select_frontier is available only at the runtime frontier-selection boundary."
        callback = action.get("callback")
        if callback is not None:
            return "Error: persisted frontier action is invalid; runtime must recover it before selection."
        handler = getattr(self, "_frontier_selector", None)
        if not callable(handler):
            return "Error: runtime has not attached frontier selection for this boundary."
        try:
            result = handler(node_sha)
            self.runtime_state.complete_next_autoresearch_action("select_frontier", result)
        except Exception as exc:
            return f"Error: runtime could not select this frontier node: {exc}. Inspect the frontier and retry."
        return "Runtime persisted the selected frontier node. The next proposal may begin."

    def begin_frontier_selection(
        self, prompt: str, selector: Callable[[str], Dict[str, Any]]
    ) -> Dict[str, Any]:
        action = self.runtime_state.begin_next_autoresearch_action({"kind": "select_frontier"})
        if action.get("status") == "resolved" and isinstance(action.get("result"), dict):
            result = dict(action["result"])
            self.runtime_state.clear_completed_next_autoresearch_action("select_frontier")
            return result
        self._frontier_selector = selector
        self.notify_runtime(prompt)
        # The controller waits until select_frontier clears the action.
        while True:
            current = self.runtime_state.snapshot().get("next_autoresearch_action")
            if (
                isinstance(current, dict)
                and current.get("kind") == "select_frontier"
                and current.get("status") == "resolved"
            ):
                result = dict(current.get("result") or {})
                self.runtime_state.clear_completed_next_autoresearch_action("select_frontier")
                return result
            threading.Event().wait(0.1)

    def select_frontier_for_next_proposal(
        self,
        *,
        on_select: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        from core.hitl import _load_hitl_template

        def selector(node_sha: str) -> Dict[str, Any]:
            from core.autoresearch import CheckpointManager
            from core.hitl_frontier import HitlFrontierStore

            store = HitlFrontierStore(self.work_dir)
            state = store.state()
            if node_sha not in state["active_frontier_node_shas"]:
                raise ValueError("Only an active frontier node can be selected.")
            checkpoints = CheckpointManager(self.work_dir)
            if not checkpoints.checkpoint_exists(node_sha):
                raise ValueError("The selected frontier node is not a valid workspace checkpoint.")
            previous = state["selected_frontier_node_sha"]
            try:
                checkpoints.restore_checkpoint(node_sha, clean_untracked_public=True)
                state = store.select(node_sha)
                return on_select(
                    {
                        "selected_frontier_node_sha": state["selected_frontier_node_sha"],
                        "active_frontier_node_shas": state["active_frontier_node_shas"],
                    }
                )
            except Exception:
                checkpoints.restore_checkpoint(previous, clean_untracked_public=True)
                store.select(previous)
                raise

        return self.begin_frontier_selection(
            _load_hitl_template("manager_select_frontier.txt"), selector
        )

    def _current_generation(self) -> int:
        with self._generation_lock:
            return self._generation

    def _generation_is_current(self, generation: int) -> bool:
        return generation == self._current_generation()

    def _invalidate_turns(self) -> None:
        """Fence manager work that belongs to a discarded runtime boundary."""
        # Acquire the short mutation lock before advancing the generation. A
        # turn already mutating durable context finishes before rollback; a
        # provider call runs outside this lock and observes the new generation
        # before it can append its eventual response.
        with self._turn_lock:
            with self._generation_lock:
                self._generation += 1

    def _new_turn(
        self,
        speaker: str,
        content: str,
        *,
        requires_worker_resolution: bool = False,
        done: Optional[threading.Event] = None,
    ) -> _Turn:
        return _Turn(
            speaker,
            content,
            requires_worker_resolution=requires_worker_resolution,
            done=done,
            generation=self._current_generation(),
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            turn = self._turns.get()
            if self._stop.is_set():
                break
            if not turn.content:
                continue
            try:
                if not self._generation_is_current(turn.generation):
                    continue
                turn.reply = self._run_turn(
                    turn.speaker,
                    turn.content,
                    record_input=not turn.input_recorded,
                    generation=turn.generation,
                )
                if (
                    self._generation_is_current(turn.generation)
                    and turn.requires_worker_resolution
                    and not self._defer_current_turn
                    and self.runtime_state.pending_worker_command() is not None
                ):
                    # The manager remains a normal interactive agent, but a
                    # runtime-held worker request cannot be resolved by prose
                    # alone. Ask for the next ReAct turn instead of silently
                    # abandoning the request after a text-only response.
                    reminder = _Turn(
                        "runtime",
                        "The worker request remains unresolved. Use the available tools to inspect it, ask the human if needed, or finalize it with a valid runtime result.",
                        requires_worker_resolution=True,
                        generation=turn.generation,
                    )
                    timer = threading.Timer(
                        self.backend_retry_delay_seconds,
                        self._turns.put,
                        args=(reminder,),
                    )
                    timer.daemon = True
                    timer.start()
            except BaseException as exc:
                if (
                    turn.speaker == "runtime"
                    and not self._stop.is_set()
                    and self._generation_is_current(turn.generation)
                ):
                    # A runtime request must not be dropped because a provider
                    # is briefly unavailable.  Preserve the held worker request
                    # and retry the same conversation turn without duplicating
                    # its original runtime message in the transcript.
                    turn.input_recorded = True
                    turn.retry_count += 1
                    if turn.retry_count == 1:
                        self.channel.send(
                            "The HITL manager is temporarily unavailable. The worker request remains held and runtime will retry.",
                            kind="system",
                        )
                    delay = min(
                        30.0, self.backend_retry_delay_seconds * (2 ** min(turn.retry_count - 1, 5))
                    )
                    timer = threading.Timer(delay, self._turns.put, args=(turn,))
                    timer.daemon = True
                    timer.start()
                    continue
                turn.error = exc
            finally:
                if turn.done is not None:
                    turn.done.set()

    def _run_turn(
        self,
        speaker: str,
        content: str,
        *,
        record_input: bool = True,
        generation: int,
    ) -> str:
        with self._turn_lock:
            if not self._generation_is_current(generation):
                return ""
            self._defer_current_turn = False
            self.world_model.reconcile(self.research)
            if record_input:
                self.conversation.append(speaker, content)
        executor = HitlManagerToolExecutor(self)
        final_text = ""
        for _ in range(self.max_react_turns):
            with self._turn_lock:
                if not self._generation_is_current(generation):
                    return ""
                try:
                    messages = self._messages(generation)
                except _StaleManagerTurn:
                    return ""
            response = self._send(messages, self.tool_definitions)
            with self._turn_lock:
                if not self._generation_is_current(generation):
                    return ""
                text = str(getattr(response, "text", "")).strip()
                if text:
                    self.conversation.append("manager", text)
                    final_text = text
                calls = list(getattr(response, "tool_calls", []) or [])
                if not calls:
                    return final_text
                for call in calls:
                    if not self._generation_is_current(generation):
                        return ""
                    self.conversation.append_tool_call(
                        call_id=call.id, name=call.name, arguments=call.arguments
                    )
                    result = executor.execute(call.name, call.arguments)
                    if not self._generation_is_current(generation):
                        return ""
                    self.conversation.append_tool_result(
                        call_id=call.id, tool_name=call.name, content=result
                    )
                    if self._defer_current_turn:
                        return final_text
        return final_text

    def _messages(self, generation: int) -> List[Dict[str, Any]]:
        from core.hitl import _load_hitl_template

        self.world_model.reconcile(self.research)
        conversation = self.conversation.prepare(
            research_state=self.research.digest_section(),
            summarize=lambda prior, state: self._summarize(prior, state, generation),
        )
        return [
            {
                "role": "system",
                "content": _load_hitl_template("interactive_manager_system.txt")
                + self.research.digest_section(),
            },
            {"role": "user", "content": "Chronological manager conversation:\n" + conversation},
        ]

    def _summarize(self, prior: str, research_state: str, generation: int) -> str:
        from core.hitl import _load_hitl_template

        prompt = _load_hitl_template(
            "manager_conversation_compaction.txt",
            research_state=research_state,
            prior_conversation=prior,
            max_tokens=6000,
        )
        response = self._send([{"role": "system", "content": prompt}], [])
        if not self._generation_is_current(generation):
            raise _StaleManagerTurn()
        text = str(getattr(response, "text", "")).strip()
        if not text:
            raise RuntimeError("Manager returned an empty conversation summary")
        return text

    def _send(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        last: Optional[Exception] = None
        for _ in range(self.max_backend_retries):
            try:
                return self.backend.send(messages, tools)
            except Exception as exc:
                last = exc
        raise RuntimeError("Manager backend was unavailable") from last
