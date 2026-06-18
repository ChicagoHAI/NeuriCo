"""Agent-transcript formatting for the interactive web UI.

The web server tails the per-agent Claude transcripts in a workspace and renders
each entry into the browser's live agent-log feed. This module owns the parsing
and HTML formatting of those entries so the web server can stay focused on
transport. It has no dependencies beyond the standard library.
"""

from __future__ import annotations

import html as html_module
import json

# Prefer transcript (.jsonl) over .log — they're identical content but transcripts
# are the canonical file. Paper writer has no transcript so falls back to .log.
TRANSCRIPT_FILES = [
    ("execution_claude_transcript.jsonl",    "execution_claude.log",    "Execution"),
    ("resource_finder_claude_transcript.jsonl", "resource_finder_claude.log", "Resource Finder"),
    (None,                                   "paper_writer_claude.log", "Paper Writer"),
]


def esc(s: str) -> str:
    return html_module.escape(str(s))


def format_tool_input(inp: dict) -> str:
    """Render tool input dict as readable HTML lines."""
    lines = []
    for k, v in inp.items():
        v_str = str(v)
        if len(v_str) > 200:
            v_str = v_str[:200] + "…"
        lines.append(f'<span class="tool-key">{esc(k)}</span>: <span class="tool-val">{esc(v_str)}</span>')
    return "\n".join(lines)


def format_tool_result(content) -> str:
    """Render tool result content as truncated HTML."""
    if isinstance(content, list):
        text = "\n".join(
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in content
        )
    else:
        text = str(content)

    lines = text.splitlines()
    preview_lines = lines[:8]
    preview = esc("\n".join(preview_lines))

    if len(lines) > 8:
        rest = esc("\n".join(lines[8:]))
        return (
            f"{preview}\n"
            f'<details><summary>{len(lines) - 8} more lines</summary>'
            f'<div class="inner">{rest}</div></details>'
        )
    return preview


def format_block(block: dict) -> dict | None:
    """
    Returns dict with keys: type_label, type_label_class, headline, body, body_class
    or None to skip the block.
    """
    bt = block.get("type", "")

    if bt == "thinking":
        text = block.get("thinking", "").strip()
        if not text:
            return None
        lines = text.splitlines()
        preview = esc(" ".join(lines[:2]))
        body = f'<details><summary>{len(lines)} lines</summary><div class="inner">{esc(text)}</div></details>'
        return {
            "type_label": "🧠 Claude Thinking",
            "type_label_class": "tl-thinking",
            "headline": preview[:120],
            "body": body,
            "body_class": "body-thinking",
        }

    if bt == "text":
        text = block.get("text", "").strip()
        if not text:
            return None
        return {
            "type_label": "💬 Claude Response",
            "type_label_class": "tl-text",
            "headline": esc(text[:120]),
            "body": esc(text),
            "body_class": "body-text",
        }

    if bt == "tool_use":
        name = block.get("name", "?")
        inp  = block.get("input", {})
        primary = next(iter(inp.values()), "") if inp else ""
        headline = f'<span class="tool-name">{esc(name)}</span>  <span class="tool-arg">{esc(str(primary)[:80])}</span>'
        body = f'<span class="tool-name">{esc(name)}</span>\n{format_tool_input(inp)}'
        return {
            "type_label": f"🔧 Tool Call: {name}",
            "type_label_class": "tl-tool-use",
            "headline": headline,
            "body": body,
            "body_class": "body-tool-use",
        }

    if bt == "tool_result":
        content = block.get("content", "")
        is_error = block.get("is_error", False)
        body = format_tool_result(content)
        return {
            "type_label": "⚠️ Tool Error" if is_error else "📤 Tool Result",
            "type_label_class": "tl-error" if is_error else "tl-tool-result",
            "headline": None,
            "body": body,
            "body_class": "body-error" if is_error else "body-tool-result",
        }

    return None


def _detail(raw: dict):
    """Pretty-printed raw entry, used as the expandable body for system/rate-limit/
    result rows so they're clickable like every other row (instead of dangling a
    chevron that does nothing)."""
    try:
        return '<div class="inner">' + esc(json.dumps(raw, indent=2, ensure_ascii=False)) + '</div>'
    except (TypeError, ValueError):
        return None


def format_entry(e: dict, last_ts: str) -> list[dict]:
    """
    Convert a raw log entry into a list of display dicts (one per visual block).
    Returns [] to skip entirely.
    """
    raw = e["raw"]
    t   = raw.get("type", "")
    ts  = e["ts"] or last_ts
    ts_short = ts[11:19] if len(ts) >= 19 else ts

    src = e["source"]
    if "Execution" in src:
        badge_class = "badge-execution"
    elif "Resource" in src:
        badge_class = "badge-resource"
    else:
        badge_class = "badge-paper"

    base = {"ts": ts_short, "source": src, "badge_class": badge_class}

    if t == "system":
        sub = raw.get("subtype", "")
        if sub == "init":
            model = raw.get("model", "")
            sid   = raw.get("session_id", "")[:8]
            text  = f"session started  model={model}  session={sid}"
        else:
            text = f"[{sub}]"
        return [{**base, "type_label": "system", "type_label_class": "tl-system",
                 "headline": esc(text), "body": _detail(raw), "body_class": "body-system"}]

    if t == "rate_limit_event":
        info = raw.get("rate_limit_info", {})
        text = f"rate limit: {info.get('status')}  ({info.get('rateLimitType')})"
        return [{**base, "type_label": "rate limit", "type_label_class": "tl-system",
                 "headline": esc(text), "body": _detail(raw), "body_class": "body-system"}]

    if t == "result":
        result   = raw.get("result", "")
        duration = raw.get("duration_ms", "")
        cost     = raw.get("cost_usd", "")
        parts = [f"result: {result}"]
        if duration: parts.append(f"duration: {int(duration)/1000:.1f}s")
        if cost:     parts.append(f"cost: ${cost:.4f}")
        return [{**base, "type_label": "result", "type_label_class": "tl-system",
                 "headline": esc("  ·  ".join(parts)), "body": _detail(raw), "body_class": "body-system"}]

    if t in ("assistant", "user"):
        msg    = raw.get("message", {})
        blocks = msg.get("content", [])
        out    = []
        for block in blocks:
            formatted = format_block(block)
            if formatted:
                out.append({**base, **formatted})
        return out

    return []
