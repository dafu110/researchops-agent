from pydantic import BaseModel


class PlanStep(BaseModel):
    name: str
    goal: str
    needs_tool: bool = False
    needs_approval: bool = False


class PlannerAgent:
    async def plan(self, question: str) -> list[PlanStep]:
        lowered = question.lower()
        risky_terms = (
            "delete",
            "drop",
            "update",
            "insert",
            "send email",
            "create pr",
            "remove",
            "\u5220\u9664",
            "\u5199\u5165",
            "\u53d1\u9001",
            "\u53d1\u90ae\u4ef6",
        )
        needs_approval = any(term in lowered for term in risky_terms)
        plan = [
            PlanStep(
                name="research",
                goal=f"Collect grounded evidence for: {question}",
            )
        ]
        if any(
            term in lowered
            for term in (
                "calculate",
                "\u8ba1\u7b97",
                "eval",
                "\u8bc4\u4f30",
                "metric",
                "document count",
                "\u6587\u6863\u6570\u91cf",
                "knowledge",
                "\u77e5\u8bc6\u5e93",
                "select ",
                "```python",
                "mcp",
                "report",
                "markdown",
            )
        ):
            plan.insert(
                0,
                PlanStep(
                    name="tool_call",
                    goal="Use built-in tools for calculation, SQL, sandbox, MCP, or reports.",
                    needs_tool=True,
                ),
            )
        report_terms = (
            "report",
            "summary",
            "analysis",
            "\u62a5\u544a",
            "\u603b\u7ed3",
            "\u5206\u6790",
        )
        if any(term in lowered for term in report_terms):
            plan.append(
                PlanStep(
                    name="synthesize_report",
                    goal="Turn grounded evidence into a concise research report.",
                )
            )
        if needs_approval:
            plan.append(
                PlanStep(
                    name="human_approval",
                    goal="Request approval before executing a high-risk action.",
                    needs_approval=True,
                )
            )
        return plan
