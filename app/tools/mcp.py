import json
import subprocess
from dataclasses import dataclass, field
from itertools import count
from urllib.request import Request, urlopen

from app.core.config import settings
from app.core.network import validate_public_url


@dataclass
class MCPServerConfig:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None


class MCPRegistry:
    def __init__(self) -> None:
        self._request_ids = count(1)

    def list_servers(self) -> list[MCPServerConfig]:
        try:
            payload = json.loads(settings.mcp_servers_json)
        except json.JSONDecodeError:
            return []
        servers = []
        for item in payload:
            if isinstance(item, dict) and "name" in item:
                servers.append(
                    MCPServerConfig(
                        name=str(item["name"]),
                        command=item.get("command"),
                        args=list(item.get("args", [])),
                        url=item.get("url"),
                    )
                )
        return servers

    def describe(self) -> str:
        servers = self.list_servers()
        if not servers:
            return "no MCP servers configured"
        return "\n".join(
            f"{server.name}: {server.url or ' '.join([server.command or '', *server.args]).strip()}"
            for server in servers
        )

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        server = next((item for item in self.list_servers() if item.name == server_name), None)
        if server is None:
            return f"mcp_error: server '{server_name}' is not configured"
        if server.url:
            return self._call_http(server, tool_name, arguments)
        if server.command:
            return self._call_stdio(server, tool_name, arguments)
        return f"mcp_error: server '{server_name}' has no command or url"

    def _call_http(self, server: MCPServerConfig, tool_name: str, arguments: dict) -> str:
        validate_public_url(server.url or "")
        payload = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        request = Request(
            server.url or "",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=settings.mcp_timeout_seconds) as response:
            return response.read().decode("utf-8")[:4000]

    def _call_stdio(self, server: MCPServerConfig, tool_name: str, arguments: dict) -> str:
        messages = [
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "researchops-agent", "version": "0.1.0"},
                },
            ),
            self._notification("notifications/initialized", {}),
            self._request("tools/call", {"name": tool_name, "arguments": arguments}),
        ]
        stdin = "\n".join(json.dumps(message) for message in messages) + "\n"
        process = subprocess.run(
            [server.command or "", *server.args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=settings.mcp_timeout_seconds,
            check=False,
        )
        if process.returncode != 0:
            return f"mcp_error: {process.stderr.strip()[:1000]}"
        return process.stdout.strip()[:4000] or "mcp_completed"

    def _request(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "id": next(self._request_ids), "method": method, "params": params}

    def _notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}


mcp_registry = MCPRegistry()
