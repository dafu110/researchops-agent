from app.agents.planner import PlanStep
from app.agents.sdk_runtime import openai_agents_runtime
from app.api.schemas import Citation
from app.rag.models import RetrievalHit
from app.rag.retriever import retriever


class ResearchAgent:
    async def answer(
        self,
        question: str,
        corpus_ids: list[str],
        plan: list[PlanStep],
        tenant_id: str | None = None,
        allowed_sources: list[str] | None = None,
    ) -> tuple[str, list[Citation]]:
        del plan
        hits = retriever.retrieve(question, corpus_ids, tenant_id, allowed_sources)
        if not hits:
            return (
                "I could not find enough grounded evidence in the indexed corpus. "
                "Ingest documents first, then ask again.",
                [],
            )

        citations = [self._citation_from_hit(hit) for hit in hits]
        evidence = self._format_evidence(hits)
        sdk_result = await openai_agents_runtime.run_research_summary(question, evidence)
        if sdk_result.used_sdk and sdk_result.output:
            return sdk_result.output, citations

        answer = self._build_grounded_answer(question, hits)
        if sdk_result.error:
            answer += f"\n\nRuntime note: {sdk_result.error}"
        return answer, citations

    def _citation_from_hit(self, hit: RetrievalHit) -> Citation:
        chunk = hit.chunk
        excerpt = chunk.text[:260] + ("..." if len(chunk.text) > 260 else "")
        return Citation(
            source_id=chunk.document_id,
            title=chunk.title,
            locator=chunk.locator,
            excerpt=excerpt,
        )

    def _format_evidence(self, hits: list[RetrievalHit]) -> str:
        lines = []
        for index, hit in enumerate(hits, start=1):
            lines.append(
                f"[{index}] {hit.chunk.title} {hit.chunk.locator} "
                f"score={hit.score}: {hit.chunk.text[:700]}"
            )
        return "\n".join(lines)

    def _build_grounded_answer(self, question: str, hits: list[RetrievalHit]) -> str:
        evidence_lines = []
        for index, hit in enumerate(hits, start=1):
            snippet = hit.chunk.text[:420] + ("..." if len(hit.chunk.text) > 420 else "")
            evidence_lines.append(
                f"{index}. {snippet} "
                f"[source: {hit.chunk.title}, {hit.chunk.locator}, score={hit.score}]"
            )
        return (
            f"Grounded answer for: {question}\n\n"
            "Evidence:\n"
            + "\n".join(evidence_lines)
            + "\n\nConclusion: the answer above is limited to indexed evidence. "
            "Add more sources when coverage is incomplete."
        )
