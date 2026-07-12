from uuid import uuid4

from app.agents.orchestrator import AgentOrchestrator
from app.api.schemas import ApprovalDecision, AskRequest, EvalRunResponse
from app.approvals.service import approval_service
from app.core.audit import audit_service
from app.core.security import UserContext
from app.core.traces import trace_store
from app.evals.golden import GOLDEN_CASES, score_case
from app.rag.store import knowledge_store


class EvalService:
    async def run_golden(self, user: UserContext | None = None) -> EvalRunResponse:
        orchestrator = AgentOrchestrator()
        results = []
        evaluation_user = UserContext(
            user_id=f"eval-{uuid4().hex[:8]}",
            tenant_id=f"evaluation-{uuid4()}",
            role="admin",
        )
        document_ids: list[str] = []
        run_ids: set[str] = set()
        try:
            for case in GOLDEN_CASES:
                corpus_ids, seeded_document_ids = self._seed_case(case, evaluation_user)
                document_ids.extend(seeded_document_ids)
                initial_response = await orchestrator.answer(
                    AskRequest(
                        question=str(case["question"]),
                        corpus_ids=corpus_ids,
                        require_citations=bool(case.get("requires_citation", True)),
                    ),
                    evaluation_user,
                )
                run_ids.add(initial_response.run_id)
                response = initial_response
                lifecycle_correct = True
                flow = case.get("approval_flow")
                if flow == "rejected" and initial_response.approval_id:
                    decision = approval_service.decide(
                        initial_response.approval_id,
                        ApprovalDecision(approved=False, reviewer="eval-reviewer"),
                        tenant_id=evaluation_user.tenant_id,
                    )
                    if decision and decision.status == "rejected":
                        trace_store.set_status(initial_response.run_id, "rejected")
                        trace_store.add_step(
                            initial_response.run_id,
                            "approval_rejected",
                            status="completed",
                            input_payload={"approval_id": initial_response.approval_id, "reviewer": "eval-reviewer"},
                            output_payload={"status": "rejected"},
                            model="workflow-controller",
                        )
                    lifecycle_correct = bool(decision and decision.status == "rejected")
                elif flow == "resumed" and initial_response.approval_id:
                    approval_service.decide(
                        initial_response.approval_id,
                        ApprovalDecision(approved=True, reviewer="eval-reviewer"),
                        tenant_id=evaluation_user.tenant_id,
                    )
                    response = await orchestrator.resume(initial_response.run_id, evaluation_user)
                    lifecycle_correct = response.run_id == initial_response.run_id and not response.requires_approval
                results.append(score_case(case, response, initial_response, lifecycle_correct))
        finally:
            for run_id in run_ids:
                approval_service.delete_for_run(run_id, evaluation_user.tenant_id)
                audit_service.delete_for_run(run_id, evaluation_user.tenant_id)
                trace_store.delete_run(run_id, evaluation_user.tenant_id)
            for document_id in document_ids:
                knowledge_store.delete_document(document_id, evaluation_user.tenant_id)

        total = len(results)
        passed = sum(1 for result in results if result.passed)
        citation_correct = sum(1 for result in results if result.citation_correct)
        return EvalRunResponse(
            total_cases=total,
            passed_cases=passed,
            pass_rate=passed / total if total else 0.0,
            citation_correctness=citation_correct / total if total else 0.0,
            results=results,
        )

    def _seed_case(self, case: dict, user: UserContext) -> tuple[list[str], list[str]]:
        context = case.get("context")
        if not context:
            return list(case.get("corpus_ids", [])), []
        document, _chunks = knowledge_store.ingest_text(
            title=f"Eval Fixture: {case['case_id']}",
            text=str(context),
            source=str(case.get("source", f"eval:{case['case_id']}")),
            tenant_id=user.tenant_id,
        )
        return [document.document_id], [document.document_id]


eval_service = EvalService()
