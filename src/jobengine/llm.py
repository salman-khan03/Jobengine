"""Optional LLM cover-letter polish (OpenRouter), offline-safe.

polish() improves flow/tone only — the system prompt forbids adding facts —
and *any* failure (no key, network down, API error, malformed response)
falls back to returning the deterministic draft untouched. The pipeline
must never depend on an external API to produce output.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .logging_config import get_logger

log = get_logger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("JOBENGINE_LLM_MODEL", "x-ai/grok-4-fast")
TIMEOUT = 30


def polish(draft: str, job: dict, system: str) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return draft

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",
             "content": f"Polish this cover letter for the "
                        f"{job.get('title')} role at {job.get('company')}. "
                        f"Improve flow only; never add facts or numbers.\n\n{draft}"},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"].strip()
        return text or draft
    except (urllib.error.URLError, TimeoutError, OSError,
            KeyError, IndexError, json.JSONDecodeError) as exc:
        log.warning("LLM polish unavailable (%s) — using deterministic draft.", exc)
        return draft
