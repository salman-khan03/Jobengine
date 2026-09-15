import pytest

from jobengine import auth, config, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Same isolation strategy as test_tracker.py: fresh SQLite file per test,
    plus a truncate for when DATABASE_URL points at a shared Postgres."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(db.status_events.delete())
        conn.execute(db.applications.delete())
        conn.execute(db.users.delete())
    yield


def test_register_then_login_roundtrip():
    user = auth.register("Person@Example.com", "correcthorsebattery")
    assert user.email == "person@example.com"  # normalized lowercase
    logged_in = auth.login("person@example.com", "correcthorsebattery")
    assert logged_in.user_id == user.user_id


def test_register_rejects_duplicate_email():
    auth.register("dup@example.com", "correcthorsebattery")
    with pytest.raises(auth.AuthError):
        auth.register("dup@example.com", "anotherpassword")


def test_register_rejects_short_password():
    with pytest.raises(auth.AuthError):
        auth.register("short@example.com", "1234567")


def test_register_rejects_invalid_email():
    with pytest.raises(auth.AuthError):
        auth.register("not-an-email", "correcthorsebattery")


def test_login_rejects_wrong_password():
    auth.register("wrongpw@example.com", "correcthorsebattery")
    with pytest.raises(auth.AuthError):
        auth.login("wrongpw@example.com", "wrongpassword")


def test_login_rejects_unknown_email():
    with pytest.raises(auth.AuthError):
        auth.login("nobody@example.com", "correcthorsebattery")


def test_password_hash_is_not_plaintext():
    user = auth.register("hash@example.com", "correcthorsebattery")
    with db.ENGINE.connect() as conn:
        from sqlalchemy import select
        row = conn.execute(
            select(db.users.c.password_hash).where(db.users.c.user_id == user.user_id)
        ).first()
    assert row.password_hash != "correcthorsebattery"
    assert row.password_hash.startswith("$2b$")


def test_token_roundtrip_decodes_to_same_user():
    user = auth.register("token@example.com", "correcthorsebattery")
    token = auth.create_token(user)
    decoded = auth.decode_token(token)
    assert decoded.user_id == user.user_id
    assert decoded.email == user.email


def test_decode_rejects_garbage_token():
    with pytest.raises(auth.AuthError):
        auth.decode_token("not.a.real.token")


def test_decode_rejects_token_signed_with_different_secret(monkeypatch):
    user = auth.register("forged@example.com", "correcthorsebattery")
    token = auth.create_token(user)
    monkeypatch.setattr(auth, "SECRET_KEY", "a-different-secret")
    with pytest.raises(auth.AuthError):
        auth.decode_token(token)
