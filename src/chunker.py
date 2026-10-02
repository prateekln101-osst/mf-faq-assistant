"""Section-first chunker. See docs/chunking_strategy.md."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from pathlib import Path

from src.config import (
    CLEANED_DIR,
    CHUNKS_PATH,
    EMBEDDED_TOKEN_CAP,
    SPLIT_BODY_TARGET,
    SPLIT_OVERLAP_TOKENS,
)
from src.embedder import count_tokens

SEPARATOR = "-" * 80


def slugify(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    return (slug or "section")[:80]


def chunk_id_for(source_url: str, section: str, chunk_index: int) -> str:
    raw = f"{source_url}\n{section}\n{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _embedded(scheme_name: str, heading: str, body: str) -> str:
    prefix = f"{scheme_name} | {heading}:"
    body = body.strip()
    if not body:
        return prefix
    return f"{prefix}\n{body}"


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _holding_records(text: str) -> list[str]:
    records: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Name:") and current:
            records.append("\n".join(current))
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        records.append("\n".join(current))
    return records


def _units_for(heading: str, text: str) -> list[str]:
    if heading.lower().startswith("holdings"):
        records = _holding_records(text)
        if records:
            return records
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines
    return _split_sentences(text) or [text.strip()]


def _subsplit(unit: str) -> list[str]:
    sentences = _split_sentences(unit)
    if len(sentences) > 1:
        return sentences
    words = unit.split()
    if len(words) < 2:
        return [unit]
    midpoint = max(1, len(words) // 2)
    return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]


def _fit_units(scheme_name: str, heading: str, units: list[str]) -> list[str]:
    """Pack whole units to the body target without crossing the hard cap."""
    pieces: list[str] = []
    index = 0
    while index < len(units):
        chosen: list[str] = []
        cursor = index
        while cursor < len(units):
            candidate = chosen + [units[cursor]]
            body = "\n".join(candidate)
            embedded = _embedded(scheme_name, heading, body)
            within_target = count_tokens(body) <= SPLIT_BODY_TARGET or not chosen
            within_cap = count_tokens(embedded) <= EMBEDDED_TOKEN_CAP
            if within_cap and (within_target or not chosen):
                chosen = candidate
                cursor += 1
                if count_tokens(body) > SPLIT_BODY_TARGET:
                    break
                continue
            break
        if not chosen:
            parts = _subsplit(units[index])
            if parts == [units[index]]:
                pieces.append(units[index])
            else:
                pieces.extend(_fit_units(scheme_name, heading, parts))
            index += 1
            continue
        pieces.append("\n".join(chosen))
        if cursor >= len(units):
            break
        overlap: list[str] = []
        for unit in reversed(chosen):
            trial = [unit, *overlap]
            if count_tokens("\n".join(trial)) <= SPLIT_OVERLAP_TOKENS:
                overlap = trial
            else:
                break
        step = len(chosen) - len(overlap)
        if step < 1:
            step = 1
        index += step
    return pieces


def _bodies_for(scheme_name: str, heading: str, text: str) -> list[str]:
    text = text.strip()
    embedded = _embedded(scheme_name, heading, text)
    if count_tokens(embedded) <= EMBEDDED_TOKEN_CAP:
        return [text]
    return _fit_units(scheme_name, heading, _units_for(heading, text))


def chunk_document(document: dict) -> list[dict]:
    sections = document.get("sections") or []
    source_title = ""
    for section in sections:
        heading = (section.get("heading") or "").strip()
        if heading:
            source_title = heading
            break
    chunks: list[dict] = []
    for section_index, section in enumerate(sections):
        heading = (section.get("heading") or "Document").strip()
        text = (section.get("text") or "").strip()
        if not text and not heading:
            continue
        section_slug = slugify(heading)
        for body in _bodies_for(document["scheme_name"], heading, text):
            chunk_index = len(chunks)
            document_text = _embedded(document["scheme_name"], heading, body)
            chunks.append(
                {
                    "chunk_id": chunk_id_for(document["url"], section_slug, chunk_index),
                    "text": document_text,
                    "source_url": document["url"],
                    "source_title": source_title,
                    "publisher": document.get("publisher", ""),
                    "publisher_type": document.get("publisher_type", ""),
                    "scheme_name": document.get("scheme_name", ""),
                    "scheme_category": document.get("scheme_category", ""),
                    "section": section_slug,
                    "heading": heading,
                    "doc_type": document.get("doc_type", ""),
                    "fetched_date": document.get("fetched_date", ""),
                    "chunk_index": chunk_index,
                    "section_index": section_index,
                }
            )
    return chunks


def load_cleaned_documents(cleaned_dir: Path | None = None) -> list[dict]:
    directory = cleaned_dir or CLEANED_DIR
    documents = []
    for path in sorted(directory.glob("*.json")):
        documents.append(json.loads(path.read_text(encoding="utf-8")))
    return documents


def build_chunks(documents: list[dict] | None = None) -> list[dict]:
    chunks: list[dict] = []
    for document in documents if documents is not None else load_cleaned_documents():
        if document.get("status") not in (None, "", "ok"):
            continue
        chunks.extend(chunk_document(document))
    return chunks


def write_chunks(chunks: list[dict], path: Path | None = None) -> Path:
    destination = path or CHUNKS_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for chunk in chunks:
        meta = [
            f"chunk_id: {chunk['chunk_id']}",
            f"source_url: {chunk['source_url']}",
            f"source_title: {chunk['source_title']}",
            f"publisher: {chunk['publisher']}",
            f"publisher_type: {chunk['publisher_type']}",
            f"scheme_name: {chunk['scheme_name']}",
            f"scheme_category: {chunk['scheme_category']}",
            f"section: {chunk['section']}",
            f"heading: {chunk['heading']}",
            f"doc_type: {chunk['doc_type']}",
            f"fetched_date: {chunk['fetched_date']}",
            f"chunk_index: {chunk['chunk_index']}",
        ]
        blocks.append("\n".join([SEPARATOR, *meta, "", chunk["text"], ""]))
    destination.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    return destination


def token_stats(chunks: list[dict]) -> dict:
    lengths = [count_tokens(chunk["text"]) for chunk in chunks]
    if not lengths:
        return {"count": 0, "min": 0, "median": 0, "max": 0, "over_cap": 0, "over_256": 0}
    return {
        "count": len(lengths),
        "min": min(lengths),
        "median": statistics.median(lengths),
        "max": max(lengths),
        "over_cap": sum(1 for length in lengths if length > EMBEDDED_TOKEN_CAP),
        "over_256": sum(1 for length in lengths if length > 256),
    }


def format_stats(chunks: list[dict]) -> str:
    stats = token_stats(chunks)
    return (
        f"chunks={stats['count']} min={stats['min']} median={stats['median']} "
        f"max={stats['max']} over_254={stats['over_cap']} over_256={stats['over_256']}"
    )


def main() -> int:
    chunks = build_chunks()
    path = write_chunks(chunks)
    print(format_stats(chunks))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
