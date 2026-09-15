"""Password hashing + JWT issuance for the multi-user HTTP API.

Scope is deliberately narrow: email + password, one users table, HS256 JWTs.
No email verification, no OAuth, no password reset flow — this gates the API
so `jobengine track` data can be per-user, not a general-purpose auth system.
The local CLI (track_cli.py) is unaffected; it's a trusted single-user
surface that was never meant to require login (see db.py's note on
`applications.user_id`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select

from . import db
from .logging_config import get_logger

log = get_logger(__name__)

# A real deployment must set this; the fallback is fine for local dev only
# (it's public in this source file, so it can never be a real secret).
SECRET_KEY = os.environ.get("JOBENGINE_SECRET_KEY", "dev-only-insecure-secret-change-me")
if SECRET_KEY == "dev-only-insecure-secret-change-me":  # pragma: no cover — warns, doesn't block
    log.warning(
        "JOBENGINE_SECRET_KEY not set — using an insecure default. "
        "Set it before deploying the API publicly."
    )

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=7)


class AuthError(Exception):
    """Bad credentials, duplicate email, or an invalid/expired token."""


@dataclass
class User:
    user_id: int
    email: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    # bcrypt's own 72-byte input cap is the reason passwords are truncated
    # here rather than left to fail opaquely on a long paste.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))


def register(email: str, password: str) -> User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("enter a valid email address")
    if len(password) < 8:
        raise AuthError("password must be at least 8 characters")

    db.init_db()
    with db.ENGINE.begin() as conn:
        existing = conn.execute(
            select(db.users.c.user_id).where(db.users.c.email == email)
        ).first()
        if existing:
            raise AuthError("an account with that email already exists")
        result = conn.execute(
            db.users.insert().values(
                email=email, password_hash=hash_password(password), created_at=_now(),
            )
        )
        user_id = result.inserted_primary_key[0]
    log.info("Registered user #%d (%s)", user_id, email)
    return User(user_id=user_id, email=email)


def login(email: str, password: str) -> User:
    email = email.strip().lower()
    db.init_db()
    with db.ENGINE.connect() as conn:
        row = conn.execute(
            select(db.users.c.user_id, db.users.c.email, db.users.c.password_hash)
            .where(db.users.c.email == email)
        ).first()
    if row is None or not verify_password(password, row.password_hash):
        raise AuthError("incorrect email or password")
    return User(user_id=row.user_id, email=row.email)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "exp": datetime.now(timezone.utc) + TOKEN_TTL,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid or expired token: {exc}")
    return User(user_id=int(payload["sub"]), email=payload["email"])
