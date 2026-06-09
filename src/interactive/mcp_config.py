"""
MCP Configuration Writer for Interactive Mode

Writes a .mcp.json file into the workspace directory that registers
the NeuriCo MCP server for a specific session. Claude Code discovers
this file when launched from the workspace directory.
"""

import json
import sys
from pathlib import Path


def write_mcp_config(work_dir: Path, idea_file: Path, provider: str,
                     idea_id: str, idea_title: str,
                     project_root: Path) -> Path:
    """
    Write .mcp.json into work_dir, registering the NeuriCo MCP server
    with session-specific environment variables.

    Returns the path to the written config file.
    """
    python_cmd = sys.executable

    config = {
        "mcpServers": {
            "neurico": {
                "command": python_cmd,
                "args": [
                    str(project_root / "src" / "interactive" / "mcp_server.py")
                ],
                "env": {
                    "NEURICO_WORK_DIR": str(work_dir),
                    "NEURICO_IDEA_FILE": str(idea_file),
                    "NEURICO_PROVIDER": provider,
                    "NEURICO_IDEA_ID": idea_id,
                    "NEURICO_IDEA_TITLE": idea_title,
                }
            }
        }
    }

    config_path = work_dir / ".mcp.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path
