import json
import sys


def response(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def handle_tool_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "echo":
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(arguments.get("text", "")),
                }
            ]
        }
    if name == "add":
        left = float(arguments.get("left", 0))
        right = float(arguments.get("right", 0))
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(left + right),
                }
            ]
        }
    if name == "search_fixture":
        query = str(arguments.get("query", "")).lower()
        corpus = [
            "ResearchOps supports RAG citations and trace timelines.",
            "Tool execution includes SQL, sandbox, reports, and MCP.",
            "Approval gates protect high-risk agent actions.",
        ]
        matches = [item for item in corpus if query in item.lower()]
        return {"content": [{"type": "text", "text": "\n".join(matches) or "no matches"}]}
    if name == "status":
        return {"content": [{"type": "text", "text": "example-mcp healthy"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method")
        if "id" not in message:
            continue
        if method == "initialize":
            print(
                json.dumps(
                    response(
                        message["id"],
                        {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "example-mcp", "version": "0.1.0"},
                        },
                    )
                ),
                flush=True,
            )
        elif method == "tools/call":
            print(json.dumps(response(message["id"], handle_tool_call(message.get("params") or {}))), flush=True)
        elif method == "tools/list":
            print(
                json.dumps(
                    response(
                        message["id"],
                        {
                            "tools": [
                                {"name": "echo", "description": "Echo text."},
                                {"name": "add", "description": "Add two numbers."},
                                {"name": "search_fixture", "description": "Search fixture text."},
                                {"name": "status", "description": "Return server health."},
                            ]
                        },
                    )
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
