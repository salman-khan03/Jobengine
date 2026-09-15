import math

import pytest

from jobengine import db, embeddings


def test_embed_returns_unit_length_vector():
    vec = embeddings.embed("Backend Engineer Software")
    assert len(vec) == embeddings.DIMS
    norm = math.sqrt(sum(v * v for v in vec))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_embed_is_deterministic():
    a = embeddings.embed("Machine Learning Engineer")
    b = embeddings.embed("Machine Learning Engineer")
    assert a == b


def test_embed_empty_text_is_zero_vector():
    assert embeddings.embed("") == [0.0] * embeddings.DIMS


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def test_similar_text_scores_higher_than_unrelated_text():
    query = embeddings.embed("Backend Engineer Python FastAPI Postgres")
    close = embeddings.embed("Software Engineer Backend Python Postgres APIs")
    far = embeddings.embed("Marketing Coordinator social media campaigns")
    assert _cosine(query, close) > _cosine(query, far)


def test_literal_format_is_valid_pgvector_syntax():
    vec = embeddings.embed("test")
    lit = embeddings._literal(vec)
    assert lit.startswith("[") and lit.endswith("]")
    assert len(lit[1:-1].split(",")) == embeddings.DIMS


@pytest.mark.skipif(
    not db.current_database_url().startswith("postgresql"),
    reason="vector search requires the Postgres backend",
)
def test_search_jobs_finds_seeded_row(tmp_path, monkeypatch):
    from sqlalchemy import text as sql

    db.ensure_job_embeddings()
    with db.ENGINE.begin() as conn:
        conn.execute(sql("DELETE FROM job_embeddings"))
        conn.execute(sql("DELETE FROM jobs WHERE dedup_key = 'test|embed|role'"))
        conn.execute(db.jobs.insert().values(
            dedup_key="test|embed|role", id="1", source_repo="newgrad",
            company="TestCo", company_norm="testco", title="Backend Engineer",
            title_norm="backend engineer", category="Software", active=1,
            is_visible=1, terms="[]", date_posted=0, date_updated=0, url="",
            url_canon="", locations="[]", company_url="",
            sponsorship_simplify="", degrees="[]", sponsor_tier="unknown",
            sponsor_lca_count=0, sponsor_match="",
        ))
    embeddings.build_job_embeddings([("test|embed|role", "Backend Engineer Python Postgres")])
    results = embeddings.search_jobs("Python backend developer", k=5)
    assert any(r["dedup_key"] == "test|embed|role" for r in results)

    with db.ENGINE.begin() as conn:
        conn.execute(sql("DELETE FROM job_embeddings WHERE dedup_key = 'test|embed|role'"))
        conn.execute(sql("DELETE FROM jobs WHERE dedup_key = 'test|embed|role'"))
