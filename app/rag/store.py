import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.core.config import settings
from app.core.json_state import atomic_json_write, load_json_or_default
from app.rag.chunker import TextChunker
from app.rag.embeddings import embedding_service
from app.rag.models import Chunk, Document
from app.rag.text import normalize_space


class JsonKnowledgeStore:
    def __init__(self) -> None:
        self.data_dir = Path(settings.data_dir)
        self.state_path = self.data_dir / "knowledge.json"
        self._lock = Lock()
        self._chunker = TextChunker()
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._load()

    def ingest_text(
        self,
        title: str,
        text: str,
        source: str,
        tenant_id: str = "default",
    ) -> tuple[Document, list[Chunk]]:
        clean_text = normalize_space(text)
        document = Document(
            document_id=str(uuid4()),
            title=title,
            source=source,
            text=clean_text,
            metadata={"tenant_id": tenant_id},
        )
        chunks = self._chunker.chunk(document)
        with self._lock:
            self._documents[document.document_id] = document
            for chunk in chunks:
                self._chunks[chunk.chunk_id] = chunk
            self._save()
        return document, chunks

    def list_documents(self, tenant_id: str | None = None) -> list[tuple[Document, int]]:
        with self._lock:
            documents = list(self._documents.values())
        if tenant_id:
            documents = [document for document in documents if document.tenant_id == tenant_id]
        return [(document, self.count_chunks(document.document_id)) for document in documents]

    def delete_document(self, document_id: str, tenant_id: str | None = None) -> bool:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None or (tenant_id and document.tenant_id != tenant_id):
                return False
            self._documents.pop(document_id, None)
            self._chunks = {
                chunk_id: chunk
                for chunk_id, chunk in self._chunks.items()
                if chunk.document_id != document_id
            }
            self._save()
        return True

    def count_chunks(
        self,
        document_id: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        chunks = list(self._chunks.values())
        if document_id is not None:
            chunks = [chunk for chunk in chunks if chunk.document_id == document_id]
        if tenant_id is not None:
            chunks = [chunk for chunk in chunks if chunk.tenant_id == tenant_id]
        return len(chunks)

    def get_chunks(self, document_id: str | None = None, tenant_id: str | None = None) -> list[Chunk]:
        with self._lock:
            chunks = list(self._chunks.values())
        if document_id is None:
            filtered = chunks
        else:
            filtered = [chunk for chunk in chunks if chunk.document_id == document_id]
        if tenant_id:
            filtered = [chunk for chunk in filtered if chunk.tenant_id == tenant_id]
        return filtered

    def get_semantic_candidates(
        self,
        query_embedding: list[float],
        corpus_ids: list[str] | None,
        limit: int,
        tenant_id: str | None = None,
        allowed_sources: list[str] | None = None,
    ) -> list[Chunk]:
        del query_embedding, limit
        chunks = self.get_chunks(tenant_id=tenant_id)
        if corpus_ids:
            allowed_ids = set(corpus_ids)
            chunks = [chunk for chunk in chunks if chunk.document_id in allowed_ids]
        if allowed_sources:
            allowed = set(allowed_sources)
            chunks = [chunk for chunk in chunks if chunk.source in allowed]
        return chunks

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        payload = load_json_or_default(self.state_path, {})
        self._documents = {
            item["document_id"]: Document.model_validate(item)
            for item in payload.get("documents", [])
        }
        self._chunks = {
            item["chunk_id"]: self._load_chunk(item)
            for item in payload.get("chunks", [])
        }

    def _load_chunk(self, item: dict) -> Chunk:
        chunk = Chunk.model_validate(item)
        if not chunk.embedding:
            chunk.embedding = embedding_service.embed(chunk.text)
        return chunk

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "documents": [document.model_dump() for document in self._documents.values()],
            "chunks": [chunk.model_dump() for chunk in self._chunks.values()],
        }
        atomic_json_write(self.state_path, payload)


