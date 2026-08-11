"""Presentation-only terminal UI for the HITL manager client."""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


_ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "mint": "\x1b[38;5;115m",
    "blue": "\x1b[38;5;111m",
    "amber": "\x1b[38;5;221m",
    "red": "\x1b[38;5;203m",
    "muted": "\x1b[38;5;246m",
    "rule": "\x1b[38;5;239m",
}


TERMINAL_STYLE = Style.from_dict(
    {
        "prompt": "bold #8bd5ca",
        "rprompt": "#7f8c8d",
        "status": "bg:#17201e #d8e2df",
        "status.review": "bg:#332b16 #f1c75b bold",
        "status.failed": "bg:#3a2024 #f28b82 bold",
        "status.complete": "bg:#173128 #82d7bd bold",
        "status.timer": "bg:#17201e #95a39f",
    }
)


def terminal_key_bindings() -> KeyBindings:
    """Keep an empty Enter inside the active composer instead of submitting it."""
    bindings = KeyBindings()

    @bindings.add("c-j")
    @bindings.add("c-m")
    def accept_nonempty(event: Any) -> None:
        if event.current_buffer.text.strip():
            event.current_buffer.validate_and_handle()

    return bindings


class HitlTerminalUI:
    """Render shared HITL projections without interpreting workflow state."""

    def __init__(
        self,
        *,
        interactive: bool,
        width: Callable[[], int] | None = None,
    ) -> None:
        self.interactive = interactive
        self._width = width or self._terminal_width

    @staticmethod
    def _terminal_width() -> int:
        return shutil.get_terminal_size((100, 24)).columns

    @property
    def content_width(self) -> int:
        return max(24, min(100, self._width() - 4))

    def _style(self, text: str, *styles: str) -> str:
        if not self.interactive or not text:
            return text
        prefix = "".join(_ANSI[style] for style in styles)
        return f"{prefix}{text}{_ANSI['reset']}"

    def _rule(self, width: int | None = None) -> str:
        return self._style("─" * (width or self.content_width), "rule")

    @staticmethod
    def _middle_ellipsis(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        if limit < 9:
            return f"{text[: max(1, limit - 1)]}…"
        tail = min(12, (limit - 1) // 3)
        head = limit - tail - 1
        return f"{text[:head]}…{text[-tail:]}"

    @staticmethod
    def _clean_inline_markdown(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        return text

    def _wrap_paragraph(self, text: str, *, indent: str = "  ") -> List[str]:
        cleaned = self._clean_inline_markdown(" ".join(text.split()))
        if not cleaned:
            return []
        return textwrap.wrap(
            cleaned,
            width=self.content_width,
            initial_indent=indent,
            subsequent_indent=indent,
            break_long_words=False,
            break_on_hyphens=False,
        )

    def _render_body(self, text: str) -> List[str]:
        """Render common conversational Markdown as restrained terminal text."""
        rendered: List[str] = []
        paragraph: List[str] = []
        in_code = False

        def flush_paragraph() -> None:
            if paragraph:
                rendered.extend(self._wrap_paragraph(" ".join(paragraph)))
                paragraph.clear()

        for raw_line in str(text).splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped.startswith("```"):
                flush_paragraph()
                in_code = not in_code
                continue
            if in_code:
                rendered.append(self._style(f"    {line}", "blue"))
                continue
            if not stripped:
                flush_paragraph()
                if rendered and rendered[-1] != "":
                    rendered.append("")
                continue
            heading = re.match(r"^#{1,6}\s+(.+)$", stripped)
            bullet = re.match(r"^[-*]\s+(.+)$", stripped)
            numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
            if heading:
                flush_paragraph()
                rendered.append(self._style(f"  {self._clean_inline_markdown(heading.group(1))}", "bold"))
            elif bullet:
                flush_paragraph()
                wrapped = textwrap.wrap(
                    self._clean_inline_markdown(bullet.group(1)),
                    width=self.content_width - 2,
                    initial_indent="  • ",
                    subsequent_indent="    ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                rendered.extend(wrapped)
            elif numbered:
                flush_paragraph()
                marker = f"  {numbered.group(1)}. "
                rendered.extend(
                    textwrap.wrap(
                        self._clean_inline_markdown(numbered.group(2)),
                        width=self.content_width - 2,
                        initial_indent=marker,
                        subsequent_indent=" " * len(marker),
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                )
            else:
                paragraph.append(stripped)
        flush_paragraph()
        while rendered and rendered[-1] == "":
            rendered.pop()
        return rendered or ["  "]

    def startup(self, workspace: Path | None, live: Dict[str, Any]) -> List[str]:
        name = workspace.name if workspace is not None else "workspace"
        name = self._middle_ellipsis(name, max(16, self.content_width - 12))
        label = str(live.get("label") or live.get("title") or "Ready").strip()
        heading = f"NeuriCo  ·  {name}"
        hint = "/status for details  ·  /help for commands"
        if not bool(live.get("active")):
            hint = "/run to start  ·  /help for commands"
        return [
            self._style(heading, "bold", "mint"),
            f"{self._style(label, 'bold')}  {self._style(f'·  {hint}', 'muted')}",
            self._rule(),
        ]

    def conversation(self, speaker: str, text: str) -> List[str]:
        label = "You" if speaker == "human" else "NeuriCo"
        label_style = "blue" if speaker == "human" else "mint"
        return [self._style(label, "bold", label_style), *self._render_body(text)]

    def system(self, text: str, *, tone: str = "neutral") -> List[str]:
        color = {"error": "red", "success": "mint", "review": "amber"}.get(tone, "muted")
        wrapped = textwrap.wrap(
            " ".join(str(text).split()),
            width=self.content_width - 2,
            initial_indent="  ",
            subsequent_indent="  ",
            break_long_words=False,
            break_on_hyphens=False,
        )
        if not wrapped:
            return []
        wrapped[0] = f"{self._style('●', color)}{wrapped[0][1:]}"
        return wrapped

    def request(
        self,
        request: Dict[str, Any],
        *,
        live: Dict[str, Any],
        actionable: bool,
    ) -> List[str]:
        stage = str(live.get("stage_label") or "Research").strip()
        phase = str(live.get("phase_label") or "Review").strip()
        context = " / ".join(part for part in (stage, phase) if part)
        heading = "Review needed"
        heading_with_context = f"{heading}  ·  {context}" if context else heading
        lines = [self._rule()]
        if len(heading_with_context) <= self.content_width:
            lines.append(self._style(heading_with_context, "bold", "amber"))
        else:
            lines.append(self._style(heading, "bold", "amber"))
            if context:
                lines.append(self._style(context, "muted"))
        lines.extend(self._render_body(str(request.get("message", ""))))
        options = list(request.get("options") or [])
        if options:
            lines.append("")
            for index, option in enumerate(options, 1):
                option_text = str(option.get("text", "")).strip()
                prefix = f"  {index}  "
                wrapped = textwrap.wrap(
                    option_text,
                    width=self.content_width,
                    initial_indent=prefix,
                    subsequent_indent=" " * len(prefix),
                    break_long_words=False,
                    break_on_hyphens=False,
                ) or [prefix.rstrip()]
                if self.interactive:
                    wrapped[0] = wrapped[0].replace(str(index), self._style(str(index), "amber"), 1)
                lines.extend(wrapped)
        if actionable:
            lines.append("")
            for label, command in (
                ("Choose", "/reply <number>"),
                ("Revise", "/reply <feedback>"),
            ):
                command_text = self._style(command, "bold")
                if len(f"  {label:<8} {command}") <= self.content_width:
                    lines.append(f"  {label:<8} {command_text}")
                else:
                    lines.append(f"  {label}")
                    lines.append(f"    {command_text}")
        lines.append(self._rule())
        return lines

    def idea(self, notification: Dict[str, Any]) -> List[str]:
        idea_id = str(notification.get("idea_id", "")).strip()
        title = str(notification.get("title", "Research update")).strip()
        summary = " ".join(str(notification.get("summary", "")).split())
        if len(summary) > 130:
            summary = f"{summary[:129].rsplit(' ', 1)[0]}…"
        identity = " ".join(part for part in (idea_id, title) if part)
        first = f"{self._style('◆', 'mint')}  {self._style(identity, 'bold')}"
        if not summary:
            return [first]
        return [first, *[self._style(line, "muted") for line in self._wrap_paragraph(summary, indent="   ")]]

    def resolved_request(self, notification: Dict[str, Any]) -> List[str]:
        summary = str(notification.get("summary", "Response recorded.")).strip()
        lines = [f"{self._style('✓', 'mint')}  {self._style('Review resolved', 'bold')}"]
        lines.extend(self._wrap_paragraph(summary, indent="   "))
        return lines

    def activity(self, notifications: Iterable[Dict[str, Any]], *, limit: int = 12) -> List[str]:
        items = list(notifications)[-limit:]
        lines = [self._style("Recent research activity", "bold"), self._rule()]
        if not items:
            lines.append(self._style("  No research activity has been recorded yet.", "muted"))
            return lines
        for item in items:
            kind = str(item.get("kind", "")).strip()
            if kind == "idea":
                idea_id = str(item.get("idea_id", "")).strip()
                title = " ".join(part for part in (idea_id, str(item.get("title", ""))) if part)
            else:
                title = str(item.get("title", "Research update")).strip()
            summary = " ".join(str(item.get("summary", "")).split())
            if len(summary) > 100:
                summary = f"{summary[:99].rsplit(' ', 1)[0]}…"
            entry = f"{title}  {summary}".strip()
            wrapped = textwrap.wrap(
                entry,
                width=self.content_width,
                initial_indent="  • ",
                subsequent_indent="    ",
                break_long_words=False,
                break_on_hyphens=False,
            ) or ["  •"]
            lines.extend(wrapped)
        return lines

    def idea_detail(self, idea: Dict[str, Any]) -> List[str]:
        idea_id = str(idea.get("idea_id", "Idea")).strip()
        idea_type = str(idea.get("idea_type", "idea")).strip().lower()
        level = str(idea.get("level", "?")).strip()
        actor = "Human" if str(idea.get("actor", "")).strip().lower() == "human" else "NeuriCo"
        heading = f"{idea_id}  ·  {idea_type.title()}  ·  Level {level}"
        lines = [self._style(heading, "bold", "mint"), self._style(f"Recorded by {actor}", "muted"), self._rule()]

        def section(label: str, value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            lines.append(self._style(label, "bold"))
            lines.extend(self._render_body(text))

        context = str(idea.get("context", "")).strip()
        if idea_type == "decision":
            selected = str(idea.get("decision", "")).strip()
            for option in idea.get("options") or []:
                if isinstance(option, str):
                    option_id = option_text = option
                elif isinstance(option, dict):
                    option_id = str(option.get("option_id", "")).strip()
                    option_text = str(option.get("text", "")).strip()
                else:
                    continue
                if selected in {option_id, option_text}:
                    selected = option_text or selected
                    break
            section("Decision", selected or idea.get("decision_needed") or context)
            question = str(idea.get("decision_needed", "")).strip()
            if question and question != selected:
                section("Question", question)
        elif idea_type == "proposal":
            proposal = re.sub(
                r"^\s*#?\s*AUTORESEARCH PROPOSAL\s*\n+",
                "",
                str(idea.get("proposal") or context),
                flags=re.IGNORECASE,
            ).strip()
            section("Proposal", proposal)
        else:
            section("Evidence", idea.get("evidence") or idea.get("proposal") or context)

        primary = str(
            idea.get("evidence")
            or idea.get("proposal")
            or idea.get("decision")
            or idea.get("decision_needed")
            or ""
        ).strip()
        if context and context != primary:
            section("Context", context)

        options = list(idea.get("options") or [])
        if options:
            lines.append(self._style("Options", "bold"))
            selected = str(idea.get("decision", "")).strip()
            for option in options:
                if isinstance(option, str):
                    option_id = option_text = option
                elif isinstance(option, dict):
                    option_id = str(option.get("option_id", "")).strip()
                    option_text = str(option.get("text", "")).strip()
                else:
                    continue
                marker = "✓" if selected in {option_id, option_text} else "•"
                wrapped = textwrap.wrap(
                    option_text or option_id,
                    width=self.content_width,
                    initial_indent=f"  {marker} ",
                    subsequent_indent="    ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                lines.extend(wrapped)

        premises = [str(item).strip() for item in idea.get("premises") or [] if str(item).strip()]
        if premises:
            section("Premises", ", ".join(premises))

        artifacts = list(idea.get("related_artifacts") or [])
        if artifacts:
            lines.append(self._style("Artifacts", "bold"))
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    path = str(artifact.get("path", "")).strip()
                    description = str(artifact.get("description", "")).strip()
                else:
                    path, description = str(artifact).strip(), ""
                text = f"{path} — {description}" if description else path
                if text:
                    lines.extend(self._wrap_paragraph(text, indent="  • "))
        return lines

    def expanded_status(self, live: Dict[str, Any]) -> List[str]:
        label = str(live.get("label") or live.get("title") or "Ready").strip()
        detail = str(live.get("detail") or "").strip()
        next_action = str(live.get("next_action") or "").strip()
        elapsed = str(live.get("elapsed") or "").strip()
        heading = label if not elapsed else f"{label}  ·  {elapsed}"
        lines = [self._style("Research status", "bold"), self._rule(), f"  {self._style(heading, 'bold')}"]
        if detail:
            lines.extend(self._wrap_paragraph(detail, indent="  "))
        if next_action:
            lines.extend(self._wrap_paragraph(f"Next: {next_action}", indent="  "))
        return lines

    def help(self) -> List[str]:
        commands = [
            ("/run", "Start or continue research"),
            ("/status", "Show current research status"),
            ("/activity", "Show recent research activity"),
            ("/idea", "Show one idea by ID, for example /idea I7"),
            ("/reply", "Resolve the active review"),
            ("/help", "Show these commands"),
            ("/quit", "Close this client"),
        ]
        lines = [self._style("Commands", "bold"), self._rule()]
        for command, description in commands:
            prefix = f"  {command:<10} "
            wrapped = textwrap.wrap(
                description,
                width=self.content_width,
                initial_indent=prefix,
                subsequent_indent=" " * len(prefix),
                break_long_words=False,
                break_on_hyphens=False,
            ) or [prefix.rstrip()]
            if self.interactive:
                wrapped[0] = wrapped[0].replace(command, self._style(command, "mint"), 1)
            lines.extend(wrapped)
        lines.append(self._style("  Any other text starts a conversation with NeuriCo.", "muted"))
        return lines

    def section(self, title: str) -> List[str]:
        return [self._style(title, "bold"), self._rule()]

    def thinking(self, frame: str) -> str:
        return f"{self._style(frame, 'mint')}  {self._style('NeuriCo is thinking…', 'muted')}"

    @staticmethod
    def prompt_message() -> ANSI:
        return ANSI("\x1b[1;38;5;115m›\x1b[0m ")

    @staticmethod
    def setting_prompt(label: str) -> ANSI:
        return ANSI(f"\x1b[38;5;246m{label}\x1b[0m")

    def toolbar(
        self,
        live: Dict[str, Any],
        *,
        elapsed: str,
    ) -> FormattedText:
        state = str(live.get("state", "idle")).strip()
        label = str(live.get("label") or live.get("title") or "Ready").strip()
        status_class = {
            "review_needed": "class:status.review",
            "failed": "class:status.failed",
            "completed": "class:status.complete",
        }.get(state, "class:status")
        parts: List[tuple[str, str]] = [(status_class, f"  ● {label} ")]
        if elapsed and bool(live.get("active")):
            parts.append(("class:status.timer", f" {elapsed} "))
        return FormattedText(parts)

    def rprompt(self, live: Dict[str, Any]) -> FormattedText:
        if str(live.get("state", "")) == "review_needed":
            return FormattedText([("class:rprompt", "review pending")])
        return FormattedText([])
