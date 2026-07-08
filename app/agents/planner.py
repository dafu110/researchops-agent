from pydantic import BaseModel


class PlanStep(BaseModel):
    name: str
    stage: str
    goal: str
    mode: str = "automatic"
    tool_hint: str | None = None
    risk_level: str = "low"
    confidence: float = 1.0
    needs_tool: bool = False
    needs_approval: bool = False


class PlannerAgent:
    async def plan(self, question: str) -> list[PlanStep]:
        lowered = question.lower()
        risk_level = self._risk_level(lowered)
        tool_hint = self._tool_hint(lowered)

        plan = [
            PlanStep(
                name="intake",
                stage="intake",
                goal="Normalize the user request, identify evidence needs, and preserve tenant/source scope.",
                confidence=0.92,
            ),
            PlanStep(
                name="retrieve_evidence",
                stage="retrieval",
                goal=f"Collect grounded evidence for: {question}",
                confidence=0.88,
            ),
        ]

        if tool_hint:
            plan.insert(
                1,
                PlanStep(
                    name="tool_call",
                    stage="execution",
                    goal="Use the safest matching built-in tool before composing the final answer.",
                    tool_hint=tool_hint,
                    risk_level="high" if tool_hint == "mcp" else "medium",
                    confidence=0.84,
                    needs_tool=True,
                ),
            )

        plan.append(
            PlanStep(
                name="compose_answer",
                stage="response",
                goal="Synthesize a grounded answer with citations and explicit uncertainty when evidence is incomplete.",
                confidence=0.9,
            )
        )

        if self._needs_report(lowered):
            plan.append(
                PlanStep(
                    name="synthesize_report",
                    stage="artifact",
                    goal="Turn grounded evidence into a concise research report.",
                    tool_hint="report",
                    risk_level="medium",
                    confidence=0.82,
                )
            )

        requires_tool_approval = self._tool_requires_approval(tool_hint, lowered)
        if risk_level in {"high", "critical"} or requires_tool_approval:
            plan.append(
                PlanStep(
                    name="human_approval",
                    stage="approval",
                    goal="Request approval before executing a high-risk, destructive, or externally delegated action.",
                    mode="human_required",
                    risk_level=risk_level if risk_level in {"high", "critical"} else "high",
                    confidence=0.95,
                    needs_approval=True,
                )
            )
        return plan

    def _risk_level(self, lowered: str) -> str:
        critical_terms = (
            "delete production",
            "drop database",
            "all production data",
            "删除生产",
            "清空",
        )
        risky_terms = (
            "delete",
            "drop",
            "update",
            "insert",
            "send email",
            "create pr",
            "remove",
            "write",
            "删除",
            "写入",
            "发送",
            "发邮件",
        )
        if any(term in lowered for term in critical_terms):
            return "critical"
        if any(term in lowered for term in risky_terms):
            return "high"
        return "low"

    def _tool_hint(self, lowered: str) -> str | None:
        tool_terms = {
            "calculator": ("calculate", "计算"),
            "eval": ("eval", "评估", "metric", "document count", "文档数量"),
            "knowledge": ("knowledge", "知识库", "documents", "chunks"),
            "sql": ("select ", "sql"),
            "sandbox": ("```python", "python"),
            "mcp": ("mcp",),
            "report": ("report", "markdown", "报告"),
        }
        for tool_name, terms in tool_terms.items():
            if any(term in lowered for term in terms):
                return tool_name
        return None

    def _needs_report(self, lowered: str) -> bool:
        return any(term in lowered for term in ("report", "summary", "analysis", "报告", "总结", "分析"))

    def _tool_requires_approval(self, tool_hint: str | None, lowered: str) -> bool:
        return tool_hint == "mcp" and "mcp call" in lowered
