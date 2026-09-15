import pytest
from fastapi.testclient import TestClient

from jobengine import analytics, api, config, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Same isolation strategy as test_auth.py: fresh SQLite file per test."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setenv("JOBENGINE_ANALYTICS", "1")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(db.api_events.delete())
        conn.execute(db.status_events.delete())
        conn.execute(db.applications.delete())
        conn.execute(db.users.delete())
    yield


@pytest.fixture
def client():
    return TestClient(api.app)


# --- percentile maths -------------------------------------------------------

def test_percentile_nearest_rank():
    values = list(range(1, 101))  # 1..100
    assert analytics._percentile(values, 0.50) == 50
    assert analytics._percentile(values, 0.95) == 95
    assert analytics._percentile(values, 0.99) == 99


def test_percentile_empty_sample_is_zero_not_crash():
    assert analytics._percentile([], 0.95) == 0


def test_percentile_single_value():
    assert analytics._percentile([7], 0.99) == 7


# --- recording --------------------------------------------------------------

def test_record_writes_a_row():
    analytics.record("/api/jobs", "GET", 200, 12.7)
    with db.ENGINE.connect() as conn:
        rows = conn.execute(db.api_events.select()).all()
    assert len(rows) == 1
    assert rows[0].route == "/api/jobs"
    assert rows[0].duration_ms == 12  # truncated to int


def test_record_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("JOBENGINE_ANALYTICS", "0")
    analytics.record("/api/jobs", "GET", 200, 5.0)
    with db.ENGINE.connect() as conn:
        assert conn.execute(db.api_events.select()).all() == []


def test_record_never_raises_when_the_write_fails(monkeypatch):
    """Analytics must not be able to break a working request."""
    def boom():
        raise RuntimeError("database on fire")
    monkeypatch.setattr(db, "get_engine", boom)
    analytics.record("/api/jobs", "GET", 200, 5.0)  # must not raise


# --- summary ----------------------------------------------------------------

def test_summary_on_empty_window_returns_zeros():
    out = analytics.summary(hours=24)
    assert out["requests"] == 0
    assert out["error_rate"] == 0.0
    assert out["latency_ms"]["p95"] == 0


def test_summary_counts_5xx_as_errors_but_not_4xx():
    for _ in range(8):
        analytics.record("/api/jobs", "GET", 200, 10)
    analytics.record("/api/jobs", "GET", 404, 10)
    analytics.record("/api/jobs", "GET", 500, 10)

    out = analytics.summary(hours=24)
    assert out["requests"] == 10
    assert out["error_rate"] == 0.1          # only the 500
    assert out["client_error_rate"] == 0.1   # only the 404


def test_summary_groups_by_route_ordered_by_volume():
    for _ in range(3):
        analytics.record("/api/jobs", "GET", 200, 10)
    analytics.record("/api/health", "GET", 200, 1)

    routes = [r["route"] for r in analytics.summary()["by_route"]]
    assert routes == ["/api/jobs", "/api/health"]


def test_summary_active_users_counts_distinct_authenticated_users():
    analytics.record("/api/applications", "GET", 200, 10, user_id=1)
    analytics.record("/api/applications", "GET", 200, 10, user_id=1)
    analytics.record("/api/applications", "GET", 200, 10, user_id=2)
    analytics.record("/api/jobs", "GET", 200, 10, user_id=None)

    assert analytics.summary()["active_users"] == 2


# --- middleware integration -------------------------------------------------

def test_health_reports_ok_and_backend(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["backend"] == "sqlite"


def test_middleware_records_the_route_template_not_the_concrete_path(client):
    """The whole point of using request.scope['route'] — otherwise every
    app_id would become its own row bucket and aggregation is impossible."""
    client.patch("/api/applications/7", json={"notes": "x"})   # 401, still recorded
    client.patch("/api/applications/99", json={"notes": "x"})

    with db.ENGINE.connect() as conn:
        routes = [r.route for r in conn.execute(db.api_events.select()).all()]
    assert routes == ["/api/applications/{app_id}"] * 2


def test_middleware_adds_a_response_time_header(client):
    resp = client.get("/api/health")
    assert float(resp.headers["X-Response-Time-ms"]) >= 0


def test_analytics_summary_endpoint_requires_auth(client):
    assert client.get("/api/analytics/summary").status_code == 401
