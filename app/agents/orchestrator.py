from uuid import uuid4

from app.api.schemas import ApprovalRequest, AskRequest, AskResponse, PlanStepDetail
from app.agents.planner import PlanStep, PlannerAgent
from app.agents.research import ResearchAgent
from app.agents.tool_agent import ToolAgent
from app.approvals.service import approval_service
from app.core.security import UserContext
from app.core.traces import timed_step, trace_store


class AgentOrchestrator:
    def __init__(self) -> None:
        self.planner = PlannerAgent()
        self.research = ResearchAgent()
        self.tool_agent = ToolAgent()

    async def answer(self, request: AskRequest, user: UserContext | None = None) -> AskResponse:
        tenant_id = user.tenant_id if user else None
        user_id = user.user_id if user else "local-dev"
        allowed_sources = user.allowed_sources if user else []
        run_id = str(uuid4())
        trace_store.create_run(
            run_id,
            request.question,
            tenant_id=tenant_id or "default",
            user_id=user_id,
        )
        with timed_step(run_id, "planner"):
            plan = await self.planner.plan(request.question)
        plan_details = _plan_details(plan)

        approval_steps = [step for step in plan if step.needs_approval]
        if approval_steps:
            with timed_step(run_id, "human_approval_requested"):
                approval = approval_service.create(
                    ApprovalRequest(
                        run_id=run_id,
                        action=request.question,
                        reason="Planner detected a potentially high-risk action.",
                        tenant_id=tenant_id or "default",
                        requester_id=user_id,
                    )
                )
            trace_store.set_status(run_id, "awaiting_approval")
            return AskResponse(
                run_id=run_id,
                answer="This request contains a high-risk action and is waiting for approval.",
                citations=[],
                requires_approval=True,
                approval_id=approval.approval_id,
                plan=[step.name for step in plan],
                plan_details=plan_details,
            )

        tool_outputs: list[str] = []
        if any(step.needs_tool for step in plan):
            with timed_step(run_id, "tool_agent"):
                tool_outputs = [
                    f"{result.name}: {result.output}"
                    for result in await self.tool_agent.run(
                        request.question,
                        run_id=run_id,
                        actor_id=user_id,
                        tenant_id=tenant_id or "default",
                    )
                ]

        with timed_step(run_id, "rag_research"):
            answer, citations = await self.research.answer(
                request.question,
                request.corpus_ids,
                plan,
                tenant_id=tenant_id,
                allowed_sources=allowed_sources,
            )

        if tool_outputs:
            answer = "Tool results:\n" + "\n".join(tool_outputs) + "\n\n" + answer

        trace_store.add_step(
            run_id,
            "final_response",
            status="completed",
            error=None if citations or not request.require_citations else "no citations returned",
        )
        trace_store.set_status(run_id, "completed")
        return AskResponse(
            run_id=run_id,
            answer=answer,
            citations=citations,
            requires_approval=False,
            approval_id=None,
            plan=[step.name for step in plan],
            plan_details=plan_details,
        )


def _plan_details(plan: list[PlanStep]) -> list[PlanStepDetail]:
    return [PlanStepDetail.model_validate(step.model_dump()) for step in plan]
