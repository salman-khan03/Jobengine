"""The persistent recommendation -> decision -> application -> outcome ->
feedback loop: job_decisions, rr_applications, rr_application_events,
recommendation_feedback, rr_analytics_events.

Domain rule under test throughout: a recommendation (`rr_decisions`) is never
overwritten by what the user does with it. Every test that touches both
checks they remain independently inspectable.
"""
from __future__ import annotations

import pytest
from sqlalchemy import insert

from jobengine import config, db
from roleradar import store
from roleradar.models import Decision, Gate, ScoreBreakdown


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(store.rr_analytics_events.delete())
        conn.execute(store.recommendation_feedback.delete())
        conn.execute(store.rr_application_events.delete())
        conn.execute(store.rr_applications.delete())
        conn.execute(store.job_decisions.delete())
        conn.execute(store.rr_decisions.delete())
        conn.execute(store.rr_profiles.delete())
    yield


def _decision(job_key: str, score: float = 0.8, verdict: str = "apply") -> Decision:
    return Decision(
        job_key=job_key, title="SWE Intern", company="Acme", verdict=verdict,
        score=score, confidence=0.7, gate=Gate(passed=True), coverages=(),
        breakdown=ScoreBreakdown(score, 0.5, 0.3, 1.0, 0.0, {}),
        generated_at="2026-09-11T00:00:00+00:00")


