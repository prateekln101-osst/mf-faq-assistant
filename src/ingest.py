"""Load cleaned documents, chunk them, and upsert MiniLM embeddings into ChromaDB."""

from __future__ import annotations

import argparse
import sys

import chromadb

from src.chunker import build_chunks, format_stats, write_chunks
from src.config import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_DIM
from src.embedder import embed_texts


def get_client() -> chromadb.PersistentClient:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def collection_names(client: chromadb.PersistentClient) -> set[str]:
    names: set[str] = set()
    for item in client.list_collections():
        name = item if isinstance(item, str) else getattr(item, "name", "")
        if name:
            names.add(name)
    return names


def open_collection(client: chromadb.PersistentClient, rebuild: bool):
    exists = COLLECTION_NAME in collection_names(client)
    if exists and not rebuild:
        collection = client.get_collection(COLLECTION_NAME)
        if collection.count() > 0:
            print(
                f"Collection {COLLECTION_NAME} already has {collection.count()} chunks. "
                "Re-run with --rebuild to replace it."
            )
            return None
        client.delete_collection(COLLECTION_NAME)
    elif exists and rebuild:
        client.delete_collection(COLLECTION_NAME)
    return client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def metadata_for(chunk: dict) -> dict:
    return {
        "source_url": chunk["source_url"],
        "source_title": chunk["source_title"],
        "publisher": chunk["publisher"],
        "publisher_type": chunk["publisher_type"],
        "scheme_name": chunk["scheme_name"],
        "scheme_category": chunk["scheme_category"],
        "section": chunk["section"],
        "heading": chunk["heading"],
        "doc_type": chunk["doc_type"],
        "fetched_date": chunk["fetched_date"],
        "chunk_index": int(chunk["chunk_index"]),
    }


def ingest(rebuild: bool = False) -> int:
    client = get_client()
    collection = open_collection(client, rebuild)
    if collection is None:
        return 0

    chunks = build_chunks()
    write_chunks(chunks)
    if not chunks:
        print("No chunks to ingest. Run the loader first.")
        return 1

    documents = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(documents)
    dimension = len(embeddings[0]) if embeddings else 0
    if dimension != EMBEDDING_DIM:
        print(f"Expected embedding dimension {EMBEDDING_DIM}, got {dimension}.", file=sys.stderr)
        return 1

    batch_size = 128
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        collection.upsert(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=[chunk["text"] for chunk in batch],
            embeddings=embeddings[start : start + len(batch)],
            metadatas=[metadata_for(chunk) for chunk in batch],
        )

    doc_ids = {chunk["source_url"] for chunk in chunks}
    print(
        f"docs={len(doc_ids)} chunks={collection.count()} embedding_dim={dimension}"
    )
    print(format_stats(chunks))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Embed chunks into the persisted Chroma collection.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and recreate the collection before upserting.",
    )
    args = parser.parse_args()
    return ingest(rebuild=args.rebuild)


if __name__ == "__main__":
    raise SystemExit(main())
