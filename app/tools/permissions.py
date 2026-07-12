from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk_level: str
    requires_approval: bool = False
    timeout_seconds: int = 3
    max_attempts: int = 2
    idempotent: bool = True
    cancellable: bool = True


TOOL_POLICIES = {
    "calculator": ToolPolicy("calculator", "low", timeout_seconds=1),
    "knowledge_stats": ToolPolicy("knowledge_stats", "low", timeout_seconds=1),
    "eval_summary": ToolPolicy("eval_summary", "low", timeout_seconds=1),
    "read_only_sql": ToolPolicy("read_only_sql", "medium", timeout_seconds=2),
    "python_sandbox": ToolPolicy("python_sandbox", "medium", timeout_seconds=5, max_attempts=1, idempotent=False),
    "mcp_registry": ToolPolicy("mcp_registry", "medium", timeout_seconds=2),
    "mcp_call": ToolPolicy("mcp_call", "high", requires_approval=True, timeout_seconds=8, max_attempts=1, idempotent=False),
    "report_writer": ToolPolicy("report_writer", "medium", timeout_seconds=2, max_attempts=1, idempotent=False),
}


def policy_for_tool(name: str) -> ToolPolicy:
    return TOOL_POLICIES.get(
        name,
        ToolPolicy(name, "high", requires_approval=True, max_attempts=1, idempotent=False),
    )
