from pydantic import BaseModel, Field


class Document(BaseModel):
    document_id: str
    title: str
    source: str
    text: str
    status: str = "indexed"
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        return self.metadata.get("tenant_id", "default")


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source: str
    locator: str
    text: str
    terms: list[str] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        return self.metadata.get("tenant_id", "default")


class RetrievalHit(BaseModel):
    chunk: Chunk
    score: float
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    rerank_score: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)
