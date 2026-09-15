"""AWS Lambda entry points for the scheduled refresh and embedding worker.

The module keeps AWS imports inside functions so the core package remains
usable and testable without boto3. Lambda provides boto3 in its Python runtime;
the deployment artifact only needs JobEngine and its declared dependencies.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


def _client(service: str):
    import boto3

    return boto3.client(service)


def _configure_runtime() -> str:
    """Load DATABASE_URL from Secrets Manager before importing app modules."""
    secret_arn = os.environ["DATABASE_SECRET_ARN"]
    payload = _client("secretsmanager").get_secret_value(SecretId=secret_arn)
    raw = payload.get("SecretString")
    if not raw:
        raise RuntimeError("database secret has no SecretString")

    # Accept either the plain URL Terraform stores today or a JSON secret so
    # rotation tooling can migrate the format without changing the function.
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    database_url = parsed.get("DATABASE_URL") if isinstance(parsed, dict) else parsed
    if not isinstance(database_url, str) or not database_url.strip():
        raise RuntimeError("database secret must be a URL or contain DATABASE_URL")

    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("JOBENGINE_HOME", "/tmp/jobengine")
    return database_url


def _metric(name: str, value: float, unit: str = "Count") -> None:
    _client("cloudwatch").put_metric_data(
        Namespace="JobEngine",
        MetricData=[{"MetricName": name, "Value": value, "Unit": unit}],
    )


def _enqueue_embeddings(rows: list[tuple[str, str]]) -> int:
    """Send one job per SQS message, using the API's ten-message batch limit."""
    queue_url = os.environ["EMBEDDING_QUEUE_URL"]
    sqs = _client("sqs")
    sent = 0
    for start in range(0, len(rows), 10):
        chunk = rows[start:start + 10]
        entries = [
            {
                "Id": str(offset),
                "MessageBody": json.dumps({"dedup_key": key, "text": text}),
            }
            for offset, (key, text) in enumerate(chunk)
        ]
        result = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failures = result.get("Failed", [])
        if failures:
            raise RuntimeError(f"SQS rejected {len(failures)} embedding messages")
        sent += len(result.get("Successful", entries))
    return sent


def refresh_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Fetch, rebuild PostgreSQL, and enqueue active jobs for embedding."""
    _configure_runtime()

    # These imports intentionally happen after JOBENGINE_HOME is configured:
    # config.py resolves its paths at import time and Lambda only permits writes
    # under /tmp.
    from . import build, db, fetch

    started = time.perf_counter()
    if not fetch.fetch_all():
        raise RuntimeError("one or more upstream listing feeds failed to refresh")

    stats = build.build(embed=False)
    with db.get_engine().connect() as conn:
        rows = [
            (row.dedup_key, f"{row.title or ''} {row.category or ''} {row.company or ''}")
            for row in conn.execute(
                db.jobs.select()
                .with_only_columns(
                    db.jobs.c.dedup_key,
                    db.jobs.c.title,
                    db.jobs.c.category,
                    db.jobs.c.company,
                )
                .where(db.jobs.c.active == 1, db.jobs.c.is_visible == 1)
            )
        ]
    queued = _enqueue_embeddings(rows)
    duration_ms = (time.perf_counter() - started) * 1000

    _metric("ListingsProcessed", stats["raw"])
    _metric("ListingsDeduplicated", stats["deduped"])
    _metric("DuplicatesRemoved", stats["removed"])
    _metric("RefreshDuration", duration_ms, "Milliseconds")

    return {"ok": True, "stats": stats, "embeddings_queued": queued}


def embedding_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Embed an SQS batch and report only failed messages for retry."""
    _configure_runtime()
    from . import embeddings

    failures: list[dict[str, str]] = []
    processed = 0
    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            key = body["dedup_key"]
            text = body["text"]
            if not isinstance(key, str) or not isinstance(text, str):
                raise ValueError("dedup_key and text must be strings")
            embeddings.build_job_embeddings([(key, text)])
            processed += 1
        except Exception:
            # Lambda's ReportBatchItemFailures contract retries just this
            # message rather than replaying successful siblings in the batch.
            failures.append({"itemIdentifier": message_id})

    if processed:
        _metric("EmbeddingsProcessed", processed)
    if failures:
        _metric("EmbeddingFailures", len(failures))
    return {"batchItemFailures": failures}
