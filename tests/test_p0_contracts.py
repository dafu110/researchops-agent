import asyncio

from app.agents.orchestrator import AgentOrchestrator, _plan_details
from app.api.routes import metrics
from app.api.schemas import ApprovalDecision, AskRequest
from app.approvals.service import approval_service
from app.core.security import UserContext
from app.core.traces import trace_store


def test_run_persists_typed_step_final_answer_and_tool_contract() -> None:
    user = UserContext(user_id="p0-contracts", tenant_id="p0-contracts", role="admin")
    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(question="calculate 2 * 5", require_citations=False),
            user,
        )
    )

    assert response.final_answer is not None
    assert response.final_answer.model == "deterministic-rag"
    assert response.tool_calls[0].tool.arguments == {"expression": "2 * 5"}
    assert response.tool_calls[0].idempotency_key
    trace = trace_store.get_steps(response.run_id)
    assert trace[0].input_payload["question"] == "calculate 2 * 5"
    assert any(step.output_payload for step in trace)


def test_cancellation_stops_at_the_next_tool_boundary() -> None:
    user = UserContext(user_id="p0-cancel", tenant_id="p0-cancel", role="admin")
    orchestrator = AgentOrchestrator()
    request = AskRequest(question="calculate 8 * 5", require_citations=False)
    run_id = "p0-cancel-run"
    trace_store.create_run(run_id, request.question, tenant_id=user.tenant_id, user_id=user.user_id)
    plan = asyncio.run(orchestrator.planner.plan(request.question))
    assert trace_store.request_cancel(run_id, user.tenant_id)

    response = asyncio.run(orchestrator._execute(run_id, request, user, plan, _plan_details(plan)))

    assert response.final_answer is not None
    assert response.final_answer.model == "workflow-controller"
    assert trace_store.get_run(run_id).status == "canceled"
    assert any(call.status == "canceled" for call in response.tool_calls)


def test_failure_recovery_reuses_the_same_run_id() -> None:
    user = UserContext(user_id="p0-recover", tenant_id="p0-recover", role="admin")
    orchestrator = AgentOrchestrator()
    request = AskRequest(question="```python\nwhile True:\n    pass\n```", require_citations=False)
    initial = asyncio.run(orchestrator.answer(request, user))

    assert any(call.status in {"timeout", "failed"} for call in initial.tool_calls)
    recovered = asyncio.run(orchestrator.recover(initial.run_id, user))

    assert recovered.run_id == initial.run_id
    assert len(recovered.tool_calls) >= 2
    assert any(step.name == "failure_recovery" for step in trace_store.get_steps(initial.run_id))


def test_metrics_counts_a_run_that_was_approved_and_resumed() -> None:
    user = UserContext(user_id="p0-metrics", tenant_id="p0-metrics", role="admin")
    orchestrator = AgentOrchestrator()
    pending = asyncio.run(
        orchestrator.answer(AskRequest(question="Please delete this metrics fixture"), user)
    )
    approval_service.decide(
        pending.approval_id,
        ApprovalDecision(approved=True, reviewer="metrics-test"),
        tenant_id=user.tenant_id,
    )
    asyncio.run(orchestrator.resume(pending.run_id, user))

    result = asyncio.run(metrics(user))

    assert result.approval_rate > 0
