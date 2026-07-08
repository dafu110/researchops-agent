from app.tools.builtin import ToolResult, builtin_tools


class ToolAgent:
    async def run(
        self,
        question: str,
        run_id: str | None = None,
        actor_id: str = "local-dev",
        tenant_id: str = "default",
    ) -> list[ToolResult]:
        return builtin_tools.run(question, run_id=run_id, actor_id=actor_id, tenant_id=tenant_id)
