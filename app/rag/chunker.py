from uuid import uuid4

from app.rag.models import Chunk, Document
from app.rag.text import normalize_space, unique_terms
from app.rag.embeddings import embedding_service


class TextChunker:
    def __init__(self, target_chars: int = 900, overlap_chars: int = 140) -> None:
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def chunk(self, document: Document) -> list[Chunk]:
        paragraphs = [normalize_space(part) for part in document.text.splitlines() if part.strip()]
        if not paragraphs:
            paragraphs = [normalize_space(document.text)]

        chunks: list[Chunk] = []
        current: list[str] = []
        current_len = 0

        for paragraph in paragraphs:
            if current and current_len + len(paragraph) > self.target_chars:
                chunks.append(self._build_chunk(document, len(chunks) + 1, " ".join(current)))
                tail = " ".join(current)[-self.overlap_chars :]
                current = [tail, paragraph] if tail else [paragraph]
                current_len = sum(len(part) for part in current)
            else:
                current.append(paragraph)
                current_len += len(paragraph)

        if current:
            chunks.append(self._build_chunk(document, len(chunks) + 1, " ".join(current)))

        return chunks

    def _build_chunk(self, document: Document, index: int, text: str) -> Chunk:
        return Chunk(
            chunk_id=str(uuid4()),
            document_id=document.document_id,
            title=document.title,
            source=document.source,
            locator=f"chunk {index}",
            text=normalize_space(text),
            terms=unique_terms(text),
            embedding=embedding_service.embed(text),
            metadata=document.metadata.copy(),
        )
