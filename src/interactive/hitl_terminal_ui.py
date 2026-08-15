"""Presentation-only terminal UI for the HITL manager client."""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

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


def terminal_safe_text(value: Any) -> str:
    """Make stored content inert while preserving it visibly in terminal output."""
    rendered: List[str] = []
    for character in str(value):
        codepoint = ord(character)
        if character == "\n":
            rendered.append(character)
        elif codepoint < 32 or codepoint == 127 or 0x80 <= codepoint <= 0x9F:
            rendered.append(f"\\x{codepoint:02x}")
        else:
            rendered.append(character)
    return "".join(rendered)


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
        return max(24, self._width() - 4)

    def _style(self, text: str, *styles: str) -> str:
        if not self.interactive or not text:
            return text
        prefix = "".join(_ANSI[style] for style in styles)
        return f"{prefix}{text}{_ANSI['reset']}"

    def _rule(self, width: int | None = None) -> str:
        return self._style("─" * (width or self.content_width), "rule")

    @staticmethod
    def _middle_ellipsis(text: str, limit: int) -> str:
        text = terminal_safe_text(text)
        if len(text) <= limit:
            return text
        if limit < 9:
            return f"{text[: max(1, limit - 1)]}…"
        tail = min(12, (limit - 1) // 3)
        head = limit - tail - 1
        return f"{text[:head]}…{text[-tail:]}"

    @staticmethod
    def _clean_inline_markdown(text: str) -> str:
        text = terminal_safe_text(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        return text

    def _wrap_paragraph(self, text: str, *, indent: str = "  ") -> List[str]:
        cleaned = self._clean_inline_markdown(" ".join(terminal_safe_text(text).split()))
        if not cleaned:
            return []
        if self.interactive:
            return [f"{indent}{cleaned}"]
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

        for raw_line in terminal_safe_text(text).splitlines():
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
                cleaned = self._clean_inline_markdown(bullet.group(1))
                wrapped = [f"  • {cleaned}"] if self.interactive else textwrap.wrap(
                    cleaned, width=self.content_width - 2, initial_indent="  • ",
                    subsequent_indent="    ", break_long_words=False,
                    break_on_hyphens=False,
                )
                rendered.extend(wrapped)
            elif numbered:
                flush_paragraph()
                marker = f"  {numbered.group(1)}. "
                cleaned = self._clean_inline_markdown(numbered.group(2))
                rendered.extend([f"{marker}{cleaned}"] if self.interactive else textwrap.wrap(
                    cleaned, width=self.content_width - 2, initial_indent=marker,
                    subsequent_indent=" " * len(marker), break_long_words=False,
                    break_on_hyphens=False,
                ))
            else:
                paragraph.append(stripped)
        flush_paragraph()
        while rendered and rendered[-1] == "":
            rendered.pop()
        return rendered or ["  "]

    def startup(self, workspace: Path | None, live: Dict[str, Any]) -> List[str]:
        name = workspace.name if workspace is not None else "workspace"
        name = self._middle_ellipsis(name, max(16, self.content_width - 12))
        heading = f"NeuriCo  ·  {name}"
        hint = "/status for details  ·  /help for commands"
        if not bool(live.get("active")):
            hint = "/run to start  ·  /help for commands"
        return [
            self._style(heading, "bold", "mint"),
            self._style(hint, "muted"),
            self._rule(),
        ]

    def conversation(self, speaker: str, text: str) -> List[str]:
        if speaker == "human":
            lines = terminal_safe_text(text).splitlines() or [""]
            return [
                f"{self._style('›', 'bold', 'mint')} {lines[0]}",
                *[f"  {line}" for line in lines[1:]],
            ]
        return [self._style("NeuriCo", "bold", "mint"), *self._render_body(text)]

    def system(self, text: str, *, tone: str = "neutral") -> List[str]:
        color = {"error": "red", "success": "mint", "review": "amber"}.get(tone, "muted")
        cleaned = " ".join(terminal_safe_text(text).split())
        wrapped = [f"  {cleaned}"] if self.interactive and cleaned else textwrap.wrap(
            cleaned, width=self.content_width - 2, initial_indent="  ",
            subsequent_indent="  ", break_long_words=False, break_on_hyphens=False,
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
        stage = terminal_safe_text(live.get("stage_label") or "Research").strip()
        phase = terminal_safe_text(live.get("phase_label") or "Review").strip()
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
                option_text = terminal_safe_text(option.get("text", "")).strip()
                prefix = f"  {index}  "
                wrapped = [f"{prefix}{option_text}".rstrip()] if self.interactive else textwrap.wrap(
                    option_text, width=self.content_width, initial_indent=prefix,
                    subsequent_indent=" " * len(prefix), break_long_words=False,
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
        idea_id = terminal_safe_text(notification.get("idea_id", "")).strip()
        title = terminal_safe_text(notification.get("title", "Research update")).strip()
        summary = " ".join(terminal_safe_text(notification.get("summary", "")).split())
        if len(summary) > 130:
            summary = f"{summary[:129].rsplit(' ', 1)[0]}…"
        identity = " ".join(part for part in (idea_id, title) if part)
        first = f"{self._style('◆', 'mint')}  {self._style(identity, 'bold')}"
        if not summary:
            return [first]
        return [first, *[self._style(line, "muted") for line in self._wrap_paragraph(summary, indent="   ")]]

    def phase(self, notification: Dict[str, Any]) -> List[str]:
        title = terminal_safe_text(notification.get("title", "Research")).strip()
        summary = terminal_safe_text(notification.get("summary", "")).strip()
        return self.system(" · ".join(part for part in (title, summary) if part))

    def resolved_request(self, notification: Dict[str, Any]) -> List[str]:
        summary = terminal_safe_text(notification.get("summary", "Response recorded.")).strip()
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
                idea_id = terminal_safe_text(item.get("idea_id", "")).strip()
                item_title = terminal_safe_text(item.get("title", ""))
                title = " ".join(part for part in (idea_id, item_title) if part)
            else:
                title = terminal_safe_text(item.get("title", "Research update")).strip()
            summary = " ".join(terminal_safe_text(item.get("summary", "")).split())
            if len(summary) > 100:
                summary = f"{summary[:99].rsplit(' ', 1)[0]}…"
            entry = f"{title}  {summary}".strip()
            wrapped = [f"  • {entry}".rstrip()] if self.interactive else textwrap.wrap(
                entry, width=self.content_width, initial_indent="  • ",
                subsequent_indent="    ", break_long_words=False,
                break_on_hyphens=False,
            ) or ["  •"]
            lines.extend(wrapped)
        return lines

    def idea_detail(self, idea: Dict[str, Any]) -> List[str]:
        idea_id = terminal_safe_text(idea.get("idea_id", "Idea")).strip()
        idea_type = terminal_safe_text(idea.get("idea_type", "idea")).strip().lower()
        level = terminal_safe_text(idea.get("level", "?")).strip()
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
                value = terminal_safe_text(option_text or option_id)
                wrapped = [f"  {marker} {value}"] if self.interactive else textwrap.wrap(
                    value, width=self.content_width, initial_indent=f"  {marker} ",
                    subsequent_indent="    ", break_long_words=False,
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
        label = terminal_safe_text(live.get("label") or live.get("title") or "Ready").strip()
        detail = terminal_safe_text(live.get("detail") or "").strip()
        next_action = terminal_safe_text(live.get("next_action") or "").strip()
        elapsed = terminal_safe_text(live.get("elapsed") or "").strip()
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
            ("/stop", "Stop research and restore saved progress"),
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
            wrapped = [f"{prefix}{description}"] if self.interactive else textwrap.wrap(
                description, width=self.content_width, initial_indent=prefix,
                subsequent_indent=" " * len(prefix), break_long_words=False,
                break_on_hyphens=False,
            ) or [prefix.rstrip()]
            if self.interactive:
                wrapped[0] = wrapped[0].replace(command, self._style(command, "mint"), 1)
            lines.extend(wrapped)
        lines.append(self._style("  Any other text starts a conversation with NeuriCo.", "muted"))
        return lines

    def section(self, title: str) -> List[str]:
        return [self._style(terminal_safe_text(title), "bold"), self._rule()]

    def thinking(self, frame: str) -> str:
        return f"{self._style(frame, 'mint')}  {self._style('NeuriCo is thinking…', 'muted')}"

    def setting_response(self, label: str, value: str) -> List[str]:
        return [
            f"{self._style(terminal_safe_text(label), 'muted')}{terminal_safe_text(value)}",
        ]
