"""Shared MiniLM embedder. The same object is used at ingest and query time."""

from __future__ import annotations

from functools import lru_cache

from src.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def count_tokens(text: str) -> int:
    """Word-piece count for MiniLM, excluding [CLS] and [SEP].

    The tokenizer's default max length is 256. Counting raises that limit so a
    long section is measured in full instead of being truncated before the split.
    """
    tokenizer = get_embedder().tokenizer
    previous_limit = tokenizer.model_max_length
    tokenizer.model_max_length = max(previous_limit, len(text) + 8)
    try:
        return len(tokenizer.encode(text, add_special_tokens=False, truncation=False))
    finally:
        tokenizer.model_max_length = previous_limit


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = get_embedder().encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.tolist()
