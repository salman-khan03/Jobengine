import pytest

from jobengine import auth, config, db, seed_demo, tracker


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(db.status_events.delete())
        conn.execute(db.applications.delete())
        conn.execute(db.users.delete())
    yield


def test_seed_creates_user_and_applications():
    user_id = seed_demo.seed()
    apps = tracker.list_applications(user_id=user_id)
    assert len(apps) == len(seed_demo._DEMO_APPLICATIONS)
    assert auth.login(seed_demo.DEMO_EMAIL, seed_demo.DEMO_PASSWORD).user_id == user_id


def test_seed_is_idempotent_without_reset():
    """Redeploys re-run this; it must not duplicate rows."""
    user_id = seed_demo.seed()
    seed_demo.seed()
    assert len(tracker.list_applications(user_id=user_id)) == len(seed_demo._DEMO_APPLICATIONS)


def test_reset_rebuilds_rather_than_appending():
    user_id = seed_demo.seed()
    tracker.add(tracker.Application(company="Extra", title="Role", source="other"),
                user_id=user_id)
    assert len(tracker.list_applications(user_id=user_id)) == len(seed_demo._DEMO_APPLICATIONS) + 1

    seed_demo.seed(reset=True)
    apps = tracker.list_applications(user_id=user_id)
    assert len(apps) == len(seed_demo._DEMO_APPLICATIONS)
    assert "Extra" not in {a["company"] for a in apps}


def test_seeded_funnel_spans_multiple_stages():
    """A demo tracker showing only offers is obviously fabricated; the seed
    is supposed to include rejections and stalled applications too."""
    user_id = seed_demo.seed()
    statuses = {a["status"] for a in tracker.list_applications(user_id=user_id)}
    assert {"offer", "rejected", "interview", "oa", "applied"} <= statuses


def test_demo_data_is_scoped_to_the_demo_user():
    """Regression guard on the multi-tenancy rule: another user must not see
    the demo account's rows."""
    seed_demo.seed()
    other = auth.register("other@example.com", "correcthorsebattery")
    assert tracker.list_applications(user_id=other.user_id) == []


def test_status_history_is_populated_for_transitioned_rows():
    user_id = seed_demo.seed()
    offer = next(a for a in tracker.list_applications(user_id=user_id)
                 if a["status"] == "offer")
    events = tracker.history(offer["app_id"], user_id=user_id)
    assert [e["status"] for e in events] == ["applied", "offer"]
