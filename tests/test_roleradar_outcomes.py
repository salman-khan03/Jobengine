"""Outcome funnel, ranking metrics, persistence, and the /api/v2 surface."""
from __future__ import annotations

import pytest

from jobengine import config, db
from roleradar import outcomes, store
from roleradar.models import CandidateProfile, Decision, Gate, ScoreBreakdown


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Same pattern as test_tracker.py: a throwaway SQLite file per test on
    the default backend, truncation when pointed at a shared Postgres."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(store.rr_application_events.delete())
        conn.execute(store.rr_applications.delete())
        conn.execute(store.job_decisions.delete())
        conn.execute(store.recommendation_feedback.delete())
        conn.execute(store.rr_decisions.delete())
        conn.execute(store.rr_profiles.delete())
    yield


def _decision(job_key: str, score: float, verdict: str = "apply") -> Decision:
    return Decision(
        job_key=job_key, title="SWE Intern", company="Acme", verdict=verdict,
        score=score, confidence=0.7, gate=Gate(passed=True), coverages=(),
        breakdown=ScoreBreakdown(score, 0.5, 0.3, 1.0, 0.0, {}),
        generated_at="2026-09-11T00:00:00+00:00")


# --- funnel semantics -------------------------------------------------------

def test_furthest_stage_beats_latest_stage():
    """Almost every application ends in 'rejected'. An onsite-then-rejected
    application is a ranking success, and must not be recorded as a failure."""
    assert outcomes.furthest_stage(["applied", "oa", "onsite", "rejected"]) == "onsite"


def test_positive_threshold_starts_at_oa():
    assert outcomes.is_positive("oa") and outcomes.is_positive("offer")
    assert not outcomes.is_positive("applied")
    assert not outcomes.is_positive("rejected")


def test_relevance_is_graded_not_binary():
    assert (outcomes.relevance("offer") > outcomes.relevance("interview")
            > outcomes.relevance("oa") > outcomes.relevance("applied"))


# --- metrics ----------------------------------------------------------------

def test_ndcg_rewards_correct_ordering():
    perfect = outcomes.ndcg_at_k([5.0, 4.0, 3.0, 0.0, 0.0], 5)
    inverted = outcomes.ndcg_at_k([0.0, 0.0, 3.0, 4.0, 5.0], 5)
    assert perfect == 1.0
    assert inverted < perfect


def test_ndcg_with_no_positive_outcome_is_zero_not_one():
    """An all-zero list trivially matches its own ideal; reporting 1.0 would
    tell a user who has heard from nobody that the ranker is perfect."""
    assert outcomes.ndcg_at_k([0.0, 0.0, 0.0], 5) == 0.0


def test_precision_and_lift():
    labels = [True, True, False, False, False, False, False, False, False, False]
    assert outcomes.precision_at_k(labels, 5) == 0.4
    # base rate 0.2, precision@5 0.4 -> exactly 2x better than random order
    assert outcomes.lift_at_k(labels, 5) == 2.0


def test_lift_of_one_means_the_ranking_added_nothing():
    labels = [True, False] * 5
    assert outcomes.lift_at_k(labels, 10) == 1.0


def test_brier_penalises_confident_wrong_predictions():
    confident_wrong = outcomes.brier([0.9, 0.9], [False, False])
    hedged = outcomes.brier([0.5, 0.5], [False, False])
    assert confident_wrong > hedged


def test_spearman_handles_ties_without_overstating_correlation():
    # All predictions identical -> no rank information at all.
    assert outcomes.spearman([0.5, 0.5, 0.5, 0.5], [3.0, 2.0, 1.0, 0.0]) == 0.0
    assert outcomes.spearman([0.9, 0.7, 0.5, 0.1], [3.0, 2.0, 1.0, 0.0]) == 1.0


def test_calibration_omits_empty_buckets():
    bins = outcomes.calibration_bins([0.05, 0.95], [False, True], bins=5)
    assert [b["bin"] for b in bins] == ["0.0-0.2", "0.8-1.0"]
    assert bins[1]["observed_rate"] == 1.0


