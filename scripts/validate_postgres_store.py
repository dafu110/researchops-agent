from uuid import uuid4

from app.rag.embeddings import embedding_service
from app.rag.store import PostgresKnowledgeStore


def main() -> None:
    store = PostgresKnowledgeStore()
    suffix = uuid4().hex[:8]
    document, chunks = store.ingest_text(
        title=f"Postgres Validation {suffix}",
        text=(
            "PostgreSQL pgvector validation document for ResearchOps Agent. "
            "This fixture verifies document persistence, chunk indexing, "
            "tenant filtering, and vector candidate retrieval."
        ),
        source=f"postgres-validation:{suffix}",
        tenant_id="postgres-validation",
    )
    query_embedding = embedding_service.embed("pgvector tenant filtering validation")
    candidates = store.get_semantic_candidates(
        query_embedding=query_embedding,
        corpus_ids=[document.document_id],
        limit=5,
        tenant_id="postgres-validation",
    )
    documents = store.list_documents("postgres-validation")
    chunk_count = store.count_chunks(document_id=document.document_id, tenant_id="postgres-validation")

    print(f"document_id={document.document_id}")
    print(f"chunks_indexed={len(chunks)}")
    print(f"tenant_documents={len(documents)}")
    print(f"document_chunk_count={chunk_count}")
    print(f"semantic_candidates={len(candidates)}")
    if not chunks or not candidates or chunk_count < 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