class PostgresKnowledgeStore:
    def __init__(self) -> None:
        import psycopg

        self.psycopg = psycopg
        self._chunker = TextChunker()
        self.database_url = _psycopg_url(settings.database_url)
        self._init_schema()

    def ingest_text(
        self,
        title: str,
        text: str,
        source: str,
        tenant_id: str = "default",
    ) -> tuple[Document, list[Chunk]]:
        clean_text = normalize_space(text)
        document = Document(
            document_id=str(uuid4()),
            title=title,
            source=source,
            text=clean_text,
            metadata={"tenant_id": tenant_id},
        )
        chunks = self._chunker.chunk(document)
        with self.psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO documents (document_id, title, source, text, status, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.document_id,
                        document.title,
                        document.source,
                        document.text,
                        document.status,
                        json.dumps(document.metadata),
                    ),
                )
                for chunk in chunks:
                    cursor.execute(
                        """
                        INSERT INTO chunks
                          (chunk_id, document_id, title, source, locator, text, terms, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.document_id,
                            chunk.title,
                            chunk.source,
                            chunk.locator,
                            chunk.text,
                            chunk.terms,
                            _vector_literal(chunk.embedding),
                            json.dumps(chunk.metadata),
                        ),
                    )
        return document, chunks

    def list_documents(self, tenant_id: str | None = None) -> list[tuple[Document, int]]:
        with self.psycopg.connect(self.database_url) as connection:
            where = "WHERE d.metadata->>'tenant_id' = %s" if tenant_id else ""
            params = (tenant_id,) if tenant_id else ()
            rows = connection.execute(
                f"""
                SELECT d.document_id, d.title, d.source, d.text, d.status, d.metadata, COUNT(c.chunk_id)
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.document_id
                {where}
                GROUP BY d.document_id
                ORDER BY d.created_at DESC
                """,
                params,
            ).fetchall()
        return [
            (
                Document(
                    document_id=str(row[0]),
                    title=row[1],
                    source=row[2],
                    text=row[3],
                    status=row[4],
                    metadata=row[5] or {},
                ),
                int(row[6]),
            )
            for row in rows
        ]

    def delete_document(self, document_id: str, tenant_id: str | None = None) -> bool:
        filters = ["document_id::text = %s"]
        params: list[str] = [document_id]
        if tenant_id:
            filters.append("metadata->>'tenant_id' = %s")
            params.append(tenant_id)
        with self.psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "DELETE FROM documents WHERE " + " AND ".join(filters) + " RETURNING document_id",
                tuple(params),
            ).fetchone()
        return row is not None

    def count_chunks(
        self,
        document_id: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        with self.psycopg.connect(self.database_url) as connection:
            filters = []
            params: list[str] = []
            if document_id is not None:
                filters.append("document_id::text = %s")
                params.append(document_id)
            if tenant_id is not None:
                filters.append("metadata->>'tenant_id' = %s")
                params.append(tenant_id)
            sql = "SELECT COUNT(*) FROM chunks"
            if filters:
                sql += " WHERE " + " AND ".join(filters)
            row = connection.execute(sql, tuple(params)).fetchone()
        return int(row[0]) if row else 0

    def get_chunks(self, document_id: str | None = None, tenant_id: str | None = None) -> list[Chunk]:
        sql = (
            "SELECT chunk_id, document_id, title, source, locator, text, terms, "
            "embedding::text, metadata FROM chunks"
        )
        filters = []
        params: list[str] = []
        if document_id is not None:
            filters.append("document_id::text = %s")
            params.append(document_id)
        if tenant_id is not None:
            filters.append("metadata->>'tenant_id' = %s")
            params.append(tenant_id)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [
            Chunk(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                title=row[2],
                source=row[3],
                locator=row[4],
                text=row[5],
                terms=list(row[6] or []),
                embedding=_parse_vector(row[7]),
                metadata=row[8] or {},
            )
            for row in rows
        ]

    def get_semantic_candidates(
        self,
        query_embedding: list[float],
        corpus_ids: list[str] | None,
        limit: int,
        tenant_id: str | None = None,
        allowed_sources: list[str] | None = None,
    ) -> list[Chunk]:
        sql = (
            "SELECT chunk_id, document_id, title, source, locator, text, terms, "
            "embedding::text, metadata "
            "FROM chunks "
        )
        filters = []
        params: list[object] = []
        if tenant_id:
            filters.append("metadata->>'tenant_id' = %s")
            params.append(tenant_id)
        if corpus_ids:
            filters.append("document_id::text = ANY(%s)")
            params.append(corpus_ids)
        if allowed_sources:
            filters.append("source = ANY(%s)")
            params.append(allowed_sources)
        if filters:
            sql += "WHERE " + " AND ".join(filters) + " "
        sql += "ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([_vector_literal(query_embedding), limit])
        with self.psycopg.connect(self.database_url) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            Chunk(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                title=row[2],
                source=row[3],
                locator=row[4],
                text=row[5],
                terms=list(row[6] or []),
                embedding=_parse_vector(row[7]),
                metadata=row[8] or {},
            )
            for row in rows
        ]

    def _init_schema(self) -> None:
        schema = Path("db/schema.sql").read_text(encoding="utf-8")
        with self.psycopg.connect(self.database_url) as connection:
            connection.execute(schema)


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _parse_vector(value: str | None) -> list[float]:
    if not value:
        return []
    return [float(item) for item in value.strip("[]").split(",") if item]


def _build_store():
    if settings.store_backend == "json":
        return JsonKnowledgeStore()
    if settings.store_backend in {"auto", "postgres"}:
        try:
            return PostgresKnowledgeStore()
        except Exception:
            if settings.store_backend == "postgres":
                raise
    return JsonKnowledgeStore()


knowledge_store = _build_store()
