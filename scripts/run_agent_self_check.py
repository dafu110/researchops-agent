"""Run an isolated end-to-end self-check of the ResearchOps Agent control loop."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4


def configure_environment() -> None:
    os.environ.setdefault("STORE_BACKEND", "json")
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="researchops-self-check-"))
    os.environ.setdefault(
        "API_KEYS_JSON",
        '[{"key":"self-check-admin","user_id":"self-check","tenant_id":"self-check","role":"admin"}]',
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run() -> dict:
    configure_environment()

    from fastapi.testclient import TestClient

    from app.agents.orchestrator import AgentOrchestrator, _plan_details
    from app.api.schemas import ApprovalDecision, AskRequest
    from app.approvals.service import approval_service
    from app.core.security import UserContext
    from app.core.traces import trace_store
    from app.evals.service import eval_service
    from app.main import app
    from app.rag.store import knowledge_store

    user = UserContext(user_id="self-check", tenant_id="self-check", role="admin")
    orchestrator = AgentOrchestrator()
    checks: list[dict] = []

    def check(name: str, passed: bool, evidence: dict) -> None:
        checks.append({"name": name, "passed": passed, "evidence": evidence})
        if not passed:
            raise AssertionError(f"self-check failed: {name}: {evidence}")

    document, _ = knowledge_store.ingest_text(
        title="Self-check evidence",
        text=(
            "ResearchOps keeps selected source scope, citations, approvals, "
            "same-run recovery, tool records, metrics, and governed deletion traceable."
        ),
        source="self-check",
        tenant_id=user.tenant_id,
    )

    grounded = await orchestrator.answer(
        AskRequest(question="How are citations and same-run recovery kept traceable?", corpus_ids=[document.document_id]),
        user,
    )
    trace = trace_store.get_steps(grounded.run_id)
    check(
        "grounded_answer_and_trace",
        bool(grounded.citations and grounded.final_answer and trace and trace[0].input_payload),
        {"run_id": grounded.run_id, "citation_count": len(grounded.citations), "step_count": len(trace)},
    )

    tool_run = await orchestrator.answer(AskRequest(question="calculate 12 * (3 + 4)", require_citations=False), user)
    check(
        "tool_lifecycle_record",
        bool(tool_run.tool_calls and tool_run.tool_calls[0].status == "completed" and tool_run.tool_calls[0].idempotency_key),
        {"run_id": tool_run.run_id, "tool_calls": [item.model_dump() for item in tool_run.tool_calls]},
    )

    pending = await orchestrator.answer(
        AskRequest(question="Please delete this self-check fixture and summarize the evidence", corpus_ids=[document.document_id]),
        user,
    )
    approval_service.decide(pending.approval_id, ApprovalDecision(approved=True, reviewer="self-check"), tenant_id=user.tenant_id)
    resumed = await orchestrator.resume(pending.run_id, user)
    check(
        "approval_and_same_run_recovery",
        resumed.run_id == pending.run_id and not resumed.requires_approval and any(step.name == "approval_resumed" for step in trace_store.get_steps(pending.run_id)),
        {"run_id": resumed.run_id, "approval_id": pending.approval_id},
    )

    cancel_request = AskRequest(question="calculate 8 * 5", require_citations=False)
    cancel_run_id = str(uuid4())
    trace_store.create_run(cancel_run_id, cancel_request.question, tenant_id=user.tenant_id, user_id=user.user_id)
    cancel_plan = await orchestrator.planner.plan(cancel_request.question)
    trace_store.request_cancel(cancel_run_id, user.tenant_id)
    canceled = await orchestrator._execute(cancel_run_id, cancel_request, user, cancel_plan, _plan_details(cancel_plan))
    check(
        "cooperative_cancellation",
        trace_store.get_run(cancel_run_id).status == "canceled" and any(item.status == "canceled" for item in canceled.tool_calls),
        {"run_id": cancel_run_id, "tool_statuses": [item.status for item in canceled.tool_calls]},
    )

    timeout_request = AskRequest(question="```python\nwhile True:\n    pass\n```", require_citations=False)
    timeout_run = await orchestrator.answer(timeout_request, user)
    recovered = await orchestrator.recover(timeout_run.run_id, user)
    check(
        "timeout_and_failure_recovery",
        any(item.status == "timeout" for item in timeout_run.tool_calls)
        and recovered.run_id == timeout_run.run_id
        and any(step.name == "failure_recovery" for step in trace_store.get_steps(timeout_run.run_id)),
        {"run_id": timeout_run.run_id, "tool_calls_after_recovery": len(recovered.tool_calls)},
    )

    client = TestClient(app, headers={"X-API-Key": "self-check-admin"})
    contract_response = client.get("/api/contracts")
    metrics_response = client.get("/api/metrics")
    delete_run = client.post("/api/ask", json={"question": "Create a deletable self-check research record", "require_citations": False}).json()
    delete_response = client.delete(f"/api/runs/{delete_run['run_id']}")
    check(
        "contracts_metrics_and_governed_deletion",
        contract_response.status_code == 200
        and "tool_call" in contract_response.json()
        and metrics_response.status_code == 200
        and "p95_latency_ms" in metrics_response.json()
        and metrics_response.json()["approval_rate"] > 0
        and delete_response.status_code == 200
        and client.get(f"/api/runs/{delete_run['run_id']}/trace").status_code == 404
        and client.get(f"/api/audit/replay/{delete_run['run_id']}").status_code == 404,
        {"deleted_run_id": delete_run["run_id"], "metrics": metrics_response.json()},
    )

    evaluation = await eval_service.run_golden(user)
    check(
        "evaluation_gate",
        evaluation.pass_rate >= 0.9 and evaluation.citation_correctness >= 0.95 and all(item.passed for item in evaluation.results),
        {"total_cases": evaluation.total_cases, "pass_rate": evaluation.pass_rate, "citation_correctness": evaluation.citation_correctness},
    )

    return {"passed": True, "checks": checks}


if __name__ == "__main__":
    try:
        report = asyncio.run(run())
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
