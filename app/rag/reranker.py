from app.rag.models import RetrievalHit


class Reranker:
    def rerank(self, question: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        del question
        for hit in hits:
            exact_bonus = 0.05 if hit.matched_terms else 0.0
            source_bonus = 0.02 if hit.chunk.source.startswith("http") else 0.0
            hit.rerank_score = round(
                (0.62 * hit.semantic_score) + (0.33 * hit.keyword_score) + exact_bonus + source_bonus,
                4,
            )
            hit.score = hit.rerank_score
        return sorted(hits, key=lambda item: item.rerank_score, reverse=True)


reranker = Reranker()