def test_evaluate_withholds_metrics_below_the_minimum_sample():
    report = outcomes.evaluate([(0.9, "offer"), (0.2, "rejected")])
    assert report.underpowered
    assert report.ndcg_at_5 == 0.0 and "at least" in report.note


def test_evaluate_sorts_by_predicted_score_itself():
    """A caller passing unsorted pairs must still get correct metrics."""
    pairs = [(0.1, "rejected"), (0.9, "offer"), (0.8, "interview")] + \
            [(0.2, "rejected")] * 9
    report = outcomes.evaluate(pairs)
    assert not report.underpowered
    assert report.precision_at_5 > 0
    assert report.n == 12


def test_evaluate_reports_no_positive_signal_honestly():
    report = outcomes.evaluate([(0.5, "rejected")] * 12)
    assert report.positives == 0
    assert "no positive signal" in report.note
    assert report.ndcg_at_10 == 0.0


# --- persistence ------------------------------------------------------------

def test_profile_roundtrip_preserves_the_unknown_tristate():
    store.save_profile(CandidateProfile(name="T", needs_sponsorship=None),
                       resume={"name": "T"})
    profile, resume = store.load_profile()
    assert profile.needs_sponsorship is None, "unknown must not become False"
    assert resume == {"name": "T"}


def test_saving_a_profile_twice_updates_rather_than_duplicates():
    store.save_profile(CandidateProfile(name="A"), resume={})
    store.save_profile(CandidateProfile(name="B"), resume={})
    profile, _ = store.load_profile()
    assert profile.name == "B"
    with db.ENGINE.connect() as conn:
        assert conn.execute(store.rr_profiles.select()).fetchall().__len__() == 1


def test_outcome_links_to_the_latest_prediction():
    store.save_decision(_decision("j1", 0.8))
    store.record_outcome("j1", "interview")
    pairs = store.scored_outcomes()
    assert pairs == [(0.8, "interview")]


def test_outcome_without_a_prediction_counts_in_the_funnel_only():
    store.record_outcome("unscored", "offer")
    assert store.funnel_counts() == {"offer": 1}
    assert store.scored_outcomes() == [], "no prediction, no ranking metric"


def test_multiple_events_for_one_job_count_once_at_the_furthest_stage():
    store.save_decision(_decision("j1", 0.8))
    for stage in ("applied", "oa", "interview", "rejected"):
        store.record_outcome("j1", stage)
    assert store.scored_outcomes() == [(0.8, "interview")]
    assert store.funnel_counts() == {"rejected": 1}


def test_bulk_save_writes_every_row():
    assert store.save_decisions([_decision(f"j{i}", i / 10) for i in range(5)]) == 5
    assert len(store.list_decisions(limit=10)) == 5


def test_decisions_are_listed_best_first():
    store.save_decisions([_decision("low", 0.2), _decision("high", 0.9)])
    assert [d["job_key"] for d in store.list_decisions()] == ["high", "low"]


def test_model_version_records_the_weights_in_force():
    version = store.model_version()
    assert "required_coverage=0.5" in version and version.startswith("v2|")


def test_end_to_end_evaluation_over_stored_data():
    for i in range(12):
        score = 0.95 - i * 0.05
        store.save_decision(_decision(f"j{i}", score))
        store.record_outcome(f"j{i}", "applied")
        store.record_outcome(f"j{i}", "interview" if i < 4 else "rejected")
    report = outcomes.evaluate(store.scored_outcomes())
    assert report.n == 12 and report.positives == 4
    assert report.lift_at_5 > 1.0, "a perfectly ordered ranker must beat random"
    assert report.spearman > 0.5


# --- HTTP surface -----------------------------------------------------------

RESUME = {
    "name": "T", "location": "Houston, TX",
    "education": {"school": "NAU", "degree": "B.S. Computer Science",
                  "graduation": "May 2027", "coursework": ["Algorithms"]},
    "skills": {"Languages": ["Python", "SQL"]},
    "projects": [{"name": "JobEngine", "stack": ["Python", "PostgreSQL"],
                  "dates": "2026",
                  "bullets": ["Built an ingest pipeline in Python on PostgreSQL"]}],
}
JD = "Minimum Qualifications\n- Python\n- SQL\nWe cannot provide visa sponsorship.\n"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JOBENGINE_SECRET_KEY", "test-secret-key-that-is-long-enough")
    from fastapi.testclient import TestClient
    from jobengine import api
    return TestClient(api.app)


