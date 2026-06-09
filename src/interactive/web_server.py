"""
Embedded web server for NeuriCo Interactive Mode.

Serves a single browser page with THREE panes, tuned for non-technical
researchers:
  1. A brief, always-visible **dashboard** strip (phase, cost, agents, papers,
     files, elapsed) — a live "what's happening" summary.
  2. The **conversation** with the manager (the primary pane, with an input box
     and clickable option buttons).
  3. A compact, **collapsible live log** of the agent's actions — each row shows
     only time / agent / a plain-language label / a short preview, and expands
     inline on click to reveal the full content.

Architecture A (embedded): this runs in background threads inside the manager
process and shares in-process queues with a WebChannel — no file polling for the
conversation, no second process.

Routes:
  GET  /            -> the HTML page
  GET  /stream      -> Server-Sent Events: conversation + agent-log + status + dashboard
  GET  /annotations -> {key: verdict} map of offline-eval thumbs (re-paint on load)
  POST /input       -> the browser submits the human's reply
  POST /annotate    -> record a 👍/👎 on an assessment / decision / manager bubble
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from interactive.channel import WebChannel
from interactive import annotations as _annotations

# Reuse the standalone visualizer's transcript formatting so the agent-log feed
# looks identical to the old viewer. Best-effort: if the import fails, the
# conversation still works, just without the live agent transcript.
_viz = None


def _load_visualizer(project_root: Path):
    global _viz
    if _viz is not None:
        return _viz
    try:
        viz_dir = str(project_root / "visualizer")
        if viz_dir not in sys.path:
            sys.path.insert(0, viz_dir)
        import visualizer as viz  # type: ignore
        _viz = viz
    except Exception:
        _viz = False  # sentinel: tried and failed
    return _viz


# ---------------------------------------------------------------------------
# Agent-log tailer
# ---------------------------------------------------------------------------

def _tail_agent_logs(log_dir: Path, channel: WebChannel,
                     project_root: Path, stop: threading.Event) -> None:
    """Incrementally tail the workspace transcripts and emit formatted entries
    into the channel as `agentlog` events."""
    viz = _load_visualizer(project_root)
    if not viz:
        # Don't fail silently — an empty log pane is otherwise unexplained.
        print("[web] live log disabled: could not import visualizer/visualizer.py",
              file=sys.stderr)
        return

    offsets: dict = {}
    last_ts = ""

    while not stop.is_set():
        for transcript, fallback, source_name in viz.TRANSCRIPT_FILES:
            fname = transcript if (transcript and (log_dir / transcript).exists()) else fallback
            if not fname:
                continue
            path = log_dir / fname
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    fh.seek(offsets.get(str(path), 0))
                    while True:
                        pos = fh.tell()
                        line = fh.readline()
                        if not line:
                            break
                        if not line.endswith("\n"):
                            fh.seek(pos)  # incomplete line; re-read next pass
                            break
                        offsets[str(path)] = fh.tell()
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        entry = {"ts": obj.get("timestamp", ""),
                                 "source": source_name, "raw": obj}
                        if entry["ts"]:
                            last_ts = entry["ts"]
                        # Defensive: a single malformed entry must not kill the
                        # whole live feed (which would freeze the log pane
                        # mid-session and look "empty").
                        try:
                            items = viz.format_entry(entry, last_ts)
                        except Exception:
                            continue
                        for item in items:
                            channel.emit_raw({"event": "agentlog", **item})
            except OSError:
                continue
        stop.wait(1.0)


# ---------------------------------------------------------------------------
# Dashboard feed (brief, real-time "what's happening" stats)
# ---------------------------------------------------------------------------

_COST_RE = re.compile(r'"(?:total_cost_usd|cost_usd)"\s*:\s*([0-9]+\.?[0-9]*)')
# Per-file cost cache so we don't re-parse big transcripts every tick.
_cost_cache: dict = {}  # str(path) -> (mtime, size, cost)


def _cost_source_files(log_dir: Path, project_root: Path) -> list:
    """One cost-bearing file per agent. Mirrors the live-log tailer: prefer the
    `.jsonl` transcript, fall back to the agent's `.log` (e.g. the paper writer
    only writes `paper_writer_claude.log`). Using one file per agent avoids
    double-counting the agents whose `.jsonl` and `.log` are identical copies."""
    viz = _load_visualizer(project_root)
    if viz and getattr(viz, "TRANSCRIPT_FILES", None):
        paths = []
        for transcript, fallback, _ in viz.TRANSCRIPT_FILES:
            if transcript and (log_dir / transcript).exists():
                paths.append(log_dir / transcript)
            elif fallback and (log_dir / fallback).exists():
                paths.append(log_dir / fallback)
        return paths
    # Visualizer unavailable: fall back to jsonl only (still no double-count).
    return list(log_dir.glob("*_transcript.jsonl"))


def _sum_cost(log_dir: Path, project_root: Path) -> float:
    """Total USD across all agent runs (one file per agent). Cached by
    (mtime, size) so a multi-MB transcript is only re-scanned when it grows."""
    if not log_dir.exists():
        return 0.0
    total = 0.0
    for path in _cost_source_files(log_dir, project_root):
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        cached = _cost_cache.get(key)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            total += cached[2]
            continue
        file_cost = 0.0
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for m in _COST_RE.finditer(fh.read()):
                    try:
                        file_cost = max(file_cost, float(m.group(1)))
                    except ValueError:
                        pass
        except OSError:
            continue
        _cost_cache[key] = (st.st_mtime, st.st_size, file_cost)
        total += file_cost
    return total


def _count_files(*dirs: Path) -> int:
    n = 0
    for d in dirs:
        if not d.exists():
            continue
        try:
            n += sum(1 for p in d.rglob("*") if p.is_file())
        except OSError:
            continue
    return n


def _compute_dashboard(workspace: Path, project_root: Path) -> dict:
    """Cheap snapshot of progress for the dashboard strip."""
    # Session state (phase + agent runs)
    phase, agents_done, agents_running, started = "", 0, 0, ""
    running_agents, last_agent = [], ""
    sess_file = workspace / ".neurico" / "manager_session.json"
    try:
        with open(sess_file, encoding="utf-8") as fh:
            sess = json.load(fh)
        phase = sess.get("phase", "") or ""
        started = sess.get("started_at", "") or sess.get("created_at", "") or ""
        for a in sess.get("agents_run", []):
            # session_state records `completed` (timestamp or None) rather than a
            # status string: an agent is done once `completed` is set, otherwise
            # it is still running.
            last_agent = a.get("agent", "") or last_agent
            if a.get("completed"):
                agents_done += 1
            else:
                agents_running += 1
                running_agents.append(a.get("agent", ""))
    except (OSError, json.JSONDecodeError):
        pass

    # The manager's recorded `phase` lags real activity (it only changes when the
    # manager calls update_session). Derive a truer phase from the agents:
    #   - a running agent → its phase (most real-time);
    #   - else the most recent agent's phase — unless the manager has set a
    #     meaningful terminal state, which we keep.
    _AGENT_PHASE = {"resource_finder": "exploring", "experiment_runner": "experimenting",
                    "paper_writer": "writing", "comment_handler": "revising"}
    _TERMINAL = {"complete", "completed", "done", "finished", "blocked", "failed"}
    if running_agents:
        phase = _AGENT_PHASE.get(running_agents[-1], phase) or phase
    elif last_agent and phase.lower() not in _TERMINAL:
        phase = _AGENT_PHASE.get(last_agent, phase) or phase

    cost = _sum_cost(workspace / "logs", project_root)
    papers = _count_files(workspace / "papers", workspace / "paper_search_results")
    files = _count_files(workspace / "code", workspace / "figures",
                         workspace / "results", workspace / "paper_draft")
    if (workspace / "REPORT.md").exists():
        files += 1

    return {
        "event": "dashboard",
        "phase": phase,
        "cost": round(cost, 4),
        "agents_done": agents_done,
        "agents_running": agents_running,
        "papers": papers,
        "files": files,
        "started": started,
    }


def _emit_dashboard(workspace: Path, project_root: Path, channel: WebChannel,
                    stop: threading.Event) -> None:
    """Periodically push a `dashboard` event, but only when something changed
    (keeps the SSE history small for reconnects)."""
    last = None
    while not stop.is_set():
        try:
            d = _compute_dashboard(workspace, project_root)
        except Exception:
            d = None
        if d is not None:
            sig = (d["phase"], d["cost"], d["agents_done"], d["agents_running"],
                   d["papers"], d["files"], d["started"])
            if sig != last:
                last = sig
                channel.emit_raw(d)
        stop.wait(3.0)


def _emit_research_state(workspace: Path, channel: WebChannel,
                         stop: threading.Event) -> None:
    """Push the manager's world model (the `research` event) to the browser when
    it changes. The manager writes research_state.json via update_research_state
    / assess; we poll it and fan a snapshot out to the Research whiteboard. Polled
    (not in-process) so it works identically for fresh and resumed sessions and
    stays decoupled from the manager loop."""
    state_file = workspace / ".neurico" / "research_state.json"
    last_stamp = None
    while not stop.is_set():
        try:
            if state_file.exists():
                with open(state_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                stamp = data.get("updated_at")
                if stamp != last_stamp:
                    last_stamp = stamp
                    data["event"] = "research"
                    channel.emit_raw(data)
        except (OSError, json.JSONDecodeError):
            pass
        stop.wait(2.0)


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NeuriCo Interactive – {{TITLE}}</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;display:flex;flex-direction:column;overflow:hidden}

  /* ---- top bar: title + dashboard ---- */
  #topbar{background:#161b22;border-bottom:1px solid #30363d;padding:8px 16px}
  #titlerow{display:flex;align-items:center;gap:10px;margin-bottom:8px}
  #titlerow h1{font-size:14px;color:#58a6ff;font-weight:600;display:flex;align-items:center;gap:8px}
  #brand-logo{height:24px;width:auto;display:block}
  .avatar{width:18px;height:18px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-right:5px}
  #titlerow .ws{color:#8b949e;font-size:11px;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #conn{margin-left:auto;color:#6e7681;font-size:11px}
  #dash{display:flex;flex-wrap:wrap;gap:8px}
  .stat{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:4px 12px;min-width:84px}
  .stat .k{font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.04em}
  .stat .v{font-size:15px;color:#e6edf3;font-weight:600}
  .stat.live .v{color:#56d364}
  #activity{font-size:11px;color:#8b949e;margin-top:6px;min-height:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #activity b{color:#79c0ff;font-weight:600}

  /* ---- main: chat (primary) | log (secondary) ---- */
  #main{flex:1;display:flex;min-height:0}
  #chatcol{flex:1.5;display:flex;flex-direction:column;min-width:0;min-height:0;border-right:1px solid #30363d}
  #logcol{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;background:#0b0f14}
  .panehead{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;padding:8px 16px;border-bottom:1px solid #21262d;background:#10151c;flex-shrink:0}
  /* min-height:0 lets these flex children actually scroll instead of growing the page */
  #chat{flex:1;min-height:0;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
  /* #log visibility/layout is governed by .tabpane / .tabpane.active (see tab CSS) */

  /* ---- chat bubbles ---- */
  .msg{flex:0 0 auto;border-radius:8px;padding:8px 12px;line-height:1.5;white-space:pre-wrap;word-break:break-word;max-width:92%}
  .msg .who{font-size:11px;color:#8b949e;margin-bottom:3px}
  .role-manager{background:#11233b;border:1px solid #1f3c5e;align-self:flex-start}
  .role-manager .who{color:#79c0ff}
  .role-user{background:#10261a;border:1px solid #1a3a2e;align-self:flex-end}
  .role-user .who{color:#56d364}
  .role-system{background:transparent;color:#6e7681;font-size:12px;align-self:center}
  /* a real question (ask_user) — stands out as "needs your reply" */
  .msg.is-question{border:1px solid #e3b341;background:#26200d;box-shadow:0 0 0 2px #e3b34133;max-width:100%}
  .msg.is-question .who{color:#e3b341}
  /* a manager note that merely ends with "?" — subtle hint it may want a reply */
  .msg.maybe-question{border-left:3px solid #58a6ff}
  /* "manager is thinking" placeholder bubble */
  .typing{align-self:flex-start;opacity:.9}
  .typing .dots::after{content:'';animation:typing-dots 1.3s steps(4,end) infinite}
  @keyframes typing-dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}100%{content:''}}

  /* ---- collapsible log rows ---- */
  .entry{flex:0 0 auto;border:1px solid #21262d;border-radius:6px;background:#0d1117;overflow:hidden}
  .entry-row{display:flex;align-items:center;gap:8px;padding:5px 9px;cursor:pointer;font-size:12px}
  .entry-row:hover{background:#161b22}
  .entry-row .ts{font-family:monospace;color:#6e7681;font-size:10px;min-width:58px}
  .entry-row .badge{display:inline-block;padding:1px 6px;border-radius:9px;font-size:9px;font-weight:600;white-space:nowrap}
  .badge-execution{background:#1f3c5e;color:#79c0ff}
  .badge-resource{background:#1a3a2e;color:#56d364}
  .badge-paper{background:#2d1f4e;color:#d2a8ff}
  .entry-row .lbl{font-weight:600;white-space:nowrap}
  .lbl-thinking{color:#e3b341}.lbl-text{color:#56d364}.lbl-tool{color:#79c0ff}
  .lbl-result{color:#a5d6ff}.lbl-error{color:#ff7b72}.lbl-system{color:#6e7681}
  .entry-row .prev{color:#8b949e;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:monospace}
  .entry-row .more{color:#6e7681;font-size:10px;white-space:nowrap}
  /* "ask the manager about this row" — appears on hover to keep rows clean */
  .entry-row .ask{background:none;border:none;color:#6e7681;cursor:pointer;font-size:12px;padding:0 4px;opacity:0;transition:opacity .1s}
  .entry-row:hover .ask{opacity:1}
  .entry-row .ask:hover{color:#58a6ff}
  .entry-row .chev{color:#6e7681;font-size:10px;transition:transform .1s}
  .entry.open .chev{transform:rotate(90deg)}
  .entry-body{display:none;padding:8px 12px;border-top:1px solid #21262d;font-family:monospace;font-size:11.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;background:#0a0d12;max-height:50vh;overflow:auto}
  .entry.open .entry-body{display:block}
  .body-thinking{color:#b8a000;font-style:italic}.body-tool-use{color:#79c0ff}
  .body-tool-result{color:#8b949e}.body-text{color:#e6edf3}.body-system{color:#6e7681}
  .body-error{color:#ff7b72}
  .tool-name{color:#ffa657;font-weight:bold}.tool-key{color:#79c0ff}.tool-val{color:#aff5b4}
  #logempty{color:#6e7681;font-size:12px;padding:8px;text-align:center}

  /* ---- tabbed right column (Research whiteboard | Activity) ---- */
  .tabhead{display:flex;gap:4px;padding:0 8px;align-items:flex-end}
  .tab{background:none;border:none;border-bottom:2px solid transparent;color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;cursor:pointer;font-weight:600}
  .tab:hover{color:#c9d1d9}
  .tab.active{color:#e6edf3;border-bottom-color:#58a6ff}
  .tabpane{display:none;flex:1;min-height:0;overflow-y:auto;padding:12px}
  .tabpane.active{display:flex;flex-direction:column;gap:10px}
  #log.tabpane.active{gap:6px}
  #researchempty{color:#6e7681;font-size:12px;padding:8px;text-align:center}

  /* the manager's world model, rendered as a shared whiteboard */
  .r-crux{border:1px solid #e3b341;background:#26200d;border-radius:8px;padding:8px 12px;font-size:13px;color:#f0d990}
  .r-crux b{color:#e3b341;display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .r-card{background:#10261a;border:1px solid #1a3a2e;border-radius:8px;padding:8px 12px;font-size:13px;color:#aff5b4}
  .r-card b{color:#56d364;display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .r-narrative{font-size:13px;color:#c9d1d9;line-height:1.5;padding:2px 2px}
  .r-assess{background:#11233b;border:1px solid #1f3c5e;border-radius:8px;padding:8px 12px;font-size:12px;color:#c9d1d9}
  .r-assess b{color:#79c0ff;display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .r-assess .eng{display:inline-block;margin-top:5px;font-size:11px;padding:1px 7px;border-radius:9px}
  .r-assess .eng.yes{background:#26200d;color:#e3b341;border:1px solid #e3b341}
  .r-assess .eng.no{background:#161b22;color:#6e7681;border:1px solid #30363d}
  .r-sec .r-h{font-size:11px;font-weight:700;color:#adbac7;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
  .hyp{display:flex;gap:7px;align-items:baseline;padding:4px 0;border-bottom:1px solid #161b22;font-size:13px}
  .hyp .st{flex-shrink:0;font-size:9px;font-weight:700;padding:1px 6px;border-radius:9px;text-transform:uppercase}
  .st-alive{background:#1f3c5e;color:#79c0ff}.st-uncertain{background:#2a2a1e;color:#e3b341}
  .st-supported{background:#1a3a2e;color:#56d364}.st-dead{background:#3a1e1e;color:#ff7b72}
  .hyp .stmt{color:#c9d1d9}.hyp.st-row-dead .stmt{color:#8b949e;text-decoration:line-through}
  .hyp .ev{color:#6e7681;font-size:11px}
  .qitem{font-size:13px;color:#c9d1d9;padding:3px 0;padding-left:14px;position:relative}
  .qitem::before{content:"?";position:absolute;left:0;color:#58a6ff;font-weight:700}
  .decitem{font-size:12px;color:#c9d1d9;padding:4px 0;border-bottom:1px solid #161b22}
  .decitem .ch{color:#56d364}.decitem .rat{color:#6e7681;font-size:11px}

  /* ---- offline-eval thumbs (👍/👎 on assessments, decisions, manager bubbles) ---- */
  .ann{display:inline-flex;gap:2px;margin-left:6px;vertical-align:middle}
  .ann-btn{background:none;border:none;cursor:pointer;font-size:13px;line-height:1;padding:0 2px;
           opacity:.3;filter:grayscale(1);transition:opacity .1s}
  .ann-btn:hover{opacity:.65}
  .ann-btn.on{opacity:1;filter:none}
  .ann-foot{margin-top:5px;display:flex;align-items:center;gap:4px}
  .ann-foot .ann-lbl{font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.05em}
  .expitem{font-size:12px;color:#8b949e;padding:3px 0;font-family:monospace}
  .expitem .est{font-size:9px;padding:0 5px;border-radius:8px;margin-right:5px}
  .est-running{background:#1f3c5e;color:#79c0ff}.est-done{background:#1a3a2e;color:#56d364}.est-failed{background:#3a1e1e;color:#ff7b72}
  /* consistency warnings (drift to fix) + incident log (what went wrong) */
  .r-warn{border:1px solid #d29922;background:#2a1e0a;border-radius:8px;padding:8px 12px;font-size:12px;color:#f0c674}
  .r-warn b{color:#e3b341;display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
  .r-warn .warn-i{padding:2px 0}
  .inc-i{font-size:12px;color:#c9d1d9;padding:3px 0;border-bottom:1px solid #161b22}
  .inc-i .inc-k{display:inline-block;font-size:9px;font-weight:700;padding:1px 6px;border-radius:8px;background:#3a1e1e;color:#ff7b72;text-transform:uppercase;margin-right:5px}
  .inc-i .inc-ts{color:#6e7681;font-family:monospace;font-size:10px}

  /* ---- PI-defined custom blocks (design_panel) ---- */
  .r-ul{margin:0;padding-left:18px}
  .r-ul li{font-size:13px;color:#c9d1d9;padding:2px 0;line-height:1.45}
  .r-kv{width:100%;border-collapse:collapse;font-size:13px}
  .r-kv td{padding:3px 8px 3px 0;vertical-align:top;border-bottom:1px solid #161b22}
  .r-kv td.k{color:#8b949e;white-space:nowrap;width:1%}
  .r-kv td.v{color:#c9d1d9}
  .r-table{width:100%;border-collapse:collapse;font-size:12px}
  .r-table th{text-align:left;color:#8b949e;font-weight:600;padding:4px 8px;border-bottom:1px solid #30363d;text-transform:uppercase;font-size:10px;letter-spacing:.04em}
  .r-table td{padding:4px 8px;border-bottom:1px solid #161b22;color:#c9d1d9;vertical-align:top}
  .r-table tr:hover td{background:#11151c}

  /* ---- composer (bottom of chat column) ---- */
  #composer{border-top:1px solid #30363d;background:#161b22;padding:10px 16px;flex-shrink:0}
  #composer.awaiting{background:#26200d;border-top:2px solid #e3b341}
  #hint{font-size:11px;color:#e3b341;min-height:15px;margin-bottom:6px}
  #options{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
  .opt{background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:14px;padding:5px 13px;font-size:13px;cursor:pointer;text-align:left}
  .opt:hover{background:#30363d;border-color:#58a6ff}
  #inputrow{display:flex;gap:8px;align-items:flex-end}
  #msg{flex:1;resize:none;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 10px;font-family:inherit;font-size:14px;line-height:1.4;max-height:160px}
  #msg:focus{outline:none;border-color:#58a6ff}
  #send{background:#238636;color:#fff;border:none;border-radius:8px;padding:9px 18px;font-size:14px;font-weight:600;cursor:pointer}
  #send:hover{background:#2ea043}
</style>
</head>
<body>
  <div id="topbar">
    <div id="titlerow">
      <h1><img id="brand-logo" src="/brand/logo" alt="" onerror="this.remove()"><span>NeuriCo Interactive</span></h1>
      <span class="ws">{{WORKSPACE}}</span>
      <span id="conn">Connecting…</span>
    </div>
    <div id="dash">
      <div class="stat"><div class="k">Phase</div><div class="v" id="s-phase">—</div></div>
      <div class="stat"><div class="k">Cost</div><div class="v" id="s-cost">$0.00</div></div>
      <div class="stat"><div class="k">Agents</div><div class="v" id="s-agents">0</div></div>
      <div class="stat"><div class="k">Papers</div><div class="v" id="s-papers">0</div></div>
      <div class="stat"><div class="k">Files</div><div class="v" id="s-files">0</div></div>
      <div class="stat"><div class="k">Elapsed</div><div class="v" id="s-elapsed">0:00</div></div>
    </div>
    <div id="activity"></div>
  </div>

  <div id="main">
    <div id="chatcol">
      <div class="panehead">💬 Conversation</div>
      <div id="chat"></div>
      <div id="composer">
        <div id="hint"></div>
        <div id="options"></div>
        <div id="inputrow">
          <textarea id="msg" rows="1" placeholder="Type a message to the manager… (Enter to send, Shift+Enter for newline)"></textarea>
          <button id="send">Send</button>
        </div>
      </div>
    </div>
    <div id="logcol">
      <div class="panehead tabhead">
        <button class="tab active" data-tab="research">🔬 Research</button>
        <button class="tab" data-tab="activity">⚙️ Activity</button>
      </div>
      <div id="research" class="tabpane active">
        <div id="researchempty">The manager hasn't recorded its research model yet…</div>
        <!-- Rebuilt in panel_layout order by setResearch(); sections are a mix
             of built-in renderers and PI-defined custom blocks. -->
        <div id="researchbody" style="display:none"></div>
      </div>
      <div id="log" class="tabpane"><div id="logempty">Waiting for the agent to start…</div></div>
    </div>
  </div>

<script>
  const chat=document.getElementById('chat');
  const logEl=document.getElementById('log');
  const connEl=document.getElementById('conn');
  const activityEl=document.getElementById('activity');
  const hint=document.getElementById('hint');
  const optionsEl=document.getElementById('options');
  const composer=document.getElementById('composer');
  const msg=document.getElementById('msg');
  const send=document.getElementById('send');

  let awaitingReply=false;   // true only while the manager is actively asking

  function atBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<80;}

  // --- conversation ---
  function addMessage(d){
    if(!d.text) return;
    const stick=atBottom(chat);
    const role=d.role||'manager';
    if(role==='manager') setThinking(false);   // a reply arrived → drop the placeholder
    const isQuestion=!!(d.meta&&d.meta.question);   // came via ask_user → needs a reply
    // light heuristic: a manager note ending with "?" probably invites a reply
    const looksAsk=role==='manager'&&!isQuestion&&/\?\s*$/.test((d.text||'').trim());
    const el=document.createElement('div');
    el.className='msg role-'+role+(isQuestion?' is-question':'')+(looksAsk?' maybe-question':'');
    let whoEl=null;
    if(isQuestion){
      whoEl=document.createElement('div');whoEl.className='who';whoEl.textContent='❓ Manager needs your reply';
    }else if(role==='manager'){
      whoEl=document.createElement('div');whoEl.className='who';
      // avatar image; if it 404s (no file pasted), fall back to the 🤖 emoji
      whoEl.innerHTML='<img class="avatar" src="/brand/manager" alt="" onerror="this.replaceWith(document.createTextNode(\'🤖 \'))">Manager';
    }else if(role==='user'){
      whoEl=document.createElement('div');whoEl.className='who';whoEl.textContent='🧑 You';
    }
    if(whoEl) el.appendChild(whoEl);
    const t=document.createElement('div');t.textContent=d.text;el.appendChild(t);
    // Offline-eval thumbs on manager bubbles (keyed by the event's seq, which is
    // stable across reconnects within a run; the POST also snapshots the text).
    if(role==='manager'&&d.seq!=null){
      const af=document.createElement('div');af.className='ann-foot';
      af.innerHTML=annHTML('msg:'+d.seq,d.text);
      el.appendChild(af);
    }
    chat.appendChild(el);
    if(stick) chat.scrollTop=chat.scrollHeight;
  }

  // A transient "🤖 Manager is thinking…" bubble so a wait never looks dead.
  let thinkingEl=null;
  function setThinking(on){
    if(on){
      if(thinkingEl) return;
      const stick=atBottom(chat);
      thinkingEl=document.createElement('div');
      thinkingEl.className='msg role-manager typing';
      thinkingEl.innerHTML='<div class="who"><img class="avatar" src="/brand/manager" alt="" onerror="this.replaceWith(document.createTextNode(\'🤖 \'))">Manager</div><div>🤔 Thinking<span class="dots"></span></div>';
      chat.appendChild(thinkingEl);
      if(stick) chat.scrollTop=chat.scrollHeight;
    }else if(thinkingEl){
      thinkingEl.remove(); thinkingEl=null;
    }
  }

  // --- friendly, plain-language labels for the log ---
  function friendly(d){
    const tl=(d.type_label||'');
    const cls=(d.type_label_class||'');
    if(cls.indexOf('thinking')>=0) return {txt:'🧠 Thinking',cls:'lbl-thinking'};
    if(cls.indexOf('tool-result')>=0||cls.indexOf('error')>=0)
      return {txt:(cls.indexOf('error')>=0?'⚠️ Problem':'📤 Result'),cls:(cls.indexOf('error')>=0?'lbl-error':'lbl-result')};
    if(cls.indexOf('tool-use')>=0){
      const m=tl.match(/:\s*(\w+)/); const tool=m?m[1]:'';
      const map={Bash:'⚙️ Running code',Read:'📖 Reading a file',Write:'✍️ Writing a file',
        Edit:'✏️ Editing a file',Grep:'🔎 Searching files',Glob:'🔎 Finding files',
        WebSearch:'🌐 Searching the web',WebFetch:'🌐 Reading a web page',Task:'🧩 Delegating a sub-task'};
      return {txt:map[tool]||('🔧 '+(tool||'Action')),cls:'lbl-tool'};
    }
    if(cls.indexOf('text')>=0) return {txt:'💬 Note',cls:'lbl-text'};
    return {txt:(tl||'•'),cls:'lbl-system'};
  }

  function plainText(html){const t=document.createElement('div');t.innerHTML=html||'';return t.textContent||'';}

  // --- live log (collapsed rows, expand inline) ---
  function addAgentLog(d){
    const empty=document.getElementById('logempty'); if(empty) empty.remove();
    const stick=atBottom(logEl);
    const f=friendly(d);
    const bodyText=plainText(d.body);
    const lines=bodyText?bodyText.split('\n').length:0;
    // headline can contain HTML (e.g. <span class="tool_name">Bash</span>) —
    // strip tags so the one-line preview shows clean text, not markup.
    const preview=(plainText(d.headline)||bodyText||'').replace(/\s+/g,' ').slice(0,120);

    const entry=document.createElement('div'); entry.className='entry';
    const row=document.createElement('div'); row.className='entry-row';
    row.innerHTML=
      '<span class="ts">'+(d.ts||'—')+'</span>'+
      (d.source?'<span class="badge '+(d.badge_class||'')+'">'+d.source+'</span>':'')+
      '<span class="lbl '+f.cls+'">'+f.txt+'</span>'+
      '<span class="prev"></span>'+
      (lines>2?'<span class="more">'+lines+' lines</span>':'')+
      '<button class="ask" title="Ask the manager about this">💬</button>'+
      (d.body?'<span class="chev">▶</span>':'');
    row.querySelector('.prev').textContent=preview;
    entry.appendChild(row);

    // "Ask about this" → drop a quoted reference + content into the chat box, so
    // the manager gets the actual log item as context (option A: quote-to-chat).
    row.querySelector('.ask').addEventListener('click',ev=>{
      ev.stopPropagation();   // don't also toggle the row open
      const content=(bodyText||preview||'').trim().slice(0,600);
      const id=(d.seq!=null)?(' #'+d.seq):'';
      const ref='Re: log'+id+' ['+f.txt+(d.source?(' · '+d.source):'')+
                (d.ts?(' · '+d.ts):'')+']:\n"'+content+'"\n\n';
      msg.value=ref+msg.value;
      autosize(); msg.focus();
      try{msg.setSelectionRange(msg.value.length,msg.value.length);}catch(e){}
      hint.textContent='Add your instruction about this log item, then Send.';
    });

    if(d.body){
      const body=document.createElement('div');
      body.className='entry-body '+(d.body_class||'');
      body.innerHTML=d.body;
      entry.appendChild(body);
      row.onclick=()=>entry.classList.toggle('open');
    }else{
      row.style.cursor='default';
    }
    logEl.appendChild(entry);
    if(stick) logEl.scrollTop=logEl.scrollHeight;

    // update the one-line "current activity" summary in the dashboard
    activityEl.innerHTML='<b>'+(d.source||'Agent')+'</b> · '+f.txt+(preview?' — '+preview:'');
  }

  // --- options / prompt ---
  function renderOptions(opts){
    optionsEl.innerHTML='';
    if(typeof opts==='string'){ try{opts=JSON.parse(opts);}catch(e){opts=[opts];} }
    if(!Array.isArray(opts)) opts=opts?[opts]:[];
    opts.forEach(o=>{
      const b=document.createElement('button');
      b.className='opt'; b.textContent=o; b.onclick=()=>submit(o);
      optionsEl.appendChild(b);
    });
  }

  // --- dashboard ---
  let startedMs=null;
  function fmtElapsed(){
    if(!startedMs) return;
    let s=Math.max(0,Math.floor((Date.now()-startedMs)/1000));
    const h=Math.floor(s/3600); s-=h*3600;
    const m=Math.floor(s/60); s-=m*60;
    const pad=n=>String(n).padStart(2,'0');
    document.getElementById('s-elapsed').textContent=(h>0?h+':':'')+pad(m)+':'+pad(s);
  }
  function setDash(d){
    if(d.phase) document.getElementById('s-phase').textContent=d.phase;
    document.getElementById('s-cost').textContent='$'+Number(d.cost||0).toFixed(2);
    const ag=document.getElementById('s-agents');
    ag.textContent=(d.agents_done||0)+(d.agents_running?(' ✓ '+d.agents_running+'▶'):' done');
    ag.parentElement.classList.toggle('live',!!d.agents_running);
    document.getElementById('s-papers').textContent=d.papers||0;
    document.getElementById('s-files').textContent=d.files||0;
    if(d.started){const t=Date.parse(d.started); if(!isNaN(t)) startedMs=t;}
    fmtElapsed();
  }
  setInterval(fmtElapsed,1000);

  function setStatus(d){
    if(d.phase) document.getElementById('s-phase').textContent=d.phase;
    if(d.closed){connEl.textContent='Session ended';hint.textContent='';awaitingReply=false;composer.classList.remove('awaiting');setThinking(false);return;}
    if(d.thinking){hint.textContent='🤔 Manager is thinking…';connEl.textContent='working';setThinking(true);}
    if(d.waiting===false){awaitingReply=false;composer.classList.remove('awaiting');}
    if(d.label){connEl.textContent=d.label;}
  }

  // --- research whiteboard (the manager's world model) ---
  // Rebuilt in panel_layout order each update. Each section is either a built-in
  // renderer (CORE) or a PI-defined custom block (design_panel). All text is
  // escaped via esc() before insertion, so custom content can't inject markup.
  function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}
  function show(id,on){document.getElementById(id).style.display=on?'':'none';}
  function el(tag,cls,html){const e=document.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;return e;}
  function rsec(title,innerHTML){
    if(!innerHTML||!innerHTML.trim()) return null;   // skip empty sections
    return el('div','r-sec','<div class="r-h">'+esc(title)+'</div>'+innerHTML);
  }
  // The browser receives the raw state file, which stores `assessments` (a
  // list); fall back to its last entry if a derived `latest_assessment` is absent.
  function latestAssessment(d){
    if(d.latest_assessment) return d.latest_assessment;
    const a=d.assessments; return (Array.isArray(a)&&a.length)?a[a.length-1]:null;
  }

  // Built-in section renderers: id -> function(d) -> HTMLElement|null.
  // ---- offline-eval annotations (👍/👎) ----
  // ANN: key -> 'up'|'down' (current verdict, drives thumb highlight + survives
  // the whiteboard's 2s re-render). SNIP: key -> text snapshot sent with the POST
  // so the JSONL record is self-contained for offline eval. Keys are
  // 'assess:<id>' | 'dec:<id>' | 'msg:<seq>'.
  const ANN={}, SNIP={}, ANN_KIND={assess:'assessment',dec:'decision',msg:'message'};
  function annHTML(key,snip){
    if(snip!=null) SNIP[key]=String(snip);
    const v=ANN[key]||'';
    return '<span class="ann" data-key="'+esc(key)+'">'+
      '<button class="ann-btn'+(v==='up'?' on':'')+'" data-v="up" title="Good call">👍</button>'+
      '<button class="ann-btn'+(v==='down'?' on':'')+'" data-v="down" title="Bad call">👎</button></span>';
  }
  function applyAnn(){document.querySelectorAll('.ann').forEach(span=>{
    const v=ANN[span.getAttribute('data-key')]||'';
    span.querySelectorAll('.ann-btn').forEach(x=>x.classList.toggle('on',x.getAttribute('data-v')===v));
  });}
  document.addEventListener('click',e=>{
    const b=e.target.closest&&e.target.closest('.ann-btn'); if(!b) return;
    const span=b.closest('.ann'), key=span.getAttribute('data-key');
    let v=b.getAttribute('data-v');
    if(ANN[key]===v) v='none';                 // click the active thumb again → clear it
    ANN[key]=(v==='none'?'':v);
    span.querySelectorAll('.ann-btn').forEach(x=>x.classList.toggle('on',x.getAttribute('data-v')===ANN[key]));
    fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:key,kind:ANN_KIND[key.split(':')[0]]||'message',
        verdict:v,snapshot:(SNIP[key]||'').slice(0,500)})}).catch(()=>{});
  });
  // Re-paint thumbs for anything already in the DOM (chat bubbles) once we know
  // the saved verdicts. The whiteboard re-reads ANN on its next poll on its own.
  fetch('/annotations').then(r=>r.json()).then(m=>{if(m&&typeof m==='object')Object.assign(ANN,m);applyAnn();}).catch(()=>{});

  const CORE={
    warnings:d=>{
      const w=d.warnings||[]; if(!w.length) return null;
      return el('div','r-warn','<b>⚠ Needs attention</b>'+w.map(x=>'<div class="warn-i">'+esc(x)+'</div>').join(''));
    },
    crux:d=>d.crux?el('div','r-crux','<b>⚡ Crux right now</b>'+esc(d.crux)):null,
    current_best:d=>d.current_best?el('div','r-card','<b>Current best</b>'+esc(d.current_best)):null,
    narrative:d=>{if(!d.narrative)return null;const e=el('div','r-narrative');e.textContent=d.narrative;return e;},
    assessment:d=>{
      const a=latestAssessment(d); if(!a) return null;
      const eng=a.engage_user?'<span class="eng yes">would engage you</span>':'<span class="eng no">proceeding solo</span>';
      return el('div','r-assess','<b>🧭 Manager\'s read</b>'+esc(a.situation||'')+
        (a.uncertainty?'<br><span style="color:#8b949e">Unsure: </span>'+esc(a.uncertainty):'')+
        (a.rationale?'<br><span style="color:#8b949e">Why: </span>'+esc(a.rationale):'')+'<br>'+eng+
        '<div class="ann-foot"><span class="ann-lbl">rate this read</span>'+
        annHTML('assess:'+(a.id||a.ts||''),a.situation||a.crux||'')+'</div>');
    },
    hypotheses:d=>{
      const hyp=d.hypotheses||[]; if(!hyp.length) return null;
      return rsec('Hypotheses',hyp.map(h=>{const st=esc(h.status||'alive');
        return '<div class="hyp st-row-'+st+'"><span class="st st-'+st+'">'+st+'</span>'+
          '<span class="stmt">'+esc(h.statement)+(h.evidence?' <span class="ev">— '+esc(h.evidence)+'</span>':'')+'</span></div>';
      }).join(''));
    },
    open_questions:d=>{
      const q=d.open_questions||[]; if(!q.length) return null;
      return rsec('Open questions',q.map(x=>'<div class="qitem">'+esc(x)+'</div>').join(''));
    },
    decisions:d=>{
      const dec=d.decisions||[]; if(!dec.length) return null;
      return rsec('Decisions',dec.map(x=>'<div class="decitem">'+esc(x.question)+
        (x.chosen?' <span class="ch">→ '+esc(x.chosen)+'</span>':'')+
        annHTML('dec:'+(x.id||x.question||''),x.question)+
        (x.rationale?'<br><span class="rat">'+esc(x.rationale)+'</span>':'')+'</div>').join(''));
    },
    experiments:d=>{
      const exp=d.experiments||[]; if(!exp.length) return null;
      return rsec('Experiments',exp.map(x=>'<div class="expitem">'+
        '<span class="est est-'+esc(x.status||'running')+'">'+esc(x.status||'running')+'</span>'+
        esc(x.run_id)+' '+esc(x.agent)+(x.rationale?' — <span style="color:#6e7681">'+esc(x.rationale)+'</span>':'')+
        (x.result?'<br><span style="color:#8b949e">→ '+esc(x.result)+'</span>':'')+'</div>').join(''));
    },
    incidents:d=>{
      const inc=d.incidents||[]; if(!inc.length) return null;
      return rsec('⚠ Incidents',inc.map(x=>'<div class="inc-i">'+
        '<span class="inc-k">'+esc(x.kind)+'</span> '+esc(x.detail)+
        (x.ts?' <span class="inc-ts">'+esc(String(x.ts).slice(11,19))+'</span>':'')+'</div>').join(''));
    },
  };
  const DEFAULT_ORDER=['warnings','crux','current_best','narrative','assessment','hypotheses','open_questions','decisions','experiments','incidents'];

  // PI-defined custom block -> inner HTML. Every value goes through esc().
  function customInner(sec){
    const kind=sec.kind||'text', data=sec.data;
    const cell=v=>esc(typeof v==='string'?v:(v==null?'':JSON.stringify(v)));
    if(kind==='bullet_list'){
      const arr=Array.isArray(data)?data:(data?[data]:[]);
      return arr.length?'<ul class="r-ul">'+arr.map(x=>'<li>'+cell(x)+'</li>').join('')+'</ul>':'';
    }
    if(kind==='key_value'){
      let rows=[];
      if(Array.isArray(data)) rows=data.map(o=>[o&&o.key,o&&o.value]);
      else if(data&&typeof data==='object') rows=Object.keys(data).map(k=>[k,data[k]]);
      return rows.length?'<table class="r-kv">'+rows.map(r=>'<tr><td class="k">'+cell(r[0])+'</td><td class="v">'+cell(r[1])+'</td></tr>').join('')+'</table>':'';
    }
    if(kind==='table'){
      const cols=(data&&data.columns)||[], body=(data&&data.rows)||[];
      if(!cols.length&&!body.length) return '';
      return '<table class="r-table"><thead><tr>'+cols.map(c=>'<th>'+cell(c)+'</th>').join('')+'</tr></thead><tbody>'+
        body.map(r=>'<tr>'+(Array.isArray(r)?r:[r]).map(c=>'<td>'+cell(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
    }
    if(kind==='status_list'){
      const arr=Array.isArray(data)?data:[];
      return arr.map(it=>{const st=esc(it.status||'alive');const label=it.label||it.statement||'';const note=it.note||it.evidence;
        return '<div class="hyp st-row-'+st+'"><span class="st st-'+st+'">'+st+'</span><span class="stmt">'+esc(label)+(note?' <span class="ev">— '+esc(note)+'</span>':'')+'</span></div>';}).join('');
    }
    return data?('<div class="r-narrative">'+cell(data)+'</div>'):'';   // text (default)
  }

  function setResearch(d){
    const body=document.getElementById('researchbody');
    const sections=d.sections||{};
    let order=(Array.isArray(d.panel_layout)&&d.panel_layout.length)?d.panel_layout.slice():DEFAULT_ORDER.slice();
    // Any custom section not explicitly placed in the layout is appended.
    const placed=new Set(order);
    Object.keys(sections).forEach(id=>{if(!placed.has(id))order.push(id);});
    // Honesty sections are non-suppressible: a PI-designed layout (design_panel)
    // may reorder them, but must not be able to HIDE warnings/incidents — that
    // would let a drifting manager conceal its own failures. Force them in if a
    // custom layout left them out (their renderers return null when empty, so
    // this never adds empty boxes).
    if(!order.includes('warnings')) order.unshift('warnings');
    if(!order.includes('incidents')) order.push('incidents');

    const frag=document.createDocumentFragment();
    let any=false;
    order.forEach(id=>{
      let node=null;
      if(CORE[id]) node=CORE[id](d);
      else if(sections[id]) node=rsec(sections[id].title||id,customInner(sections[id]));
      if(node){frag.appendChild(node);any=true;}
    });
    show('researchempty',!any);
    show('researchbody',any);
    body.innerHTML='';
    body.appendChild(frag);
  }

  // tab switching (Research / Activity)
  document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.tabpane').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab==='research'?'research':'log').classList.add('active');
  }));

  const es=new EventSource('/stream');
  es.onopen=()=>{connEl.textContent='connected';};
  es.addEventListener('message',e=>addMessage(JSON.parse(e.data)));
  es.addEventListener('agentlog',e=>addAgentLog(JSON.parse(e.data)));
  es.addEventListener('dashboard',e=>setDash(JSON.parse(e.data)));
  es.addEventListener('research',e=>setResearch(JSON.parse(e.data)));
  es.addEventListener('prompt',e=>{
    const d=JSON.parse(e.data);
    setThinking(false);   // the manager finished thinking and is now asking
    renderOptions(d.options);
    awaitingReply=true;
    composer.classList.add('awaiting');
    hint.textContent='⏳ Your turn — the manager is waiting for your reply';
    connEl.textContent='waiting for you';
    msg.focus();
  });
  es.addEventListener('status',e=>setStatus(JSON.parse(e.data)));
  es.onerror=()=>{connEl.textContent='connection lost – reload to retry';};

  function submit(text){
    text=(text||'').trim();
    if(!text) return;
    const wasAwaiting=awaitingReply;
    fetch('/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    if(!wasAwaiting){
      // Typed while the manager isn't actively asking: it's queued, not lost.
      hint.textContent='✓ Message queued — the manager will see it at its next checkpoint.';
    }else{
      // Answered a question: the manager is about to think — show it immediately
      // so the wait never looks like the session died.
      hint.textContent='';
      setThinking(true);
    }
    awaitingReply=false;
    composer.classList.remove('awaiting');
    msg.value=''; optionsEl.innerHTML=''; autosize();
  }
  send.onclick=()=>submit(msg.value);
  msg.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit(msg.value);}
  });
  function autosize(){msg.style.height='auto';msg.style.height=Math.min(msg.scrollHeight,160)+'px';}
  msg.addEventListener('input',autosize);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

# Optional branding images live in assets/web/. Keyed by the URL the page
# requests (/brand/logo, /brand/manager) → the file's base name on disk.
_BRAND_STEMS = {"logo": "neurico-logo", "manager": "manager-avatar"}
_BRAND_EXTS = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif")


def _brand_file(project_root: Path, key: str) -> Optional[Path]:
    stem = _BRAND_STEMS.get(key)
    if not stem:
        return None
    base = project_root / "assets" / "web"
    for ext in _BRAND_EXTS:
        p = base / (stem + ext)
        if p.exists():
            return p
    return None


def _make_handler(channel: WebChannel, workspace_name: str, title: str,
                  project_root: Path, workspace_path: Path):
    page = PAGE.replace("{{WORKSPACE}}", workspace_name).replace("{{TITLE}}", title)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path.startswith("/brand/"):
                # Optional branding image; 404 (handled gracefully by the page) if absent.
                f = _brand_file(project_root, self.path[len("/brand/"):])
                if f is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    data = f.read_bytes()
                except OSError:
                    self.send_response(404)
                    self.end_headers()
                    return
                ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                # Fixed branding — cache so it isn't re-fetched every reload.
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)

            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                q = channel.subscribe()
                try:
                    while True:
                        try:
                            ev = q.get(timeout=15)
                        except Exception:
                            # keep-alive ping
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                            continue
                        name = ev.get("event", "message")
                        data = json.dumps(ev)
                        self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    channel.unsubscribe(q)

            elif self.path == "/annotations":
                # Offline-eval thumbs, so the browser can re-paint thumb state on
                # load / reconnect. {key: "up"|"down"}.
                try:
                    latest = _annotations.load_latest(workspace_path)
                except Exception:
                    latest = {}
                body = json.dumps(latest).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/input":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                text = ""
                try:
                    text = json.loads(raw.decode("utf-8")).get("text", "")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    text = raw.decode("utf-8", errors="replace")
                if text:
                    channel.submit_input(text)
                self.send_response(204)
                self.end_headers()

            elif self.path == "/annotate":
                # Record an offline-eval thumb. Never touches the live run.
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    _annotations.append_annotation(
                        workspace_path,
                        key=payload.get("key", ""),
                        kind=payload.get("kind", ""),
                        verdict=payload.get("verdict", ""),
                        snapshot=payload.get("snapshot", ""),
                    )
                    self.send_response(204)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    self.send_response(400)
                self.end_headers()

            else:
                self.send_response(404)
                self.end_headers()

    return Handler


class InteractiveWebServer:
    """Owns the HTTP server thread, the agent-log tailer, and the dashboard feed."""

    def __init__(self, channel: WebChannel, workspace: Path,
                 project_root: Path, title: str, port: int = 7890,
                 host: str = "localhost"):
        self.channel = channel
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)
        self.title = title
        self.host = host
        self.port = port

        self._httpd: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._tailer_thread: Optional[threading.Thread] = None
        self._dash_thread: Optional[threading.Thread] = None
        self._research_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        handler = _make_handler(self.channel, self.workspace.name, self.title,
                                self.project_root, self.workspace)
        # Try the requested port, then a few above it if taken.
        last_err = None
        for port in range(self.port, self.port + 10):
            try:
                self._httpd = ThreadingHTTPServer((self.host, port), handler)
                self.port = port
                break
            except OSError as e:
                last_err = e
        if self._httpd is None:
            raise RuntimeError(f"Could not bind a port near {self.port}: {last_err}")

        self._server_thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._server_thread.start()

        log_dir = self.workspace / "logs"
        self._tailer_thread = threading.Thread(
            target=_tail_agent_logs,
            args=(log_dir, self.channel, self.project_root, self._stop),
            daemon=True)
        self._tailer_thread.start()

        self._dash_thread = threading.Thread(
            target=_emit_dashboard,
            args=(self.workspace, self.project_root, self.channel, self._stop),
            daemon=True)
        self._dash_thread.start()

        self._research_thread = threading.Thread(
            target=_emit_research_state,
            args=(self.workspace, self.channel, self._stop),
            daemon=True)
        self._research_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._httpd is not None:
            threading.Thread(target=self._httpd.shutdown, daemon=True).start()
