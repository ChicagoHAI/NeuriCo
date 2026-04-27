"""
Session State Management

Handles persistent session state and conversation history for the
interactive manager. Enables resume, error recovery, and context compaction.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import uuid
from datetime import datetime


class SessionState:
    """
    Manages persistent session state stored in .neurico/manager_session.json
    and conversation history in .neurico/manager_conversation.jsonl.
    """

    def __init__(self, work_dir: Path, idea_id: str, idea_title: str, provider: str):
        self.work_dir = Path(work_dir)
        self.neurico_dir = self.work_dir / ".neurico"
        self.neurico_dir.mkdir(parents=True, exist_ok=True)

        self.session_file = self.neurico_dir / "manager_session.json"
        self.conversation_file = self.neurico_dir / "manager_conversation.jsonl"

        # Load or create session
        if self.session_file.exists():
            with open(self.session_file) as f:
                self.state = json.load(f)
        else:
            self.state = {
                "session_id": str(uuid.uuid4()),
                "started_at": datetime.now().isoformat(),
                "idea_id": idea_id,
                "idea_title": idea_title,
                "provider": provider,
                "status": "active",
                "agents_run": [],
                "conversation_summary": "",
                "key_findings": [],
                "open_questions": [],
                "phase": "starting",
                "user_preferences": {}
            }
            self._save_state()

    def _save_state(self):
        """Write session state to disk."""
        with open(self.session_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    @property
    def session_id(self) -> str:
        return self.state["session_id"]

    @property
    def is_resuming(self) -> bool:
        """True if this session was loaded from an existing file."""
        return len(self.state.get("agents_run", [])) > 0

    def record_agent_start(self, agent_name: str, run_id: str):
        """Record that an agent has been started."""
        self.state["agents_run"].append({
            "agent": agent_name,
            "run_id": run_id,
            "started": datetime.now().isoformat(),
            "completed": None,
            "success": None,
            "exit_code": None
        })
        self._save_state()

    def record_agent_complete(self, run_id: str, success: bool, exit_code: Optional[int] = None):
        """Record that an agent has completed."""
        for entry in self.state["agents_run"]:
            if entry["run_id"] == run_id:
                entry["completed"] = datetime.now().isoformat()
                entry["success"] = success
                entry["exit_code"] = exit_code
                break
        self._save_state()

    def update_findings(self, key_findings: Optional[List[str]] = None,
                        open_questions: Optional[List[str]] = None,
                        phase: Optional[str] = None):
        """Update session findings and questions."""
        if key_findings:
            # Append new findings (deduplicate)
            existing = set(self.state["key_findings"])
            for f in key_findings:
                if f not in existing:
                    self.state["key_findings"].append(f)
        if open_questions is not None:
            self.state["open_questions"] = open_questions
        if phase:
            self.state["phase"] = phase
        self._save_state()

    def update_conversation_summary(self, summary: str):
        """Update the compacted conversation summary."""
        self.state["conversation_summary"] = summary
        self._save_state()

    def mark_completed(self):
        """Mark the session as completed."""
        self.state["status"] = "completed"
        self.state["completed_at"] = datetime.now().isoformat()
        self._save_state()

    # --- Conversation history ---

    def append_message(self, message: Dict[str, Any]):
        """Append a message to the conversation history."""
        with open(self.conversation_file, 'a') as f:
            f.write(json.dumps(message) + '\n')

    def load_conversation(self, max_messages: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load conversation history from disk."""
        if not self.conversation_file.exists():
            return []

        messages = []
        with open(self.conversation_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))

        if max_messages and len(messages) > max_messages:
            return messages[-max_messages:]
        return messages

    def rewrite_conversation(self, messages: List[Dict[str, Any]]):
        """Rewrite the conversation history (used during compaction)."""
        with open(self.conversation_file, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

    def get_resume_context(self) -> str:
        """Build a context string for resuming a session."""
        summary = self.state.get("conversation_summary", "")
        findings = self.state.get("key_findings", [])
        questions = self.state.get("open_questions", [])
        agents = self.state.get("agents_run", [])
        phase = self.state.get("phase", "unknown")

        parts = [f"Resuming session (phase: {phase})."]

        if summary:
            parts.append(f"\nPrevious session summary:\n{summary}")

        if findings:
            parts.append("\nKey findings so far:")
            for f in findings:
                parts.append(f"- {f}")

        if questions:
            parts.append("\nOpen questions:")
            for q in questions:
                parts.append(f"- {q}")

        if agents:
            parts.append("\nAgents run in this session:")
            for a in agents:
                status = "completed" if a.get("success") else ("failed" if a.get("success") is False else "in progress")
                parts.append(f"- {a['agent']} ({a['run_id']}): {status}")

        return "\n".join(parts)

    def generate_run_id(self, agent_name: str) -> str:
        """Generate a unique run_id for an agent invocation."""
        # Count existing runs of this agent type
        prefix_map = {
            'resource_finder': 'rf',
            'experiment_runner': 'er',
            'paper_writer': 'pw',
            'comment_handler': 'ch'
        }
        prefix = prefix_map.get(agent_name, agent_name[:2])
        count = sum(1 for a in self.state["agents_run"] if a["agent"] == agent_name)
        return f"{prefix}_{count + 1:03d}"
