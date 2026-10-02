"""Paths and model settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SOURCES_CSV = ROOT / "data" / "sources.csv"
CLEANED_DIR = ROOT / "data" / "cleaned"
CHUNKS_PATH = ROOT / "data" / "chunks.txt"
CHROMA_DIR = ROOT / "chroma_db"

COLLECTION_NAME = "mf_faq"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Tuned on eval/retrieval_check.csv. Scores are cosine similarity (1 - Chroma distance).
# In-corpus questions usually score 0.63 to 0.90. "expense ratio of SBI Bluechip?"
# scores about 0.46, and "exit load of Axis Bluechip?" about 0.58, so the
# unfiltered cutoff rejects both.
TOP_K = 5
SIMILARITY_THRESHOLD = 0.60
# A named scheme is already filtered. Short questions such as "exit load of ELSS?"
# score about 0.40 on the right ELSS chunks and lower on every other scheme.
SCHEME_SIMILARITY_THRESHOLD = 0.35
# The capital-gains guide is not a scheme page. Its best chunks score about 0.54,
# so when the top hit is a guide the floor is lower than the unfiltered cutoff.
GUIDE_SIMILARITY_THRESHOLD = 0.50

# MiniLM input limit is 256 word-pieces, including [CLS] and [SEP].
EMBEDDED_TOKEN_CAP = 254
SPLIT_BODY_TARGET = 200
SPLIT_OVERLAP_TOKENS = 40
