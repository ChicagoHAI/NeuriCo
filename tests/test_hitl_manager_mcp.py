import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.hitl_manager_mcp import _handle
from core.hitl_manager_react import HitlManager


class _Channel:
    def send(self, *_args, **_kwargs):
        return None

    def set_resolution_reply_handler(self, _handler):
        return None


def test_cli_mcp_bridge_exposes_only_current_runtime_tool_surface(tmp_path: Path) -> None:
    manager = HitlManager({"manager": {"llm_backend": "cli"}}, work_dir=tmp_path, channel=_Channel())
    try:
        manager._ensure_cli_mcp_bridge()
        tools = manager._mcp_tools()
        names = {tool["name"] for tool in tools}

        assert "list_workspace" in names
        assert "prune_frontier" not in names
        assert manager._mcp_config_path.exists()
        assert json.loads(manager._mcp_config_path.read_text())["mcpServers"]
    finally:
        manager.stop()

    assert not manager._mcp_config_path.exists()


def test_cli_mcp_bridge_revalidates_a_tool_at_execution_time(tmp_path: Path) -> None:
    manager = HitlManager({"manager": {"llm_backend": "cli"}}, work_dir=tmp_path, channel=_Channel())
    try:
        content, is_error = manager._execute_mcp_tool(
            "prune_frontier", {"node_sha": "abc", "reason": "test"}
        )
    finally:
        manager.stop()

    assert is_error is True
    assert "unavailable" in content


def test_cli_mcp_bridge_is_recreated_after_private_state_restore(tmp_path: Path) -> None:
    manager = HitlManager({"manager": {"llm_backend": "cli"}}, work_dir=tmp_path, channel=_Channel())
    try:
        manager._ensure_cli_mcp_bridge()
        original = json.loads(manager._mcp_config_path.read_text(encoding="utf-8"))

        manager.reload_after_runtime_restore()

        assert manager._mcp_server is None
        assert not manager._mcp_config_path.exists()

        manager._ensure_cli_mcp_bridge()
        recreated = json.loads(manager._mcp_config_path.read_text(encoding="utf-8"))
        assert recreated != original
    finally:
        manager.stop()


def test_mcp_adapter_translates_tools_list_and_call(monkeypatch) -> None:
    calls = []

    def fake_runtime_request(path, payload):
        calls.append((path, payload))
        if path == "/mcp/tools":
            return {"tools": [{"name": "list_workspace"}]}
        return {"content": "workspace listed", "is_error": False}

    monkeypatch.setattr("core.hitl_manager_mcp._runtime_request", fake_runtime_request)

    listed = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    called = _handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "list_workspace",
                "arguments": {"path": "."},
            },
        }
    )

    assert listed["result"]["tools"][0]["name"].endswith("list_workspace")
    assert called["result"] == {"content": [{"type": "text", "text": "workspace listed"}], "isError": False}
    assert calls == [
        ("/mcp/tools", {}),
        (
            "/mcp/call",
            {"name": "list_workspace", "arguments": {"path": "."}},
        ),
    ]
