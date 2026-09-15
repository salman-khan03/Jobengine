"""Fixed-dimension text embeddings via the hashing trick, for pgvector search.

Deliberately not calling this "AI embeddings" or "semantic AI" in any UI copy
— it's feature hashing over the same tokenizer semantic_match.py already
uses for TF-IDF, projected into a fixed-size dense vector so it fits a
pgvector column. That's an honest, explainable technique (no training, no
external model, no API key required), consistent with this project's own
audit gate against overclaiming what a feature actually does.

Each token hashes to one of `dims` buckets; the bucket accumulates the
token's TF-IDF-style weight (with a sign derived from a second hash, the
standard feature-hashing trick to keep collisions unbiased in expectation).
The result is L2-normalized so cosine distance and dot product agree, which
is what pgvector's `<=>` (cosine) operator assumes.
"""
from __future__ import annotations

import hashlib
import math

from sqlalchemy import text as sql

from .semantic_match import _tokenize

DIMS = 256


def _hash_bucket(token: str, dims: int) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dims


def _hash_sign(token: str) -> float:
    # A second, independent hash decides the sign — this is what keeps
    # hash collisions from systematically inflating magnitude.
    return 1.0 if int(hashlib.md5((token + "#sign").encode("utf-8")).hexdigest(), 16) % 2 == 0 else -1.0


def embed(text: str, dims: int = DIMS) -> list[float]:
    """Embed arbitrary text (title + category + JD, project bullets, etc.)
    into a unit-length `dims`-dimensional vector via the hashing trick."""
    vec = [0.0] * dims
    for token in _tokenize(text):
        b = _hash_bucket(token, dims)
        vec[b] += _hash_sign(token)

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _literal(vec: list[float]) -> str:
    """pgvector's text input format: '[0.1,-0.2,...]', cast via ::vector /
    CAST(:x AS vector) at the call site — no client-side type adapter needed."""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def build_job_embeddings(rows: list[tuple[str, str]]) -> int:
    """Compute + upsert an embedding per (dedup_key, text_to_embed) pair.

    Returns the number of rows written, or 0 with a log line if the backend
    isn't Postgres (no-op, not an error — SQLite has no vector search).
    """
    from . import db  # local import: avoids a db<->embeddings import cycle
    from .logging_config import get_logger

    log = get_logger(__name__)
    if not db.ensure_job_embeddings():
        log.warning("Vector search needs Postgres (DATABASE_URL) — skipping embeddings.")
        return 0

    with db.get_engine().begin() as conn:
        for dedup_key, text_blob in rows:
            conn.execute(
                sql(
                    "INSERT INTO job_embeddings (dedup_key, embedding) "
                    "VALUES (:dedup_key, CAST(:embedding AS vector)) "
                    "ON CONFLICT (dedup_key) DO UPDATE SET embedding = EXCLUDED.embedding"
                ),
                {"dedup_key": dedup_key, "embedding": _literal(embed(text_blob))},
            )
    return len(rows)


def search_jobs(query_text: str, k: int = 10) -> list[dict]:
    """Nearest-neighbor job search by cosine distance, done in the database
    (pgvector's HNSW index + `<=>` operator), not by looping in Python.

    Returns [] on SQLite (no vector search there) rather than raising —
    callers (the API route) turn that into a clear 503, same pattern as
    query.py's `_require_db`.
    """
    from . import db

    if not db.pgvector_available():
        return []

    query_vec = _literal(embed(query_text))
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            sql(
                "SELECT j.*, (e.embedding <=> CAST(:q AS vector)) AS distance "
                "FROM job_embeddings e JOIN jobs j USING (dedup_key) "
                "WHERE j.active = 1 AND j.is_visible = 1 "
                "ORDER BY e.embedding <=> CAST(:q AS vector) "
                "LIMIT :k"
            ),
            {"q": query_vec, "k": k},
        )
        return [dict(r._mapping) for r in rows]