def _user(email: str = "loop@test.io") -> int:
    """Real row in `users`: job_decisions/rr_applications carry a hard FK to
    it (unlike rr_decisions/rr_profiles, which stay nullable for the CLI), so
    store-level tests need an actual user_id, not an arbitrary int."""
    from datetime import datetime, timezone
    with db.ENGINE.begin() as conn:
        result = conn.execute(insert(db.users).values(
            email=email, password_hash="x",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        assert result.inserted_primary_key is not None
        return int(result.inserted_primary_key[0])


RESUME = {
    "name": "T", "location": "Houston, TX",
    "skills": {"Languages": ["Python", "SQL"]},
    "projects": [{"name": "JobEngine", "stack": ["Python"], "dates": "2026",
                  "bullets": ["Built an ingest pipeline in Python"]}],
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JOBENGINE_SECRET_KEY", "test-secret-key-that-is-long-enough")
    from fastapi.testclient import TestClient
    from jobengine import api
    return TestClient(api.app)


@pytest.fixture()
def auth(client):
    def register(email="rr-loop@test.io"):
        token = client.post("/api/auth/register",
                            json={"email": email, "password": "password12345"}
                            ).json()["token"]
        return {"Authorization": f"Bearer {token}"}
    return register


# --- store: job_decisions -----------------------------------------------------

def test_save_job_decision_rejects_unknown_decision():
    uid = _user()
    with pytest.raises(ValueError):
        store.save_job_decision("j1", "maybe", user_id=uid)


def test_save_job_decision_links_the_latest_recommendation():
    uid = _user()
    rid = store.save_decision(_decision("j1"), user_id=uid)
    row = store.save_job_decision("j1", "apply", user_id=uid, reason="strong match")
    assert row["recommendation_id"] == rid
    assert row["decision"] == "apply" and row["reason"] == "strong match"


def test_repeated_post_upserts_rather_than_duplicating():
    """Idempotency: a retried decision POST must not create a second row."""
    uid = _user()
    first = store.save_job_decision("j1", "save", user_id=uid)
    second = store.save_job_decision("j1", "apply", user_id=uid)
    assert first["job_decision_id"] == second["job_decision_id"]
    with db.ENGINE.connect() as conn:
        rows = conn.execute(store.job_decisions.select()).mappings().all()
    assert len(rows) == 1
    assert rows[0]["decision"] == "apply"


def test_editing_a_decision_does_not_repoint_an_existing_recommendation_link():
    uid = _user()
    r1 = store.save_decision(_decision("j1", 0.5), user_id=uid)
    store.save_job_decision("j1", "save", user_id=uid)
    store.save_decision(_decision("j1", 0.9), user_id=uid)  # a later re-score
    row = store.save_job_decision("j1", "apply", user_id=uid)
    assert row["recommendation_id"] == r1, \
        "the decision was already linked to r1; editing it must not silently re-link to a newer score"


def test_update_job_decision_returns_none_for_another_users_row():
    a, b = _user("a1@test.io"), _user("b1@test.io")
    row = store.save_job_decision("j1", "save", user_id=a)
    assert store.update_job_decision(row["job_decision_id"], user_id=b,
                                     decision="apply") is None


def test_update_job_decision_rejects_bad_value():
    uid = _user()
    row = store.save_job_decision("j1", "save", user_id=uid)
    with pytest.raises(ValueError):
        store.update_job_decision(row["job_decision_id"], user_id=uid, decision="vibes")


# --- store: applications and immutable events ---------------------------------

def test_application_requires_an_apply_decision():
    uid = _user()
    row = store.save_job_decision("j1", "skip", user_id=uid)
    with pytest.raises(store.InvalidTransition):
        store.create_application(row["job_decision_id"], user_id=uid)


def test_create_application_is_idempotent():
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    a = store.create_application(d["job_decision_id"], user_id=uid, source="referral")
    b = store.create_application(d["job_decision_id"], user_id=uid, source="linkedin")
    assert a["application_id"] == b["application_id"]
    assert b["source"] == "referral", "the retried call must not silently overwrite the original"
    with db.ENGINE.connect() as conn:
        assert len(conn.execute(store.rr_applications.select()).fetchall()) == 1


def test_new_application_starts_planned_with_one_immutable_event():
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    assert app["current_stage"] == "planned"
    assert app["applied_at"] is None
    history = store.application_history(app["application_id"], user_id=uid)
    assert len(history) == 1 and history[0]["stage"] == "planned"


def test_advance_application_appends_an_event_and_sets_applied_at():
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    store.advance_application(app["application_id"], user_id=uid, stage="applied")
    row = store.get_application(app["application_id"], user_id=uid)
    assert row["current_stage"] == "applied"
    assert row["applied_at"] is not None
    history = store.application_history(app["application_id"], user_id=uid)
    assert [h["stage"] for h in history] == ["planned", "applied"]


def test_terminal_stage_cannot_be_advanced_past():
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    store.advance_application(app["application_id"], user_id=uid, stage="rejected")
    with pytest.raises(store.InvalidTransition):
        store.advance_application(app["application_id"], user_id=uid, stage="oa")


def test_reposting_the_current_stage_does_not_duplicate_history():
    """Retried PATCH .../stage must be a no-op, not a second event."""
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    store.advance_application(app["application_id"], user_id=uid, stage="applied")
    store.advance_application(app["application_id"], user_id=uid, stage="applied")
    history = store.application_history(app["application_id"], user_id=uid)
    assert [h["stage"] for h in history] == ["planned", "applied"]


def test_advance_application_rejects_unknown_stage():
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    with pytest.raises(ValueError):
        store.advance_application(app["application_id"], user_id=uid, stage="vibes")


def test_planned_cannot_be_re_entered_after_real_progress():
    """`planned` is a create-time-only bootstrap stage; letting it back in
    via advance_application would erase apparent progress from
    current_stage while the append-only event history disagreed underneath."""
    uid = _user()
    d = store.save_job_decision("j1", "apply", user_id=uid)
    app = store.create_application(d["job_decision_id"], user_id=uid)
    store.advance_application(app["application_id"], user_id=uid, stage="applied")
    with pytest.raises(store.InvalidTransition):
        store.advance_application(app["application_id"], user_id=uid, stage="planned")


def test_advance_application_checks_ownership():
    a, b = _user("a2@test.io"), _user("b2@test.io")
    d = store.save_job_decision("j1", "apply", user_id=a)
    app = store.create_application(d["job_decision_id"], user_id=a)
    with pytest.raises(LookupError):
        store.advance_application(app["application_id"], user_id=b, stage="applied")


def test_application_history_is_append_only_no_update_helper_exists():
    """There is deliberately no store function that edits an existing event
    row -- history grows only by `advance_application` appending a new one."""
    assert not hasattr(store, "update_application_event")
    assert not hasattr(store, "delete_application_event")


# --- store: feedback -----------------------------------------------------------

def test_feedback_requires_an_owned_recommendation():
    a, b = _user("a3@test.io"), _user("b3@test.io")
    rid = store.save_decision(_decision("j1"), user_id=a)
    with pytest.raises(LookupError):
        store.save_feedback(rid, user_id=b, relevant=True, reason="good_match")


def test_feedback_rejects_unknown_reason():
    uid = _user()
    rid = store.save_decision(_decision("j1"), user_id=uid)
    with pytest.raises(ValueError):
        store.save_feedback(rid, user_id=uid, relevant=True, reason="vibes")


def test_feedback_upserts_one_row_per_user_and_recommendation():
    uid = _user()
    rid = store.save_decision(_decision("j1"), user_id=uid)
    a = store.save_feedback(rid, user_id=uid, relevant=True, reason="good_match")
    b = store.save_feedback(rid, user_id=uid, relevant=False, reason="wrong_skills")
    assert a["feedback_id"] == b["feedback_id"]
    with db.ENGINE.connect() as conn:
        rows = conn.execute(store.recommendation_feedback.select()).mappings().all()
    assert len(rows) == 1 and rows[0]["reason"] == "wrong_skills"


# --- store: analytics -----------------------------------------------------------

def test_emit_analytics_never_raises_on_a_bad_call(monkeypatch):
    """Analytics is best-effort: a broken write must never break the caller."""
    def boom(*a, **kw):
        raise RuntimeError("db is down")
    monkeypatch.setattr(store.db, "get_engine", boom)
    store.emit_analytics("application_created", user_id=1)  # must not raise


def test_analytics_counts_group_by_event_type():
    store.emit_analytics("application_created", user_id=1, job_key="j1")
    store.emit_analytics("application_created", user_id=1, job_key="j2")
    store.emit_analytics("feedback_submitted", user_id=1)
    assert store.analytics_counts(user_id=1) == {
        "application_created": 2, "feedback_submitted": 1,
    }


# --- HTTP surface ---------------------------------------------------------------

def test_decision_routes_require_auth(client):
    assert client.post("/api/v2/jobs/j1/decisions",
                       json={"decision": "apply"}).status_code == 401
    assert client.post("/api/v2/applications", json={"job_decision_id": 1}
                       ).status_code == 401
    assert client.post("/api/v2/recommendations/1/feedback",
                       json={"relevant": True, "reason": "good_match"}
                       ).status_code == 401


def test_full_loop_over_http(client, auth):
    headers = auth()
    client.post("/api/v2/profile", json={"resume": RESUME}, headers=headers)
    decided = client.post("/api/v2/decide", json={
        "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": "Required: Python", "save": True}, headers=headers).json()
    job_key = decided["job_key"]

    decision = client.post(f"/api/v2/jobs/{job_key}/decisions",
                           json={"decision": "apply", "reason": "great fit"},
                           headers=headers)
    assert decision.status_code == 201
    body = decision.json()
    assert body["saved"] is True and body["decision"] == "apply"
    assert body["recommendation_id"] == decided["decision_id"]

    application = client.post("/api/v2/applications",
                              json={"job_decision_id": body["job_decision_id"],
                                    "source": "referral"}, headers=headers)
    assert application.status_code == 201
    app_body = application.json()
    assert app_body["current_stage"] == "planned"

    stage = client.patch(f"/api/v2/applications/{app_body['application_id']}/stage",
                         json={"stage": "applied"}, headers=headers)
    assert stage.status_code == 200

    events = client.get(f"/api/v2/applications/{app_body['application_id']}/events",
                        headers=headers).json()
    assert [e["stage"] for e in events["events"]] == ["planned", "applied"]

    feedback = client.post(f"/api/v2/recommendations/{decided['decision_id']}/feedback",
                           json={"relevant": True, "reason": "good_match"},
                           headers=headers)
    assert feedback.status_code == 201
    assert feedback.json()["relevant"] is True

    # The recommendation itself is untouched by any of the above.
    saved = client.get("/api/v2/decisions", headers=headers).json()["decisions"][0]
    assert saved["verdict"] == decided["verdict"] and saved["score"] == decided["score"]


def test_application_requires_apply_decision_over_http(client, auth):
    headers = auth()
    decision = client.post("/api/v2/jobs/j1/decisions",
                           json={"decision": "skip"}, headers=headers).json()
    resp = client.post("/api/v2/applications",
                       json={"job_decision_id": decision["job_decision_id"]},
                       headers=headers)
    assert resp.status_code == 400


def test_retried_decision_post_is_idempotent_over_http(client, auth):
    headers = auth()
    a = client.post("/api/v2/jobs/j1/decisions", json={"decision": "save"},
                    headers=headers).json()
    b = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                    headers=headers).json()
    assert a["job_decision_id"] == b["job_decision_id"]
    assert b["decision"] == "apply"


def test_patch_decision_404s_for_another_users_decision(client, auth):
    a, b = auth("loop-a@test.io"), auth("loop-b@test.io")
    row = client.post("/api/v2/jobs/j1/decisions", json={"decision": "save"},
                      headers=a).json()
    resp = client.patch(f"/api/v2/decisions/{row['job_decision_id']}",
                        json={"decision": "apply"}, headers=b)
    assert resp.status_code == 404


def test_invalid_stage_transition_is_a_typed_error_over_http(client, auth):
    headers = auth()
    decision = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                           headers=headers).json()
    app = client.post("/api/v2/applications",
                      json={"job_decision_id": decision["job_decision_id"]},
                      headers=headers).json()
    client.patch(f"/api/v2/applications/{app['application_id']}/stage",
                json={"stage": "rejected"}, headers=headers)
    resp = client.patch(f"/api/v2/applications/{app['application_id']}/stage",
                        json={"stage": "oa"}, headers=headers)
    assert resp.status_code == 409


def test_unknown_stage_value_is_a_400_over_http(client, auth):
    headers = auth()
    decision = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                           headers=headers).json()
    app = client.post("/api/v2/applications",
                      json={"job_decision_id": decision["job_decision_id"]},
                      headers=headers).json()
    resp = client.patch(f"/api/v2/applications/{app['application_id']}/stage",
                        json={"stage": "vibes"}, headers=headers)
    assert resp.status_code == 400


