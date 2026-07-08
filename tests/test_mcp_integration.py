import json
import sys
from pathlib import Path

from app.core.config import settings
from app.tools.mcp import MCPRegistry


def test_stdio_mcp_echo_call() -> None:
    server_path = Path("scripts/example_mcp_server.py").resolve()
    settings.mcp_servers_json = json.dumps(
        [
            {
                "name": "example",
                "command": sys.executable,
                "args": [str(server_path)],
            }
        ]
    )

    output = MCPRegistry().call_tool("example", "echo", {"text": "hello mcp"})

    assert "hello mcp" in output
