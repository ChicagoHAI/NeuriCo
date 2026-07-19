import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.whiteboard import Whiteboard


def test_whiteboard_restores_live_file_when_required_version_capture_fails(tmp_path: Path) -> None:
    whiteboard_path = tmp_path / "whiteboard.json"
    marker = tmp_path / ".current_attempt"
    marker.write_text("attempt_1\n", encoding="utf-8")
    original = b'{"schema_version":2,"next_id_num":1,"tips":[]}\n'
    whiteboard_path.write_bytes(original)
    whiteboard = Whiteboard(
        tmp_path,
        path=whiteboard_path,
        attempt_marker_path=marker,
        record_version=lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")),
        restore_on_version_failure=True,
    ).load()
    whiteboard.add_tip("A valid tip.", "insight")

    with pytest.raises(RuntimeError, match="git unavailable"):
        whiteboard.save()

    assert whiteboard_path.read_bytes() == original
