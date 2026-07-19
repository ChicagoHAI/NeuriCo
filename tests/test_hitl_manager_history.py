import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_manager_history import HitlManagerHistory


def test_replayed_conversation_record_does_not_duplicate_recall_chunks(tmp_path: Path) -> None:
    history = HitlManagerHistory(tmp_path / "manager")
    record = {
        "id": "message-1",
        "type": "message",
        "speaker": "human",
        "content": "Keep the broader evidence direction.",
        "timestamp": "2026-07-18T12:00:00Z",
    }

    history.append(record)
    history.append(record)

    recalled = history.recall("broader evidence")
    assert recalled.count("Keep the broader evidence direction.") == 1
