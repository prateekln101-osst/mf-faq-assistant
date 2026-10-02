"""Retrieve scheme chunks from the persisted Chroma collection."""

from __future__ import annotations

import re
import sys
from functools import lru_cache

import chromadb

from src.config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    GUIDE_SIMILARITY_THRESHOLD,
    SCHEME_SIMILARITY_THRESHOLD,
    SIMILARITY_THRESHOLD,
    TOP_K,
)
from src.embedder import embed_texts

# Longer phrases first so "small cap" is not confused with a bare "cap".
SCHEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("balanced_advantage", ("balanced advantage", "balanced-advantage", "hybrid")),
    ("small_cap", ("small cap", "small-cap", "smallcap")),
    ("large_cap", ("large cap", "large-cap", "largecap")),
    ("flexi_cap", ("flexi cap", "flexi-cap", "flexicap", "flexi", "equity fund")),
    ("elss", ("tax saver", "elss")),
)


def detect_scheme_category(question: str) -> str | None:
    """Return one scheme_category when the question names exactly one scheme."""
    text = question.lower()
    found: list[str] = []
    for category, phrases in SCHEME_KEYWORDS:
        for phrase in phrases:
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text):
                found.append(category)
                break
    if len(found) == 1:
        return found[0]
    return None


@lru_cache(maxsize=1)
def get_chroma_client():
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection():
    client = get_chroma_client()
    names = []
    for item in client.list_collections():
        names.append(item if isinstance(item, str) else getattr(item, "name", ""))
    if COLLECTION_NAME not in names:
        return None
    collection = client.get_collection(COLLECTION_NAME)
    if collection.count() == 0:
        return None
    return collection


def _similarity(distance: float) -> float:
    """Chroma cosine space returns distance = 1 - cosine similarity."""
    return 1.0 - float(distance)


def _query(question: str, category: str | None, k: int) -> list[dict]:
    collection = get_collection()
    if collection is None:
        return []
    embedding = embed_texts([question])[0]
    kwargs = {
        "query_embeddings": [embedding],
        "n_results": min(k, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if category:
        kwargs["where"] = {"scheme_category": category}
    result = collection.query(**kwargs)
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits = []
    for text, metadata, distance in zip(documents, metadatas, distances):
        hits.append(
            {
                "text": text or "",
                "metadata": metadata or {},
                "score": _similarity(distance),
            }
        )
    hits.sort(key=lambda hit: hit["score"], reverse=True)
    return hits


def retrieve(question: str, k: int | None = None) -> list[dict]:
    """Return chunks that clear the similarity cutoff, best score first.

    A named scheme is filtered in Chroma and kept when it clears
    SCHEME_SIMILARITY_THRESHOLD. If that filtered search is empty or weak,
    the search is repeated without the filter and SIMILARITY_THRESHOLD applies.
    A guide page, such as the capital-gains statement instructions, is kept
    at GUIDE_SIMILARITY_THRESHOLD when it is the best hit.
    """
    limit = TOP_K if k is None else k
    category = detect_scheme_category(question)
    if category:
        hits = _query(question, category, limit)
        kept = [hit for hit in hits if hit["score"] >= SCHEME_SIMILARITY_THRESHOLD]
        if kept:
            return kept
    hits = _query(question, None, limit)
    kept = [hit for hit in hits if hit["score"] >= SIMILARITY_THRESHOLD]
    if kept:
        return kept
    if not hits:
        return []
    best = hits[0]
    if best["metadata"].get("doc_type") == "guide" and best["score"] >= GUIDE_SIMILARITY_THRESHOLD:
        return [
            hit
            for hit in hits
            if hit["metadata"].get("doc_type") == "guide" and hit["score"] >= GUIDE_SIMILARITY_THRESHOLD
        ]
    return []


def format_hits(question: str, hits: list[dict]) -> str:
    category = detect_scheme_category(question)
    lines = [f"question: {question}"]
    if category:
        lines.append(f"scheme_filter: {category}")
    if not hits:
        lines.append("no chunk cleared the similarity threshold")
        return "\n".join(lines)
    for index, hit in enumerate(hits, start=1):
        metadata = hit["metadata"]
        lines.append("")
        lines.append(f"[{index}] score={hit['score']:.4f}")
        lines.append(f"source_url: {metadata.get('source_url', '')}")
        lines.append(hit["text"])
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Usage: python -m src.retriever "your question"', file=sys.stderr)
        return 1
    question = " ".join(sys.argv[1:]).strip()
    if get_collection() is None:
        print("Index not built. Run ingestion.")
        return 1
    print(format_hits(question, retrieve(question)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
