import json
import os

import pytest

from jobengine import aws_handlers


@pytest.fixture(autouse=True)
def restore_environment():
    """Undo environment changes made *inside* the code under test.

    `_configure_runtime` assigns `os.environ["DATABASE_URL"]` directly, and
    monkeypatch only reverts variables it set itself — a value written by the
    production code stays set for the rest of the session. Without this
    fixture, these tests leave `DATABASE_URL` pointing at a fake Postgres host
    and every later test that touches the database fails with a connection
    error, in a file that has nothing to do with AWS.
    """
    snapshot = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(snapshot)


class FakeSecrets:
    def __init__(self, value):
        self.value = value

    def get_secret_value(self, **kwargs):
        return {"SecretString": self.value}


def test_configure_runtime_accepts_plain_url(monkeypatch):
    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(aws_handlers, "_client", lambda service: FakeSecrets("postgresql://db"))

    assert aws_handlers._configure_runtime() == "postgresql://db"
    assert aws_handlers.os.environ["DATABASE_URL"] == "postgresql://db"


def test_configure_runtime_accepts_json_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:test")
    secret = json.dumps({"DATABASE_URL": "postgresql+psycopg://db"})
    monkeypatch.setattr(aws_handlers, "_client", lambda service: FakeSecrets(secret))

    assert aws_handlers._configure_runtime() == "postgresql+psycopg://db"


def test_embedding_handler_reports_only_failed_messages(monkeypatch):
    from jobengine import embeddings

    monkeypatch.setattr(aws_handlers, "_configure_runtime", lambda: "sqlite://")
    monkeypatch.setattr(aws_handlers, "_metric", lambda *args: None)

    def build(rows):
        if rows[0][0] == "bad":
            raise RuntimeError("boom")
        return 1

    monkeypatch.setattr(embeddings, "build_job_embeddings", build)
    event = {
        "Records": [
            {"messageId": "one", "body": json.dumps({"dedup_key": "ok", "text": "java"})},
            {"messageId": "two", "body": json.dumps({"dedup_key": "bad", "text": "python"})},
        ]
    }

    assert aws_handlers.embedding_handler(event, None) == {
        "batchItemFailures": [{"itemIdentifier": "two"}]
    }


def test_enqueue_embeddings_uses_ten_message_batches(monkeypatch):
    calls = []

    class FakeSqs:
        def send_message_batch(self, **kwargs):
            calls.append(kwargs)
            return {"Successful": kwargs["Entries"]}

    monkeypatch.setenv("EMBEDDING_QUEUE_URL", "queue")
    monkeypatch.setattr(aws_handlers, "_client", lambda service: FakeSqs())
    rows = [(str(i), f"job {i}") for i in range(23)]

    assert aws_handlers._enqueue_embeddings(rows) == 23
    assert [len(call["Entries"]) for call in calls] == [10, 10, 3]
