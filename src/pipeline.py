"""Question path: guardrails, retrieval, Groq, then the response contract."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date

from src.config import CLEANED_DIR
from src.guardrails import (
    EDUCATION_URL,
    advice_refusal,
    factsheet_url,
    guard,
    performance_redirect,
)
from src.llm import generate
from src.retriever import get_collection, retrieve

logger = logging.getLogger(__name__)

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_ADVICE_BANNED = re.compile(r"\bi recommend\b|\byou should\b", re.IGNORECASE)
_PERFORMANCE_BANNED = re.compile(
    r"\bwill give returns\b|"
    r"\b\d+(?:\.\d+)?\s*%\s*(?:p\.a\.|per annum|cagr|return|gain)|"
    r"\b(?:cagr|returns?|gains?)\b[^.]{0,40}\d+(?:\.\d+)?\s*%",
    re.IGNORECASE,
)


def sentence_count(text: str) -> int:
    return len(split_sentences(text))


def split_sentences(text: str) -> list[str]:
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text.strip())
    parts = re.split(r"(?<=[.!?])\s+", protected)
    sentences = []
    for part in parts:
        cleaned = part.replace("<DOT>", ".").strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def strip_urls(text: str) -> str:
    stripped = _URL.sub("", text)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def trim_sentences(text: str, limit: int = 3) -> str:
    return " ".join(split_sentences(text)[:limit]).strip()


def fetched_date_for(url: str) -> str:
    for path in sorted(CLEANED_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("url") == url and document.get("fetched_date"):
            return document["fetched_date"]
    for path in sorted(CLEANED_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("fetched_date"):
            return document["fetched_date"]
    return date.today().isoformat()


def _result(text: str, source_url: str, last_updated: str, route: str) -> dict:
    return {
        "text": text,
        "source_url": source_url,
        "last_updated": last_updated,
        "route": route,
    }


def _with_citation(body: str, source_url: str, last_updated: str) -> str:
    lines = [body.strip()]
    if source_url and source_url not in body:
        lines.append(f"Source: {source_url}")
    if last_updated:
        lines.append(f"Last updated from sources: {last_updated}")
    return "\n".join(line for line in lines if line)


def enforce_contract(question: str, raw: str, chunks: list[dict], shorten) -> dict:
    """Apply the response contract to one model draft."""
    top = chunks[0]
    metadata = top.get("metadata") or {}
    source_url = metadata.get("source_url", "")
    last_updated = metadata.get("fetched_date") or fetched_date_for(source_url)
    body = strip_urls(raw)

    banned = _banned_route(body)
    if banned:
        return _refusal(question, banned, last_updated)

    if sentence_count(body) > 3:
        try:
            body = strip_urls(shorten(raw))
        except Exception:
            logger.warning("sentence rewrite failed: %s", "shorten")
        banned = _banned_route(body)
        if banned:
            return _refusal(question, banned, last_updated)
        if sentence_count(body) > 3:
            body = trim_sentences(body, 3)

    if not body:
        body = "This isn't available in the sources."
    return _result(_with_citation(body, source_url, last_updated), source_url, last_updated, "factual")


def _banned_route(body: str) -> str:
    if _ADVICE_BANNED.search(body):
        return "advice"
    if _PERFORMANCE_BANNED.search(body):
        return "performance"
    return ""


def _refusal(question: str, route: str, last_updated: str) -> dict:
    if route == "performance":
        source_url = factsheet_url(question)
        text = performance_redirect(question)
    else:
        source_url = EDUCATION_URL
        text = advice_refusal()
    return _result(_with_citation(text, source_url, last_updated), source_url, last_updated, route)


def _not_found(question: str) -> dict:
    source_url = factsheet_url(question)
    last_updated = fetched_date_for(source_url)
    body = "I couldn't find this in the sources."
    return _result(_with_citation(body, source_url, last_updated), source_url, last_updated, "not_found")


def _groq_fallback(chunks: list[dict]) -> dict:
    metadata = (chunks[0].get("metadata") or {}) if chunks else {}
    source_url = metadata.get("source_url") or factsheet_url("")
    last_updated = metadata.get("fetched_date") or fetched_date_for(source_url)
    body = "I couldn't complete the answer just now. You can check the source page directly."
    return _result(_with_citation(body, source_url, last_updated), source_url, last_updated, "error")


def answer(question: str) -> dict:
    """Return {text, source_url, last_updated, route}."""
    try:
        decision = guard(question)
        if decision["route"] == "pii":
            return _result(decision["text"], "", "", "pii")
        if decision["route"] == "advice":
            return _result(
                _with_citation(decision["text"], EDUCATION_URL, fetched_date_for(EDUCATION_URL)),
                EDUCATION_URL,
                fetched_date_for(EDUCATION_URL),
                "advice",
            )
        if decision["route"] == "performance":
            source_url = factsheet_url(question)
            last_updated = fetched_date_for(source_url)
            return _result(
                _with_citation(decision["text"], source_url, last_updated),
                source_url,
                last_updated,
                "performance",
            )
        if get_collection() is None:
            return _result("Index not built. Run ingestion.", "", "", "error")

        chunks = retrieve(question)
        if not chunks:
            return _not_found(question)

        def shorten(previous: str) -> str:
            return generate(question, chunks, previous_answer=previous)

        raw = generate(question, chunks)
        return enforce_contract(question, raw, chunks, shorten)
    except Exception:
        logger.debug("answer failed after retry; returning the source link only")
        try:
            chunks = retrieve(question)
        except Exception:
            chunks = []
        return _groq_fallback(chunks)


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Usage: python -m src.pipeline "question"', file=sys.stderr)
        return 1
    question = " ".join(sys.argv[1:]).strip()
    print(answer(question)["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
