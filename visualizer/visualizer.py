#!/usr/bin/env python3
"""
Simple live log visualizer for NeuriCo workspaces.

Usage:
    python visualizer/visualizer.py <workspace_name>
    python visualizer/visualizer.py kaggle_house_prices_benchmark__20260605_101554_15998df8
"""

import argparse
import html as html_module
import json
import sys
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WORKSPACES_DIR = Path(__file__).parent.parent / "workspaces"

# Prefer transcript (.jsonl) over .log — they're identical content but transcripts
# are the canonical file. Paper writer has no transcript so falls back to .log.
TRANSCRIPT_FILES = [
    ("execution_claude_transcript.jsonl",    "execution_claude.log",    "Execution"),
    ("resource_finder_claude_transcript.jsonl", "resource_finder_claude.log", "Resource Finder"),
    (None,                                   "paper_writer_claude.log", "Paper Writer"),
]

# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>NeuriCo – {workspace}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0d1117;
      color: #c9d1d9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      padding-bottom: 48px;
    }}

    /* ── Header ── */
    #header {{
      position: sticky; top: 0; z-index: 10;
      background: #161b22;
      border-bottom: 1px solid #30363d;
      padding: 10px 20px;
      display: flex; align-items: center; gap: 12px;
    }}
    #header h1 {{ font-size: 15px; color: #58a6ff; font-weight: 600; }}
    #header .ws  {{ color: #8b949e; font-size: 12px; font-family: monospace; }}
    #counter     {{ margin-left: auto; color: #6e7681; font-size: 11px; }}

    /* ── Log container ── */
    #log {{ padding: 16px 20px; display: flex; flex-direction: column; gap: 6px; }}

    /* ── Entry card ── */
    .entry {{
      border-radius: 6px;
      border: 1px solid #21262d;
      overflow: hidden;
    }}
    .entry-header {{
      display: flex; align-items: center; gap: 8px;
      padding: 5px 10px;
      background: #161b22;
      font-size: 11px;
      color: #8b949e;
    }}
    .entry-header .ts {{ font-family: monospace; color: #6e7681; min-width: 70px; }}
    .badge {{
      display: inline-block;
      padding: 1px 7px;
      border-radius: 10px;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.03em;
    }}
    .badge-execution     {{ background: #1f3c5e; color: #79c0ff; }}
    .badge-resource      {{ background: #1a3a2e; color: #56d364; }}
    .badge-paper         {{ background: #2d1f4e; color: #d2a8ff; }}
    .type-label {{
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 500;
    }}
    .tl-thinking  {{ background: #2a2a1e; color: #e3b341; }}
    .tl-text      {{ background: #1a2a1a; color: #56d364; }}
    .tl-tool-use  {{ background: #1e2a3a; color: #79c0ff; }}
    .tl-tool-result {{ background: #1e1e2a; color: #a5d6ff; }}
    .tl-system    {{ background: #1e1e1e; color: #6e7681; }}
    .tl-error     {{ background: #3a1e1e; color: #ff7b72; }}

    .entry-body {{
      padding: 8px 12px;
      font-family: monospace;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      color: #c9d1d9;
    }}

    /* Type-specific body styles */
    .body-thinking    {{ color: #b8a000; font-style: italic; background: #0e0e07; }}
    .body-text        {{ color: #e6edf3; background: #0d1117; }}
    .body-tool-use    {{ color: #79c0ff; background: #0a111a; }}
    .body-tool-result {{ color: #8b949e; background: #0a0a12; font-size: 11px; }}
    .body-system      {{ color: #6e7681; background: #0e0e0e; font-size: 11px; }}
    .body-error       {{ color: #ff7b72; background: #120a0a; }}

    /* Collapsible toggle */
    details summary {{
      cursor: pointer;
      list-style: none;
      user-select: none;
      color: #58a6ff;
      font-size: 11px;
      padding: 2px 0;
    }}
    details summary::-webkit-details-marker {{ display: none; }}
    details summary::before {{ content: "▶ show "; }}
    details[open] summary::before {{ content: "▼ hide "; }}
    details .inner {{ margin-top: 6px; }}

    /* Tool call formatting */
    .tool-name {{ color: #ffa657; font-weight: bold; }}
    .tool-arg  {{ color: #a5d6ff; }}
    .tool-key  {{ color: #79c0ff; }}
    .tool-val  {{ color: #aff5b4; }}

    /* Status bar */
    #status {{
      position: fixed; bottom: 0; left: 0; right: 0;
      padding: 5px 20px;
      background: #161b22;
      border-top: 1px solid #30363d;
      color: #8b949e; font-size: 11px;
    }}
  </style>
</head>
<body>
  <div id="header">
    <h1>NeuriCo Log Viewer</h1>
    <span class="ws">{workspace}</span>
    <span id="counter"></span>
  </div>
  <div id="log"></div>
  <div id="status">Connecting…</div>

  <script>
    const log     = document.getElementById('log');
    const status  = document.getElementById('status');
    const counter = document.getElementById('counter');
    let count = 0;

    const es = new EventSource('/stream');

    es.addEventListener('entry', e => {{
      const d = JSON.parse(e.data);
      count++;
      counter.textContent = count + ' entries';

      const entry = document.createElement('div');
      entry.className = 'entry';

      // Header row
      const hdr = document.createElement('div');
      hdr.className = 'entry-header';
      hdr.innerHTML =
        `<span class="ts">${{d.ts || '—'}}</span>` +
        `<span class="badge ${{d.badge_class}}">${{d.source}}</span>` +
        `<span class="type-label ${{d.type_label_class}}">${{d.type_label}}</span>` +
        (d.headline ? `<span style="color:#8b949e;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{d.headline}}</span>` : '');
      entry.appendChild(hdr);

      // Body
      if (d.body) {{
        const body = document.createElement('div');
        body.className = `entry-body ${{d.body_class}}`;
        body.innerHTML = d.body;
        entry.appendChild(body);
      }}

      log.appendChild(entry);
      window.scrollTo(0, document.body.scrollHeight);
    }});

    es.addEventListener('status', e => {{ status.textContent = e.data; }});
    es.onerror = () => {{ status.textContent = 'Connection lost – reload to retry'; }};
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Entry formatting
# ---------------------------------------------------------------------------

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
                 "headline": esc(text), "body": None, "body_class": "body-system"}]

    if t == "rate_limit_event":
        info = raw.get("rate_limit_info", {})
        text = f"rate limit: {info.get('status')}  ({info.get('rateLimitType')})"
        return [{**base, "type_label": "rate limit", "type_label_class": "tl-system",
                 "headline": esc(text), "body": None, "body_class": "body-system"}]

    if t == "result":
        result   = raw.get("result", "")
        duration = raw.get("duration_ms", "")
        cost     = raw.get("cost_usd", "")
        parts = [f"result: {result}"]
        if duration: parts.append(f"duration: {int(duration)/1000:.1f}s")
        if cost:     parts.append(f"cost: ${cost:.4f}")
        return [{**base, "type_label": "result", "type_label_class": "tl-system",
                 "headline": esc("  ·  ".join(parts)), "body": None, "body_class": "body-system"}]

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


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def load_entries(log_dir: Path) -> list[dict]:
    entries = []
    for transcript, fallback, source_name in TRANSCRIPT_FILES:
        filename = transcript if (transcript and (log_dir / transcript).exists()) else fallback
        path = log_dir / filename
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entries.append({"ts": obj.get("timestamp", ""), "source": source_name, "raw": obj})
    # No sort needed — entries are already in chronological order as written
    return entries


def make_handler(workspace_name: str, log_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_PAGE.format(workspace=workspace_name).encode())

            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                entries  = load_entries(log_dir)
                last_ts  = ""
                total    = 0

                for entry in entries:
                    if entry["ts"]:
                        last_ts = entry["ts"]
                    display_items = format_entry(entry, last_ts)
                    for item in display_items:
                        data = json.dumps(item)
                        msg  = f"event: entry\ndata: {data}\n\n"
                        try:
                            self.wfile.write(msg.encode())
                            self.wfile.flush()
                        except (BrokenPipeError, OSError):
                            return
                        total += 1
                        time.sleep(0.015)

                try:
                    self.wfile.write(
                        f"event: status\ndata: Done – {total} items from {len(entries)} log lines\n\n".encode()
                    )
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    return

                while True:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        time.sleep(15)
                    except (BrokenPipeError, OSError):
                        return

            else:
                self.send_response(404)
                self.end_headers()

    return Handler


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NeuriCo live log visualizer")
    parser.add_argument("workspace", help="Workspace folder name (or partial match)")
    parser.add_argument("--port", type=int, default=7891, help="Local port (default: 7891)")
    args = parser.parse_args()

    matches = list(WORKSPACES_DIR.glob(f"*{args.workspace}*"))
    if not matches:
        print(f"Error: no workspace matching '{args.workspace}' in {WORKSPACES_DIR}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"Ambiguous – multiple matches:")
        for m in matches:
            print(f"  {m.name}")
        sys.exit(1)

    workspace_dir = matches[0]
    log_dir = workspace_dir / "logs"
    if not log_dir.exists():
        print(f"Error: no logs/ directory in {workspace_dir}")
        sys.exit(1)

    url = f"http://localhost:{args.port}"
    print(f"Workspace : {workspace_dir.name}")
    print(f"Opening   : {url}")

    server = HTTPServer(("localhost", args.port), make_handler(workspace_dir.name, log_dir))
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
