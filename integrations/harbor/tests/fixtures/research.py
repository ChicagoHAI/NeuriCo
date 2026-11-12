"""No-model research substitute copied only into a temporary validation source."""

import json
import os
import time
from pathlib import Path


def run_research(self, **kwargs):
    from core.hitl_manager_history import HitlManagerHistory
    from core.hitl_run_control import hitl_run_stop_requested
    from core.idea_manager import IdeaManager
    from core.trace_retention import current_trace_invocation, retain_trace, retained_invocation

    idea = IdeaManager(Path(os.environ["NEURICO_IDEAS"])).get_idea(kwargs["idea_id"])
    prompt = idea["idea"]["background"]["description"]
    workspace = Path.cwd()
    HitlManagerHistory(workspace / ".neurico/hitl/manager")
    sessions = Path(os.environ["CODEX_HOME"]) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    for kind in ("manager", "worker"):
        output = json.dumps({"type": "thread.started", "thread_id": kind}) + "\n"
        events = [
            {"type": "session_meta", "payload": {"id": kind, "cli_version": "fixture"}},
            {"type": "turn_context", "payload": {"model": "fixture", "effort": "high"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": prompt}},
        ]
        (sessions / f"{kind}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        log = workspace / "logs/worker.jsonl"
        log.parent.mkdir(exist_ok=True)
        with retained_invocation(
            kind,
            prompt=prompt,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            work_dir=str(workspace),
            transcript_file=str(log),
            log_file=str(log),
        ) as outcome:
            if kind == "manager":
                retain_trace(
                    "provider_input", invocation_id=current_trace_invocation(), prompt=prompt
                )
                retain_trace(
                    "provider_output",
                    invocation_id=current_trace_invocation(),
                    stdout=output,
                    stderr="fixture diagnostic",
                    process_started=True,
                    return_code=0,
                )
            else:
                log.write_text(output)
            outcome.update(success=True, process_started=True)
    Path("answer.bin").write_bytes(b"\x00fixture result")
    if "timeout" in prompt:
        while not hitl_run_stop_requested():
            time.sleep(0.05)
        print("fixture cancellation settled", flush=True)
        return {"success": False}
    if "failed-child" in prompt:
        raise RuntimeError("fixture failed child")
    Path("answer.txt").write_text("pass\n")
    return {"success": True}
