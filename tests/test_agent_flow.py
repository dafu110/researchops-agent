import asyncio

from app.agents.orchestrator import AgentOrchestrator
from app.api.schemas import ApprovalDecision, AskRequest, FinalAnswer
from app.approvals.service import approval_service
from app.core.network import URLFetchError, fetch_public_url
from app.core.security import UserContext
from app.core.traces import trace_store
from app.evals.service import eval_service
from app.rag.store import knowledge_store


def test_ingest_and_answer_returns_citations() -> None:
    document, chunks = knowledge_store.ingest_text(
        title="Agent Spec",
        text="ResearchOps Agent supports RAG answers with citations and trace inspection.",
        source="test",
    )
    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(question="What supports citations and trace?", corpus_ids=[document.document_id])
        )
    )

    assert chunks
    assert response.citations
    assert response.citations[0].source_id == document.document_id
    assert "ResearchOps Agent" in response.answer
    assert response.plan_details
    assert response.plan_details[0].stage == "intake"


def test_chinese_question_uses_chinese_no_evidence_message() -> None:
    document, _ = knowledge_store.ingest_text(
        title="Chinese Fixture",
        text="该资料说明系统可以根据索引内容生成带引用的回答。",
        source="test",
    )

    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(question="分析这个数据", corpus_ids=[document.document_id])
        )
    )

    assert "在已索引资料中没有找到足够的依据。" in response.answer
    assert "I could not find enough grounded evidence" not in response.answer
    assert "Response requirements" not in response.answer


def test_chinese_question_uses_chinese_grounded_fallback_without_internal_prompt() -> None:
    document, _ = knowledge_store.ingest_text(
        title="English Fixture",
        text="ResearchOps Agent supports RAG answers with citations and trace inspection.",
        source="test",
    )

    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(question="请分析：What supports citations and trace?", corpus_ids=[document.document_id])
        )
    )

    assert "基于资料的回答：" in response.answer
    assert "证据：" in response.answer
    assert "Grounded answer for" not in response.answer
    assert "Response requirements" not in response.answer


def test_high_risk_question_requires_approval() -> None:
    response = asyncio.run(
        AgentOrchestrator().answer(AskRequest(question="Please delete all production records"))
    )

    assert response.requires_approval is True
    assert response.approval_id
    assert any(step.needs_approval for step in response.plan_details)


def test_approved_run_resumes_with_its_original_scope() -> None:
    document, _ = knowledge_store.ingest_text(
        title="Resume Fixture",
        text="This fixture explains how the test record is deleted and then summarized after approval.",
        source="test",
    )
    orchestrator = AgentOrchestrator()
    pending = asyncio.run(
        orchestrator.answer(
            AskRequest(
                question="Please delete this test record and summarize the fixture",
                corpus_ids=[document.document_id],
            )
        )
    )
    assert pending.approval_id
    approval_service.decide(
        pending.approval_id,
        ApprovalDecision(approved=True),
    )

    resumed = asyncio.run(
        orchestrator.resume(
            pending.run_id,
            UserContext(user_id="local-dev", tenant_id="default", role="admin"),
        )
    )

    assert resumed.run_id == pending.run_id
    assert resumed.requires_approval is False
    assert any(citation.source_id == document.document_id for citation in resumed.citations)
    assert any(step.name == "approval_resumed" for step in trace_store.get_steps(pending.run_id))


def test_approved_run_preserves_the_original_response_mode(monkeypatch) -> None:
    document, _ = knowledge_store.ingest_text(
        title="Mode Fixture",
        text="This fixture supports a report-mode response after approval.",
        source="test",
    )
    orchestrator = AgentOrchestrator()
    pending = asyncio.run(
        orchestrator.answer(
            AskRequest(
                question="Please delete this fixture and prepare a report",
                corpus_ids=[document.document_id],
                mode="report",
            )
        )
    )
    approval_service.decide(pending.approval_id, ApprovalDecision(approved=True))

    modes = []

    async def capture_mode(*args, **kwargs):
        modes.append(kwargs["mode"])
        return FinalAnswer(content="report result", citations=[], grounded=False, model="test")

    monkeypatch.setattr(orchestrator.research, "answer", capture_mode)

    asyncio.run(
        orchestrator.resume(
            pending.run_id,
            UserContext(user_id="local-dev", tenant_id="default", role="admin"),
        )
    )

    assert trace_store.get_run(pending.run_id).mode == "report"
    assert modes == ["report"]


def test_cancellation_during_research_is_terminal(monkeypatch) -> None:
    orchestrator = AgentOrchestrator()
    run_id = "late-cancel-run"
    request = AskRequest(question="Summarize this fixture", require_citations=False)
    trace_store.create_run(run_id, request.question)
    plan = asyncio.run(orchestrator.planner.plan(request.question))

    async def cancel_then_answer(*args, **kwargs):
        trace_store.request_cancel(run_id, "default")
        return FinalAnswer(content="late result", citations=[], grounded=False, model="test")

    monkeypatch.setattr(orchestrator.research, "answer", cancel_then_answer)
    response = asyncio.run(orchestrator._execute(run_id, request, None, plan, plan))

    assert trace_store.get_run(run_id).status == "canceled"
    assert response.final_answer is not None
    assert response.final_answer.model == "workflow-controller"


def test_mcp_call_requires_approval() -> None:
    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(
                question='mcp call example echo {"text":"approval required"}',
                require_citations=False,
            )
        )
    )

    assert response.requires_approval is True
    assert response.approval_id
    assert any(step.tool_hint == "mcp" for step in response.plan_details)
    assert any(step.needs_approval for step in response.plan_details)


def test_private_url_fetch_is_rejected() -> None:
    try:
        fetch_public_url("http://127.0.0.1/internal")
    except URLFetchError as exc:
        assert "private or reserved" in str(exc)
    else:
        raise AssertionError("Expected private URL fetch to be rejected.")


def test_run_records_are_tenant_scoped() -> None:
    user = UserContext(user_id="analyst-a", tenant_id="tenant-a", role="admin")
    response = asyncio.run(
        AgentOrchestrator().answer(
            AskRequest(question="What evidence exists?", require_citations=False),
            user,
        )
    )

    run = trace_store.get_run(response.run_id)
    assert run is not None
    assert run.tenant_id == "tenant-a"
    assert trace_store.run_count("tenant-a") >= 1


def test_eval_cases_require_fixture_citations() -> None:
    user = UserContext(user_id="eval-test", tenant_id="eval-test", role="admin")
    result = asyncio.run(eval_service.run_golden(user))

    assert result.pass_rate >= 0.8
    assert result.citation_correctness >= 0.8
