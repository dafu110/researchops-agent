from app.agents.orchestrator import AgentOrchestrator
from app.api.schemas import AskRequest, EvalRunResponse
from app.core.security import UserContext
from app.evals.golden import GOLDEN_CASES, score_case
from app.rag.store import knowledge_store


class EvalService:
    async def run_golden(self, user: UserContext | None = None) -> EvalRunResponse:
        orchestrator = AgentOrchestrator()
        results = []
        for case in GOLDEN_CASES:
            corpus_ids = self._seed_case(case, user)
            response = await orchestrator.answer(
                AskRequest(
                    question=str(case["question"]),
                    corpus_ids=corpus_ids,
                    require_citations=bool(case.get("requires_citation", True)),
                ),
                user,
            )
            results.append(score_case(case, response))

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

    def _seed_case(self, case: dict, user: UserContext | None) -> list[str]:
        context = case.get("context")
        if not context:
            return list(case.get("corpus_ids", []))
        document, _chunks = knowledge_store.ingest_text(
            title=f"Eval Fixture: {case['case_id']}",
            text=str(context),
            source=str(case.get("source", f"eval:{case['case_id']}")),
            tenant_id=user.tenant_id if user else "default",
        )
        return [document.document_id]


eval_service = EvalService()