def test_users_never_see_each_others_applications(client, auth):
    a, b = auth("loop-a2@test.io"), auth("loop-b2@test.io")
    decision = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                           headers=a).json()
    app = client.post("/api/v2/applications",
                      json={"job_decision_id": decision["job_decision_id"]},
                      headers=a).json()
    assert client.get(f"/api/v2/applications/{app['application_id']}",
                      headers=b).status_code == 404
    assert client.get("/api/v2/applications", headers=b).json()["count"] == 0


def test_feedback_rejects_bad_reason_over_http(client, auth):
    headers = auth()
    decided = client.post("/api/v2/decide", json={
        "resume": RESUME, "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": "Required: Python", "save": True}, headers=headers).json()
    resp = client.post(f"/api/v2/recommendations/{decided['decision_id']}/feedback",
                       json={"relevant": True, "reason": "vibes"}, headers=headers)
    assert resp.status_code == 422


def test_feedback_404s_for_a_nonexistent_recommendation(client, auth):
    headers = auth()
    resp = client.post("/api/v2/recommendations/999999/feedback",
                       json={"relevant": True, "reason": "good_match"},
                       headers=headers)
    assert resp.status_code == 404


def test_retried_stage_patch_does_not_double_count_analytics(client, auth):
    """A retried PATCH .../stage with the same stage is a no-op at the store
    layer; the analytics event for it must fire once, not once per retry."""
    headers = auth()
    decision = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                           headers=headers).json()
    app = client.post("/api/v2/applications",
                      json={"job_decision_id": decision["job_decision_id"]},
                      headers=headers).json()
    for _ in range(3):
        resp = client.patch(f"/api/v2/applications/{app['application_id']}/stage",
                            json={"stage": "applied"}, headers=headers)
        assert resp.status_code == 200
    assert store.analytics_counts().get("application_stage_changed") == 1


