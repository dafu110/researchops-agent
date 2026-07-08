import asyncio

from app.agents.orchestrator import AgentOrchestrator
from app.api.schemas import AskRequest
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


def test_high_risk_question_requires_approval() -> None:
    response = asyncio.run(
        AgentOrchestrator().answer(AskRequest(question="Please delete all production records"))
    )

    assert response.requires_approval is True
    assert response.approval_id
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
