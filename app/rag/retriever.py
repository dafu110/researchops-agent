from app.core.config import settings
from app.rag.embeddings import cosine_similarity, embedding_service
from app.rag.models import RetrievalHit
from app.rag.reranker import reranker
from app.rag.store import knowledge_store
from app.rag.text import overlap_score, tokenize


class Retriever:
    def retrieve(
        self,
        question: str,
        corpus_ids: list[str] | None = None,
        tenant_id: str | None = None,
        allowed_sources: list[str] | None = None,
    ) -> list[RetrievalHit]:
        query_terms = tokenize(question)
        query_embedding = embedding_service.embed(question)
        allowed_ids = set(corpus_ids or [])
        hits: list[RetrievalHit] = []
        chunks = knowledge_store.get_semantic_candidates(
            query_embedding,
            corpus_ids,
            settings.retrieval_top_k * 8,
            tenant_id=tenant_id,
            allowed_sources=allowed_sources,
        )
        for chunk in chunks:
            if allowed_ids and chunk.document_id not in allowed_ids:
                continue
            keyword_score, matched_terms = overlap_score(query_terms, chunk.terms)
            semantic_score = max(cosine_similarity(query_embedding, chunk.embedding), 0.0)
            combined_score = (0.55 * semantic_score) + (0.45 * keyword_score)
            if combined_score <= 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=round(combined_score, 4),
                    keyword_score=round(keyword_score, 4),
                    semantic_score=round(semantic_score, 4),
                    matched_terms=matched_terms,
                )
            )
        hits = reranker.rerank(question, hits)
        return hits[: settings.retrieval_top_k]


retriever = Retriever()
