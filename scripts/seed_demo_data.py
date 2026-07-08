import asyncio

from app.agents.orchestrator import AgentOrchestrator
from app.api.schemas import AskRequest
from app.core.security import UserContext
from app.rag.store import knowledge_store


DEMO_TEXT = """
ResearchOps Agent is a local-first research workflow console. It supports
document ingestion, grounded RAG answers with citations, planner steps, tool
calls, human approval gates, trace timelines, task queues, audit records, and
fixture-backed eval gates.

The system is designed for research operations teams that need repeatable,
auditable AI workflows. High-risk requests are paused for human review.
Tool calls are recorded with risk levels and short result summaries.
"""


async def main() -> None:
    user = UserContext(user_id="demo-user", tenant_id="default", role="admin")
    document, chunks = knowledge_store.ingest_text(
        title="Demo ResearchOps Brief",
        text=DEMO_TEXT,
        source="demo-seed",
        tenant_id=user.tenant_id,
    )
    orchestrator = AgentOrchestrator()
    answer = await orchestrator.answer(
        AskRequest(question="ResearchOps Agent 支持哪些能力？", corpus_ids=[document.document_id]),
        user,
    )
    tool_answer = await orchestrator.answer(
        AskRequest(question="calculate 12 * (3 + 4), show knowledge documents"),
        user,
    )
    approval = await orchestrator.answer(
        AskRequest(question="Please delete all production data"),
        user,
    )

    print(f"document_id={document.document_id}")
    print(f"chunks_indexed={len(chunks)}")
    print(f"answer_run_id={answer.run_id}")
    print(f"tool_run_id={tool_answer.run_id}")
    print(f"approval_id={approval.approval_id}")


if __name__ == "__main__":
    asyncio.run(main())