@pytest.fixture()
def auth_headers(client):
    token = client.post("/api/auth/register",
                        json={"email": "rr@test.io", "password": "password12345"}
                        ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_model_endpoint_publishes_the_weights(client):
    body = client.get("/api/v2/model").json()
    assert abs(sum(body["weights"].values()) - 1.0) < 1e-9
    assert "never the verdict" in body["llm"]["used_for"]


def test_anonymous_decide_works_with_an_inline_resume(client):
    body = client.post("/api/v2/decide", json={
        "job": {"title": "SWE Intern", "company": "Acme"}, "jd_text": JD,
        "resume": RESUME, "profile": {"needs_sponsorship": True}}).json()
    assert body["verdict"] == "blocked"
    assert any(v["status"] == "blocked" for v in body["gate"]["verdicts"])
    assert body["evidence"], "cited evidence ships with the decision"


def test_the_same_role_is_not_blocked_for_a_citizen(client):
    body = client.post("/api/v2/decide", json={
        "job": {"title": "SWE Intern", "company": "Acme"}, "jd_text": JD,
        "resume": RESUME, "profile": {"needs_sponsorship": False}}).json()
    assert body["verdict"] != "blocked"


def test_anonymous_decide_without_a_resume_is_rejected(client):
    resp = client.post("/api/v2/decide", json={"job": {"title": "X"}})
    assert resp.status_code == 401


def test_decide_requires_a_job(client):
    resp = client.post("/api/v2/decide", json={"resume": RESUME})
    assert resp.status_code == 400


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v2/profile"), ("get", "/api/v2/evidence"),
    ("get", "/api/v2/decisions"), ("get", "/api/v2/evaluation"),
    ("get", "/api/v2/outcomes/funnel"),
])
def test_per_user_routes_require_auth(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_profile_evidence_and_outcome_flow(client, auth_headers):
    saved = client.post("/api/v2/profile",
                        json={"resume": RESUME, "needs_sponsorship": True},
                        headers=auth_headers).json()
    assert saved["evidence_units"] > 0
    assert "python" in saved["skills_detected"]

    evidence = client.get("/api/v2/evidence", headers=auth_headers).json()
    assert evidence["count"] == saved["evidence_units"]
    assert all(u["source"] for u in evidence["units"]), "every unit is traceable"

    decided = client.post("/api/v2/decide", json={
        "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": JD, "save": True}, headers=auth_headers).json()
    assert decided["verdict"] == "blocked"

    outcome = client.post("/api/v2/outcomes",
                          json={"job_key": decided["job_key"], "stage": "oa"},
                          headers=auth_headers)
    assert outcome.status_code == 201
    assert outcome.json()["linked_prediction"]["verdict"] == "blocked"

    funnel = client.get("/api/v2/outcomes/funnel", headers=auth_headers).json()
    assert funnel["funnel"] == {"oa": 1}

    report = client.get("/api/v2/evaluation", headers=auth_headers).json()
    assert report["underpowered"] is True


def test_invalid_outcome_stage_is_rejected(client, auth_headers):
    resp = client.post("/api/v2/outcomes",
                       json={"job_key": "k", "stage": "vibes"},
                       headers=auth_headers)
    assert resp.status_code == 400


def test_users_never_see_each_others_decisions(client):
    def register(email):
        tok = client.post("/api/auth/register",
                          json={"email": email, "password": "password12345"}
                          ).json()["token"]
        return {"Authorization": f"Bearer {tok}"}

    a, b = register("a@test.io"), register("b@test.io")
    client.post("/api/v2/profile", json={"resume": RESUME}, headers=a)
    client.post("/api/v2/decide", json={
        "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": JD, "save": True}, headers=a)
    assert client.get("/api/v2/decisions", headers=a).json()["count"] == 1
    assert client.get("/api/v2/decisions", headers=b).json()["count"] == 0


def test_prediction_is_frozen_when_the_first_outcome_is_recorded():
    original = store.save_decision(_decision("frozen", 0.3))
    store.record_outcome("frozen", "applied")
    store.save_decision(_decision("frozen", 0.95))
    store.record_outcome("frozen", "offer")
    with db.ENGINE.connect() as conn:
        apps = conn.execute(store.rr_applications.select()).mappings().all()
    assert {row["recommendation_id"] for row in apps} == {original}
    assert store.scored_outcomes() == [(0.3, "offer")]


def test_scoring_after_an_unscored_application_does_not_create_a_prediction():
    store.record_outcome("late", "applied")
    store.save_decision(_decision("late", 0.99))
    store.record_outcome("late", "offer")
    assert store.scored_outcomes() == []


def test_pending_applications_are_not_counted_as_failed_predictions():
    store.save_decision(_decision("pending", 0.9))
    store.record_outcome("pending", "applied")
    assert store.scored_outcomes() == []
    store.record_outcome("pending", "rejected")
    assert store.scored_outcomes() == [(0.9, "applied")]


def test_funnel_retains_rejections_separately_from_furthest_progress():
    store.record_outcome("a", "applied")
    store.record_outcome("a", "rejected")
    store.record_outcome("b", "interview")
    store.record_outcome("b", "rejected")
    assert store.funnel_counts() == {"rejected": 2}


def test_decision_snapshot_contains_the_cited_evidence(client, auth_headers):
    response = client.post("/api/v2/decide", headers=auth_headers, json={
        "resume": RESUME, "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": JD, "save": True})
    assert response.status_code == 200
    result = response.json()
    assert result["decision_id"] > 0
    import json
    saved = client.get("/api/v2/decisions", headers=auth_headers).json()["decisions"][0]
    assert json.loads(saved["payload"])["evidence"] == result["evidence"]


def test_explicit_unknown_profile_does_not_reuse_resume_sponsorship(client):
    response = client.post("/api/v2/decide", json={
        "resume": {**RESUME, "needs_sponsorship": True},
        "profile": {"needs_sponsorship": None},
        "job": {"title": "SWE Intern", "company": "Acme"}, "jd_text": JD})
    assert response.status_code == 200
    assert response.json()["verdict"] != "blocked"


def test_match_scores_are_not_published_as_probabilities():
    report = outcomes.evaluate([(0.9, "offer"), (0.4, "rejected")] * 6)
    assert report.brier is None
    assert report.as_dict()["score_kind"] == "match_score"


def test_evaluation_minimum_cannot_be_bypassed_via_http(client, auth_headers):
    response = client.get("/api/v2/evaluation?min_sample=1", headers=auth_headers)
    assert response.status_code == 200
    assert "at least 10" in response.json()["note"]


@pytest.mark.parametrize("resume", [
    {"education": 42}, {"education": ["invalid"]},
    {"projects": [{"dates": 42}]}, {"skills": {"Languages": 42}},
])
def test_invalid_resume_shape_is_a_validation_error(client, resume):
    response = client.post("/api/v2/decide", json={
        "resume": resume, "job": {"title": "SWE", "company": "Acme"}})
    assert response.status_code == 422


def test_false_string_is_not_treated_as_true_sponsorship(client):
    response = client.post("/api/v2/decide", json={
        "resume": RESUME, "profile": {"needs_sponsorship": "false"},
        "job": {"title": "SWE Intern", "company": "Acme"}, "jd_text": JD})
    assert response.status_code == 200
    assert response.json()["verdict"] != "blocked"


def test_two_inline_postings_do_not_share_outcome_identity(client):
    body = {"resume": RESUME, "job": {"title": "SWE", "company": "Acme"}}
    a = client.post("/api/v2/decide", json={**body, "jd_text": "Required: Python"}).json()
    b = client.post("/api/v2/decide", json={**body, "jd_text": "Required: Java"}).json()
    assert a["job_key"] != b["job_key"]
