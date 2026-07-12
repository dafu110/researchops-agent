import re
from typing import Literal

from app.agents.planner import PlanStep
from app.agents.sdk_runtime import openai_agents_runtime
from app.api.schemas import Citation, FinalAnswer, TokenUsage
from app.rag.models import RetrievalHit
from app.rag.retriever import retriever


def _uses_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


class ResearchAgent:
    async def answer(
        self,
        question: str,
        corpus_ids: list[str],
        plan: list[PlanStep],
        mode: Literal["quick", "evidence", "report"] = "evidence",
        tenant_id: str | None = None,
        allowed_sources: list[str] | None = None,
    ) -> FinalAnswer:
        del plan
        hits = retriever.retrieve(question, corpus_ids, tenant_id, allowed_sources)
        if not hits:
            content = (
                "在已索引资料中没有找到足够的依据。请先导入相关资料后再试。"
                if _uses_chinese(question)
                else "I could not find enough grounded evidence in the indexed corpus. Ingest documents first, then ask again."
            )
            return FinalAnswer(
                content=content,
                citations=[],
                grounded=False,
                model="deterministic-rag",
            )

        citations = [self._citation_from_hit(hit) for hit in hits]
        evidence = self._format_evidence(hits)
        sdk_result = await openai_agents_runtime.run_research_summary(question, evidence, mode)
        if sdk_result.used_sdk and sdk_result.output:
            return FinalAnswer(
                content=sdk_result.output,
                citations=citations,
                grounded=True,
                model="openai-agents-sdk",
                token_usage=TokenUsage(
                    input_tokens=self._estimate_tokens(question + evidence),
                    output_tokens=self._estimate_tokens(sdk_result.output),
                    estimated=True,
                ),
            )

        answer = self._build_grounded_answer(question, hits)
        if sdk_result.error:
            runtime_note = "运行提示：未启用在线模型，已使用本地资料回答。" if _uses_chinese(question) else f"Runtime note: {sdk_result.error}"
            answer += f"\n\n{runtime_note}"
        return FinalAnswer(
            content=answer,
            citations=citations,
            grounded=True,
            model="deterministic-rag",
        )

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
                f"score={hit.score}: {self._sanitize_untrusted_text(hit.chunk.text[:700])}"
            )
        return "\n".join(lines)

    def _build_grounded_answer(self, question: str, hits: list[RetrievalHit]) -> str:
        evidence_lines = []
        for index, hit in enumerate(hits, start=1):
            snippet = self._sanitize_untrusted_text(hit.chunk.text[:420])
            if len(hit.chunk.text) > 420:
                snippet += "..."
            evidence_lines.append(
                f"{index}. {snippet} "
                f"[source: {hit.chunk.title}, {hit.chunk.locator}, score={hit.score}]"
            )
        if _uses_chinese(question):
            return (
                f"基于资料的回答：{question}\n\n"
                "证据：\n"
                + "\n".join(evidence_lines)
                + "\n\n结论：以上回答仅依据已索引资料；资料覆盖不足时请补充来源。"
            )
        return (
            f"Grounded answer for: {question}\n\n"
            "Evidence:\n"
            + "\n".join(evidence_lines)
            + "\n\nConclusion: the answer above is limited to indexed evidence. "
            "Add more sources when coverage is incomplete."
        )

    @staticmethod
    def _sanitize_untrusted_text(text: str) -> str:
        """Keep source evidence readable without treating embedded instructions as commands."""
        cleaned = re.sub(
            r"(?is)\bignore\s+(?:previous|all)\b.*?(?:[.!?](?:\s|$)|$)",
            "[untrusted instruction removed] ",
            text,
        )
        return re.sub(
            r"(?i)\b(?:system prompt|tool call|reveal secret)\b",
            "[untrusted instruction removed]",
            cleaned,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)
