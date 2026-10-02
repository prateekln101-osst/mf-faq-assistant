"""Streamlit UI for the mutual fund FAQ assistant."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.embedder import get_embedder
from src.guardrails import detect_pii
from src.pipeline import answer
from src.retriever import get_chroma_client, get_collection, retrieve

WELCOME = "Ask a factual question about these HDFC Mutual Fund schemes."
DISCLAIMER = "Facts-only. No investment advice."
EXAMPLES = (
    "What is the expense ratio of HDFC Large Cap Fund?",
    "What is the lock-in period of the ELSS fund?",
    "How do I download my capital-gains statement?",
)


@st.cache_resource
def cached_embedder():
    return get_embedder()


@st.cache_resource
def cached_collection():
    get_chroma_client()
    return get_collection()


def _answer_body(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source:") or stripped.startswith("Last updated from sources:"):
            continue
        if stripped.startswith("Learn more:"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _chunks_for(question: str, route: str) -> list[dict]:
    if route == "pii" or detect_pii(question):
        return []
    if route not in {"factual", "not_found", "error"}:
        return []
    return retrieve(question)


def _ask(question: str, show_chunks: bool) -> None:
    result = answer(question)
    chunks = _chunks_for(question, result["route"]) if show_chunks else []
    if result["route"] == "pii":
        user_text = "Personal details were removed and not stored."
    else:
        user_text = question
    st.session_state.messages.append({"role": "user", "content": user_text})
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["text"],
            "source_url": result["source_url"],
            "last_updated": result["last_updated"],
            "route": result["route"],
            "question": "" if result["route"] == "pii" else question,
            "chunks": chunks,
        }
    )


def main() -> None:
    st.set_page_config(page_title="Mutual Fund FAQ", layout="centered")
    cached_embedder()
    collection = cached_collection()

    show_chunks = st.sidebar.toggle("Show retrieved chunks")

    st.title("Mutual Fund FAQ")
    st.write(WELCOME)
    st.info(DISCLAIMER)

    if collection is None:
        st.error("Index not built. Run ingestion.")
        st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    columns = st.columns(len(EXAMPLES))
    for column, question in zip(columns, EXAMPLES):
        if column.button(question, use_container_width=True):
            _ask(question, show_chunks)
            st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.write(message["content"])
                continue
            body = _answer_body(message["content"])
            if body:
                st.write(body)
            source_url = message.get("source_url") or ""
            if source_url:
                st.markdown(f"[Source]({source_url})")
            if message.get("last_updated"):
                st.write(f"Last updated from sources: {message['last_updated']}")
            chunks = message.get("chunks") or []
            if show_chunks and not chunks and message.get("question"):
                chunks = _chunks_for(message["question"], message.get("route", ""))
            if show_chunks and chunks:
                with st.expander("Retrieved chunks"):
                    for index, chunk in enumerate(chunks, start=1):
                        metadata = chunk.get("metadata") or {}
                        st.write(
                            f"{index}. score={chunk.get('score', 0):.3f} "
                            f"{metadata.get('scheme_name', '')} / {metadata.get('heading', '')}"
                        )
                        st.text(chunk.get("text", ""))

    typed = st.chat_input("Ask a factual question")
    if typed:
        _ask(typed, show_chunks)
        st.rerun()


if __name__ == "__main__":
    main()