def test_retried_decision_post_does_not_double_count_analytics(client, auth):
    headers = auth()
    for _ in range(3):
        client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                   headers=headers)
    assert store.analytics_counts().get("recommendation_accepted") == 1


def test_retried_application_post_does_not_double_count_analytics(client, auth):
    headers = auth()
    decision = client.post("/api/v2/jobs/j1/decisions", json={"decision": "apply"},
                           headers=headers).json()
    for _ in range(3):
        client.post("/api/v2/applications",
                   json={"job_decision_id": decision["job_decision_id"]},
                   headers=headers)
    assert store.analytics_counts().get("application_created") == 1


def test_patch_decision_also_emits_recommendation_analytics(client, auth):
    """PATCH is the other path to APPLY (SAVE -> APPLY without a second
    POST); it must feed the same analytics counter POST does."""
    headers = auth()
    row = client.post("/api/v2/jobs/j1/decisions", json={"decision": "save"},
                      headers=headers).json()
    client.patch(f"/api/v2/decisions/{row['job_decision_id']}",
                json={"decision": "apply"}, headers=headers)
    assert store.analytics_counts().get("recommendation_accepted") == 1
    # Re-PATCHing the same value is a no-op and must not inflate the count.
    client.patch(f"/api/v2/decisions/{row['job_decision_id']}",
                json={"decision": "apply"}, headers=headers)
    assert store.analytics_counts().get("recommendation_accepted") == 1


def test_analytics_events_are_recorded_for_the_loop(client, auth):
    headers = auth()
    decided = client.post("/api/v2/decide", json={
        "resume": RESUME, "job": {"title": "SWE Intern", "company": "Acme"},
        "jd_text": "Required: Python", "save": True}, headers=headers).json()
    decision = client.post(f"/api/v2/jobs/{decided['job_key']}/decisions",
                           json={"decision": "apply"}, headers=headers).json()
    application = client.post("/api/v2/applications",
                              json={"job_decision_id": decision["job_decision_id"]},
                              headers=headers).json()
    client.patch(f"/api/v2/applications/{application['application_id']}/stage",
                json={"stage": "applied"}, headers=headers)
    client.post(f"/api/v2/recommendations/{decided['decision_id']}/feedback",
               json={"relevant": True, "reason": "good_match"}, headers=headers)

    counts = store.analytics_counts()
    assert counts.get("recommendation_accepted") == 1
    assert counts.get("application_created") == 1
    assert counts.get("application_stage_changed") == 1
    assert counts.get("feedback_submitted") == 1
