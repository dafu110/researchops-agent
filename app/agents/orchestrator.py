from uuid import uuid4

from app.api.schemas import ApprovalRequest, AskRequest, AskResponse, FinalAnswer, PlanStepDetail
from app.agents.planner import PlanStep, PlannerAgent
from app.agents.research import ResearchAgent
from app.agents.tool_agent import ToolAgent
from app.approvals.service import approval_service
from app.core.security import UserContext
from app.core.traces import timed_step, trace_store


class AgentOrchestrator:
    """Bounded research control loop with persisted state at every transition."""

    def __init__(self) -> None:
        self.planner = PlannerAgent()
        self.research = ResearchAgent()
        self.tool_agent = ToolAgent()

    async def answer(self, request: AskRequest, user: UserContext | None = None) -> AskResponse:
        tenant_id = user.tenant_id if user else "default"
        user_id = user.user_id if user else "local-dev"
        run_id = str(uuid4())
        trace_store.create_run(
            run_id,
            request.question,
            tenant_id=tenant_id,
            user_id=user_id,
            corpus_ids=request.corpus_ids,
            mode=request.mode,
            require_citations=request.require_citations,
            max_cost_usd=request.max_cost_usd,
        )
        with timed_step(
            run_id,
            "planner",
            input_payload={"question": request.question, "mode": request.mode, "corpus_ids": request.corpus_ids},
            model="rule-planner",
        ) as step:
            plan = await self.planner.plan(request.question)
            step.set_output({"plan": [item.model_dump() for item in plan]})
        plan_details = _plan_details(plan)

        approval_steps = [item for item in plan if item.needs_approval]
        if approval_steps:
            with timed_step(
                run_id,
                "human_approval_requested",
                input_payload={"risk_steps": [item.name for item in approval_steps]},
                model="workflow-controller",
            ) as step:
                approval = approval_service.create(
                    ApprovalRequest(
                        run_id=run_id,
                        action=request.question,
                        reason="Planner detected a potentially high-risk action.",
                        tenant_id=tenant_id,
                        requester_id=user_id,
                    )
                )
                step.set_output({"approval_id": approval.approval_id, "status": approval.status})
            trace_store.set_status(run_id, "awaiting_approval")
            response = self._response(
                run_id,
                "This request contains a high-risk action and is waiting for approval.",
                [],
                plan,
                plan_details,
                requires_approval=True,
                approval_id=approval.approval_id,
                final_answer=FinalAnswer(
                    content="This request contains a high-risk action and is waiting for approval.",
                    citations=[],
                    grounded=False,
                    model="workflow-controller",
                ),
            )
            trace_store.save_response(run_id, response)
            return response

        return await self._execute(run_id, request, user, plan, plan_details)

    async def resume(self, run_id: str, user: UserContext) -> AskResponse:
        record = trace_store.get_run(run_id)
        if record is None or record.tenant_id != user.tenant_id:
            raise ValueError("Run not found.")
        if record.status != "awaiting_approval":
            raise ValueError("Run is not waiting for approval.")
        if not record.approval_id:
            raise ValueError("Run has no pending approval.")
        approval = approval_service.get(record.approval_id, tenant_id=user.tenant_id)
        if approval is None or approval.run_id != run_id or approval.status != "approved":
            raise ValueError("The required approval has not been granted.")
        trace_store.add_step(run_id, "approval_resumed", status="completed", input_payload={"approval_id": approval.approval_id}, output_payload={"status": "resumed"}, model="workflow-controller")
        return await self._execute(run_id, self._request_from_record(record), user, _plan_from_record(record), record.plan_details)

    async def recover(self, run_id: str, user: UserContext) -> AskResponse:
        record = trace_store.get_run(run_id)
        if record is None or record.tenant_id != user.tenant_id:
            raise ValueError("Run not found.")
        recoverable = {"failed", "timeout", "canceled"}
        if record.status not in recoverable and not any(call.status in recoverable for call in trace_store.get_tool_calls(run_id)):
            raise ValueError("Run has no recoverable failed tool step.")
        trace_store.clear_cancel(run_id, user.tenant_id)
        trace_store.add_step(run_id, "failure_recovery", status="completed", input_payload={"previous_status": record.status}, output_payload={"strategy": "reuse original run and idempotency keys"}, model="workflow-controller")
        return await self._execute(run_id, self._request_from_record(record), user, _plan_from_record(record), record.plan_details)

    async def _execute(self, run_id: str, request: AskRequest, user: UserContext | None, plan: list[PlanStep], plan_details: list[PlanStepDetail]) -> AskResponse:
        tenant_id = user.tenant_id if user else "default"
        user_id = user.user_id if user else "local-dev"
        tool_outputs: list[str] = []
        if any(step.needs_tool for step in plan):
            with timed_step(run_id, "tool_agent", input_payload={"question": request.question}, model="bounded-tool-agent") as step:
                tool_results = await self.tool_agent.run(request.question, run_id=run_id, actor_id=user_id, tenant_id=tenant_id)
                step.set_output({"tool_calls": [{"id": result.tool_call_id, "name": result.name, "status": result.status} for result in tool_results]})
            approval_result = next((result for result in tool_results if result.requires_approval), None)
            if approval_result:
                trace_store.set_status(run_id, "awaiting_approval")
                response = self._response(
                    run_id,
                    approval_result.output,
                    [],
                    plan,
                    plan_details,
                    requires_approval=True,
                    approval_id=approval_result.approval_id,
                    final_answer=FinalAnswer(content=approval_result.output, citations=[], grounded=False, model="tool-policy"),
                )
                trace_store.save_response(run_id, response)
                return response
            tool_outputs = [f"{result.name}: {result.output}" for result in tool_results]

        if trace_store.is_cancel_requested(run_id):
            return self._canceled_response(run_id, plan, plan_details)

        with timed_step(run_id, "rag_research", input_payload={"question": request.question, "corpus_ids": request.corpus_ids}, model="research-agent") as step:
            final_answer = await self.research.answer(
                request.question,
                request.corpus_ids,
                plan,
                mode=request.mode,
                tenant_id=tenant_id,
                allowed_sources=user.allowed_sources if user else [],
            )
            step.model = final_answer.model
            step.token_usage = final_answer.token_usage
            step.cost_usd = final_answer.cost_usd
            step.set_output({"grounded": final_answer.grounded, "citation_count": len(final_answer.citations)})

        if trace_store.is_cancel_requested(run_id):
            return self._canceled_response(run_id, plan, plan_details)

        answer = final_answer.content
        if tool_outputs:
            answer = "Tool results:\n" + "\n".join(tool_outputs) + "\n\n" + answer
            final_answer.content = answer
        trace_store.add_step(run_id, "final_response", status="completed", error=None if final_answer.citations or not request.require_citations else "no citations returned", input_payload={"require_citations": request.require_citations}, output_payload={"citation_count": len(final_answer.citations)}, model=final_answer.model, token_usage=final_answer.token_usage, cost_usd=final_answer.cost_usd)
        trace_store.set_status(run_id, "completed")
        response = self._response(run_id, answer, final_answer.citations, plan, plan_details, final_answer=final_answer)
        trace_store.save_response(run_id, response)
        return response

    @staticmethod
    def _request_from_record(record) -> AskRequest:
        return AskRequest(question=record.question, corpus_ids=record.corpus_ids, mode=record.mode, require_citations=record.require_citations, max_cost_usd=record.max_cost_usd)

    @classmethod
    def _canceled_response(cls, run_id: str, plan: list[PlanStep], plan_details: list[PlanStepDetail]) -> AskResponse:
        content = "Run canceled before a final research answer was produced."
        trace_store.add_step(
            run_id,
            "run_canceled",
            status="canceled",
            input_payload={"reason": "cancellation requested"},
            output_payload={"tool_call_count": len(trace_store.get_tool_calls(run_id))},
            model="workflow-controller",
        )
        trace_store.set_status(run_id, "canceled")
        response = cls._response(
            run_id,
            content,
            [],
            plan,
            plan_details,
            final_answer=FinalAnswer(content=content, citations=[], grounded=False, model="workflow-controller"),
        )
        trace_store.save_response(run_id, response)
        return response

    @staticmethod
    def _response(run_id: str, answer: str, citations, plan: list[PlanStep], plan_details: list[PlanStepDetail], requires_approval: bool = False, approval_id: str | None = None, final_answer: FinalAnswer | None = None) -> AskResponse:
        return AskResponse(run_id=run_id, answer=answer, citations=citations, requires_approval=requires_approval, approval_id=approval_id, plan=[item.name for item in plan], plan_details=plan_details, final_answer=final_answer, tool_calls=trace_store.get_tool_calls(run_id))


def _plan_details(plan: list[PlanStep]) -> list[PlanStepDetail]:
    return [PlanStepDetail.model_validate(step.model_dump()) for step in plan]


def _plan_from_record(record) -> list[PlanStep]:
    if not record.plan_details:
        raise ValueError("Run plan is unavailable.")
    return [PlanStep.model_validate(step.model_dump()) for step in record.plan_details]
