import hashlib
import math

from app.core.config import settings
from app.rag.text import tokenize


class EmbeddingService:
    def embed(self, text: str) -> list[float]:
        if settings.embedding_provider == "openai" and settings.openai_api_key:
            try:
                return self._openai_embed(text)
            except Exception:
                return self._local_embed(text)
        return self._local_embed(text)

    def _openai_embed(self, text: str) -> list[float]:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(model=settings.embedding_model, input=text)
        return list(response.data[0].embedding)

    def _local_embed(self, text: str) -> list[float]:
        vector = [0.0 for _ in range(settings.embedding_dimensions)]
        for term in tokenize(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % settings.embedding_dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    limit = min(len(left), len(right))
    return sum(left[index] * right[index] for index in range(limit))


embedding_service = EmbeddingService()
