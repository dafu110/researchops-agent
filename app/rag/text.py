import re
from collections.abc import Iterable

TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if token.strip()]


def unique_terms(text: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in tokenize(text):
        if term not in seen:
            terms.append(term)
            seen.add(term)
    return terms


def overlap_score(query_terms: Iterable[str], chunk_terms: Iterable[str]) -> tuple[float, list[str]]:
    query_set = set(query_terms)
    chunk_set = set(chunk_terms)
    matches = sorted(query_set & chunk_set)
    if not query_set:
        return 0.0, []
    return len(matches) / len(query_set), matches
