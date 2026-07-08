import json
import sys
from pathlib import Path

from app.core.config import settings
from app.tools.mcp import MCPRegistry


def test_stdio_mcp_echo_call() -> None:
    _configure_example_server()

    output = MCPRegistry().call_tool("example", "echo", {"text": "hello mcp"})

    assert "hello mcp" in output


def test_stdio_mcp_add_call() -> None:
    _configure_example_server()

    output = MCPRegistry().call_tool("example", "add", {"left": 2, "right": 3})

    assert "5.0" in output


def test_stdio_mcp_search_fixture_call() -> None:
    _configure_example_server()

    output = MCPRegistry().call_tool("example", "search_fixture", {"query": "sandbox"})

    assert "sandbox" in output.lower()


def test_stdio_mcp_unknown_tool_returns_error_payload() -> None:
    _configure_example_server()

    output = MCPRegistry().call_tool("example", "missing_tool", {})

    assert "unknown tool" in output


def test_mcp_tool_allowlist_blocks_unlisted_tool() -> None:
    _configure_example_server()
    settings.mcp_allowed_tools_json = json.dumps({"example": ["echo"]})

    output = MCPRegistry().call_tool("example", "add", {"left": 1, "right": 2})

    assert "not allowed" in output
    settings.mcp_allowed_tools_json = "{}"


def _configure_example_server() -> None:
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
