"""
Embedded web server for NeuriCo Interactive Mode.

Serves a single browser page that unifies two things:
  1. The live conversation with the manager (with an input box) — the
     interactive part previously locked to the terminal.
  2. The live agent transcript from workspaces/<ws>/logs/*.jsonl — the
     read-only view the standalone visualizer already provided.

Architecture A (embedded): this runs in a background thread inside the manager
process and shares in-process queues with a WebChannel — no file polling for
the conversation, no second process.

Routes:
  GET  /         -> the HTML page
  GET  /stream   -> Server-Sent Events: conversation + agent-log + status
  POST /input    -> the browser submits the human's reply
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from interactive.channel import WebChannel

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
                        for item in viz.format_entry(entry, last_ts):
                            channel.emit_raw({"event": "agentlog", **item})
            except OSError:
                continue
        stop.wait(1.0)


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
  body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;padding-bottom:120px}
  #header{position:sticky;top:0;z-index:10;background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;align-items:center;gap:12px}
  #header h1{font-size:15px;color:#58a6ff;font-weight:600}
  #header .ws{color:#8b949e;font-size:12px;font-family:monospace}
  .pill{font-size:11px;color:#d2a8ff;background:#2d1f4e;border-radius:10px;padding:1px 9px}
  #status{margin-left:auto;color:#6e7681;font-size:11px}

  #log{padding:16px 20px;display:flex;flex-direction:column;gap:8px;max-width:1000px;margin:0 auto}

  /* chat bubbles */
  .msg{border-radius:8px;padding:8px 12px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
  .msg .who{font-size:11px;color:#8b949e;margin-bottom:3px}
  .role-manager{background:#11233b;border:1px solid #1f3c5e}
  .role-manager .who{color:#79c0ff}
  .role-user{background:#10261a;border:1px solid #1a3a2e;align-self:flex-end;max-width:80%}
  .role-user .who{color:#56d364}
  .role-system{background:transparent;color:#6e7681;font-size:12px;padding:2px 12px}
  .role-tool{background:#1a1430;border:1px solid #2d1f4e;color:#d2a8ff;font-family:monospace;font-size:12px}

  /* agent transcript entries (mirrors the standalone visualizer) */
  .entry{border-radius:6px;border:1px solid #21262d;overflow:hidden;opacity:.92}
  .entry-header{display:flex;align-items:center;gap:8px;padding:4px 10px;background:#161b22;font-size:11px;color:#8b949e}
  .entry-header .ts{font-family:monospace;color:#6e7681;min-width:64px}
  .badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:600}
  .badge-execution{background:#1f3c5e;color:#79c0ff}
  .badge-resource{background:#1a3a2e;color:#56d364}
  .badge-paper{background:#2d1f4e;color:#d2a8ff}
  .type-label{font-size:10px;padding:1px 6px;border-radius:4px}
  .tl-thinking{background:#2a2a1e;color:#e3b341}.tl-text{background:#1a2a1a;color:#56d364}
  .tl-tool-use{background:#1e2a3a;color:#79c0ff}.tl-tool-result{background:#1e1e2a;color:#a5d6ff}
  .tl-system{background:#1e1e1e;color:#6e7681}.tl-error{background:#3a1e1e;color:#ff7b72}
  .entry-body{padding:6px 12px;font-family:monospace;font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
  .body-thinking{color:#b8a000;font-style:italic;background:#0e0e07}
  .body-tool-use{color:#79c0ff;background:#0a111a}
  .body-tool-result{color:#8b949e;background:#0a0a12;font-size:11px}
  .body-text{color:#e6edf3}.body-system{color:#6e7681;background:#0e0e0e;font-size:11px}
  .body-error{color:#ff7b72;background:#120a0a}
  details summary{cursor:pointer;list-style:none;color:#58a6ff;font-size:11px}
  details summary::-webkit-details-marker{display:none}
  details summary::before{content:"▶ show "}details[open] summary::before{content:"▼ hide "}
  .tool-name{color:#ffa657;font-weight:bold}.tool-key{color:#79c0ff}.tool-val{color:#aff5b4}

  /* composer */
  #composer{position:fixed;bottom:0;left:0;right:0;background:#161b22;border-top:1px solid #30363d;padding:10px 20px}
  #composer .wrap{max-width:1000px;margin:0 auto}
  #hint{font-size:11px;color:#e3b341;min-height:15px;margin-bottom:6px}
  #options{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
  .opt{background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:14px;padding:4px 12px;font-size:13px;cursor:pointer}
  .opt:hover{background:#30363d}
  #inputrow{display:flex;gap:8px;align-items:flex-end}
  #msg{flex:1;resize:none;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 10px;font-family:inherit;font-size:14px;line-height:1.4;max-height:160px}
  #msg:focus{outline:none;border-color:#58a6ff}
  #send{background:#238636;color:#fff;border:none;border-radius:8px;padding:9px 18px;font-size:14px;font-weight:600;cursor:pointer}
  #send:hover{background:#2ea043}
</style>
</head>
<body>
  <div id="header">
    <h1>NeuriCo Interactive</h1>
    <span class="ws">{{WORKSPACE}}</span>
    <span id="phase" class="pill" style="display:none"></span>
    <span id="status">Connecting…</span>
  </div>
  <div id="log"></div>
  <div id="composer"><div class="wrap">
    <div id="hint"></div>
    <div id="options"></div>
    <div id="inputrow">
      <textarea id="msg" rows="1" placeholder="Type a message to the manager… (Enter to send, Shift+Enter for newline)"></textarea>
      <button id="send">Send</button>
    </div>
  </div></div>

<script>
  const log=document.getElementById('log');
  const statusEl=document.getElementById('status');
  const phaseEl=document.getElementById('phase');
  const hint=document.getElementById('hint');
  const optionsEl=document.getElementById('options');
  const msg=document.getElementById('msg');
  const send=document.getElementById('send');

  function nearBottom(){return window.innerHeight+window.scrollY>=document.body.offsetHeight-120;}
  function toBottom(){window.scrollTo(0,document.body.scrollHeight);}

  function addMessage(d){
    if(!d.text) return;
    const stick=nearBottom();
    const el=document.createElement('div');
    el.className='msg role-'+(d.role||'manager');
    const who={manager:'🤖 Manager',user:'🧑 You',system:'',tool:'🔧 Tool'}[d.role];
    let html='';
    if(who) html+='<div class="who">'+who+'</div>';
    html+='<div class="text"></div>';
    el.innerHTML=html;
    el.querySelector('.text').textContent=d.text;
    log.appendChild(el);
    if(stick) toBottom();
  }

  function addAgentLog(d){
    const stick=nearBottom();
    const entry=document.createElement('div');
    entry.className='entry';
    const hdr=document.createElement('div');
    hdr.className='entry-header';
    hdr.innerHTML='<span class="ts">'+(d.ts||'—')+'</span>'+
      '<span class="badge '+(d.badge_class||'')+'">'+(d.source||'')+'</span>'+
      '<span class="type-label '+(d.type_label_class||'')+'">'+(d.type_label||'')+'</span>'+
      (d.headline?'<span style="color:#8b949e;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+d.headline+'</span>':'');
    entry.appendChild(hdr);
    if(d.body){
      const body=document.createElement('div');
      body.className='entry-body '+(d.body_class||'');
      body.innerHTML=d.body;
      entry.appendChild(body);
    }
    log.appendChild(entry);
    if(stick) toBottom();
  }

  function renderOptions(opts){
    optionsEl.innerHTML='';
    // Tolerate a stringified array from prompt-based backends.
    if(typeof opts==='string'){ try{opts=JSON.parse(opts);}catch(e){opts=[opts];} }
    if(!Array.isArray(opts)) opts=opts?[opts]:[];
    opts.forEach(o=>{
      const b=document.createElement('button');
      b.className='opt'; b.textContent=o;
      b.onclick=()=>submit(o);
      optionsEl.appendChild(b);
    });
  }

  function setStatus(d){
    if(d.phase){phaseEl.style.display='';phaseEl.textContent='phase: '+d.phase;}
    if(d.closed){statusEl.textContent='Session ended';hint.textContent='';return;}
    if(d.thinking){hint.textContent='🤔 Manager is thinking…';statusEl.textContent='working';}
    if(d.waiting===false){hint.textContent='';}
    if(d.label){statusEl.textContent=d.label;}
  }

  const es=new EventSource('/stream');
  es.onopen=()=>{statusEl.textContent='connected';};
  es.addEventListener('message',e=>addMessage(JSON.parse(e.data)));
  es.addEventListener('agentlog',e=>addAgentLog(JSON.parse(e.data)));
  es.addEventListener('prompt',e=>{
    const d=JSON.parse(e.data);
    renderOptions(d.options);
    hint.textContent='⏳ Your turn — reply below';
    statusEl.textContent='waiting for you';
    msg.focus();
  });
  es.addEventListener('status',e=>setStatus(JSON.parse(e.data)));
  es.onerror=()=>{statusEl.textContent='connection lost – reload to retry';};

  function submit(text){
    text=(text||'').trim();
    if(!text) return;
    fetch('/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    msg.value=''; optionsEl.innerHTML=''; hint.textContent=''; autosize();
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

def _make_handler(channel: WebChannel, workspace_name: str, title: str):
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
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


class InteractiveWebServer:
    """Owns the HTTP server thread and the agent-log tailer thread."""

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
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        handler = _make_handler(self.channel, self.workspace.name, self.title)
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

    def stop(self) -> None:
        self._stop.set()
        if self._httpd is not None:
            threading.Thread(target=self._httpd.shutdown, daemon=True).start()
