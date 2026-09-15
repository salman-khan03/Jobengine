"""query.query()'s filters. company/skill were added when the Spring Boot
search service (which used to own this filtering) was removed -- see
docs/decisions.md -- so this is the only place that behavior is tested."""
import pytest
from sqlalchemy import insert

from jobengine import config, db, query


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def _job(dedup_key, company, title, terms=None, category="Software",
         source_repo="newgrad", sponsor_tier="unknown", locations=None,
         date_posted=1000):
    import json
    with db.ENGINE.begin() as conn:
        conn.execute(insert(db.jobs).values(
            dedup_key=dedup_key, id=dedup_key, source_repo=source_repo,
            company=company, company_norm=company.lower(), title=title,
            title_norm=title.lower(), category=category, active=1, is_visible=1,
            terms=json.dumps(terms or []), date_posted=date_posted, date_updated=date_posted,
            url="", locations=json.dumps(locations or []), sponsorship_simplify="",
            sponsor_tier=sponsor_tier, sponsor_lca_count=0, sponsor_match="index:seed",
        ))


def test_company_filter_matches_a_substring_case_insensitively():
    _job("a", "Acme Corp", "Backend Engineer")
    _job("b", "Widgets Inc", "Backend Engineer")
    rows = query.query(company="acme")
    assert [r["dedup_key"] for r in rows] == ["a"]


def test_skill_filter_matches_title_or_terms():
    _job("a", "Acme", "Backend Engineer", terms=["Python", "PostgreSQL"])
    _job("b", "Acme", "Frontend Engineer", terms=["React"])
    _job("c", "Acme", "Data Engineer", terms=["SQL"])
    assert {r["dedup_key"] for r in query.query(skill="python")} == {"a"}
    assert {r["dedup_key"] for r in query.query(skill="engineer")} == {"a", "b", "c"}


def test_company_and_skill_combine_with_and_semantics():
    _job("a", "Acme", "Backend Engineer", terms=["Python"])
    _job("b", "Acme", "Frontend Engineer", terms=["React"])
    _job("c", "Widgets", "Backend Engineer", terms=["Python"])
    rows = query.query(company="acme", skill="python")
    assert [r["dedup_key"] for r in rows] == ["a"]


def test_no_filters_returns_everything_swe():
    _job("a", "Acme", "Backend Engineer")
    assert len(query.query()) == 1
