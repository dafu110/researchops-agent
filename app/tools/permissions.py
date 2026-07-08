from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk_level: str
    requires_approval: bool = False


TOOL_POLICIES = {
    "calculator": ToolPolicy("calculator", "low"),
    "knowledge_stats": ToolPolicy("knowledge_stats", "low"),
    "eval_summary": ToolPolicy("eval_summary", "low"),
    "read_only_sql": ToolPolicy("read_only_sql", "medium"),
    "python_sandbox": ToolPolicy("python_sandbox", "medium"),
    "mcp_registry": ToolPolicy("mcp_registry", "medium"),
    "mcp_call": ToolPolicy("mcp_call", "high", requires_approval=True),
    "report_writer": ToolPolicy("report_writer", "medium"),
}


def policy_for_tool(name: str) -> ToolPolicy:
    return TOOL_POLICIES.get(name, ToolPolicy(name, "high", requires_approval=True))
