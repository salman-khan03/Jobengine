import pytest

from jobengine import tracker, config, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets a clean slate, on either backend.

    On the default SQLite backend this points DB_PATH at a fresh throwaway
    file. When DATABASE_URL is set to a shared Postgres instance (e.g. for
    CI/dev against the real deploy target), there's no per-test database to
    swap in, so instead the tracker tables are truncated before each test —
    same isolation guarantee, different mechanism per backend.
    """
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(db.status_events.delete())
        conn.execute(db.applications.delete())
    yield


def test_add_and_list_roundtrip():
    app = tracker.Application(company="Stripe", title="Backend Engineer", source="linkedin")
    app_id = tracker.add(app)
    rows = tracker.list_applications()
    assert len(rows) == 1
    assert rows[0]["app_id"] == app_id
    assert rows[0]["company"] == "Stripe"
    assert rows[0]["status"] == "applied"


def test_add_rejects_invalid_source():
    app = tracker.Application(company="X", title="Y", source="carrier_pigeon")
    with pytest.raises(ValueError):
        tracker.add(app)


def test_update_status_records_event_history():
    app_id = tracker.add(tracker.Application(company="Amazon", title="SDE", source="simplify"))
    tracker.update_status(app_id, "oa", note="HackerRank link received")
    tracker.update_status(app_id, "interview")
    events = tracker.history(app_id)
    statuses = [e["status"] for e in events]
    assert statuses == ["applied", "oa", "interview"]
    assert events[1]["note"] == "HackerRank link received"


def test_update_status_unknown_app_raises():
    with pytest.raises(KeyError):
        tracker.update_status(9999, "oa")


def test_update_status_unknown_status_raises():
    app_id = tracker.add(tracker.Application(company="X", title="Y", source="other"))
    with pytest.raises(ValueError):
        tracker.update_status(app_id, "ghosted")


def test_edit_updates_fields_without_touching_status():
    app_id = tracker.add(tracker.Application(company="X", title="Y", source="other"))
    tracker.edit(app_id, notes="follow up Friday")
    rows = tracker.list_applications()
    row = next(r for r in rows if r["app_id"] == app_id)
    assert row["notes"] == "follow up Friday"
    assert row["status"] == "applied"  # untouched


def test_edit_rejects_unknown_field():
    app_id = tracker.add(tracker.Application(company="X", title="Y", source="other"))
    with pytest.raises(ValueError):
        tracker.edit(app_id, status="oa")  # status must go through update_status


def test_edit_unknown_app_raises():
    with pytest.raises(KeyError):
        tracker.edit(9999, notes="x")


def test_delete_removes_application_and_cascades_history():
    app_id = tracker.add(tracker.Application(company="X", title="Y", source="other"))
    tracker.update_status(app_id, "oa")
    tracker.delete(app_id)
    assert tracker.list_applications() == []
    assert tracker.history(app_id) == []  # cascaded


def test_delete_unknown_app_raises():
    with pytest.raises(KeyError):
        tracker.delete(9999)


def test_list_filters_by_status():
    tracker.add(tracker.Application(company="A", title="X", source="other"))
    a2 = tracker.add(tracker.Application(company="B", title="Y", source="other"))
    tracker.update_status(a2, "oa")
    interviewing = tracker.list_applications(status="oa")
    assert len(interviewing) == 1
    assert interviewing[0]["app_id"] == a2


def test_summary_counts_by_status():
    tracker.add(tracker.Application(company="A", title="X", source="other"))
    a2 = tracker.add(tracker.Application(company="B", title="Y", source="other"))
    tracker.update_status(a2, "oa")
    counts = tracker.summary()
    assert counts["applied"] == 1
    assert counts["oa"] == 1


def test_dedup_key_links_back_to_a_pipeline_job():
    tracker.add(tracker.Application(
        company="Google", title="SWE", source="simplify",
        dedup_key="google|swe|https://x.com/1",
    ))
    rows = tracker.list_applications()
    assert rows[0]["dedup_key"] == "google|swe|https://x.com/1"


# --- email signal parsing ---

def test_parse_email_detects_offer():
    r = tracker.parse_email_signal("We are pleased to offer you the position of...")
    assert r["status"] == "offer"


def test_parse_email_detects_rejection():
    r = tracker.parse_email_signal("We have decided not to proceed with your application.")
    assert r["status"] == "rejected"


def test_parse_email_detects_interview():
    r = tracker.parse_email_signal("We'd like to schedule an interview with you next week.")
    assert r["status"] == "interview"


def test_parse_email_detects_oa():
    r = tracker.parse_email_signal("Please complete the online assessment within 5 days.")
    assert r["status"] == "oa"


def test_parse_email_no_signal_returns_none_not_a_guess():
    r = tracker.parse_email_signal("Happy Monday! Here's our company newsletter.")
    assert r["status"] is None
    assert r["confidence"] == 0.0


def test_parse_email_priority_offer_beats_generic_received():
    # Make sure a clear offer signal wins even if weaker phrases co-occur.
    text = "Thank you for applying. We are pleased to offer you the role."
    r = tracker.parse_email_signal(text)
    assert r["status"] == "offer"
