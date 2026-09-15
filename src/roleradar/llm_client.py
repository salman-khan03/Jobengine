"""Provider-agnostic LLM client (Gemini / Groq / OpenRouter), offline-safe.

Three rules this module exists to enforce:

1. **The pipeline never depends on it.** Every entry point returns `None`
   instead of raising when there is no key, no network, a timeout, a rate
   limit, or a malformed body. Callers treat `None` as "write the
   deterministic version" -- so `pytest` and CI run the full decision path
   with no API key and no network, and a provider outage degrades the product
   from "explained" to "explained more tersely", never to "down".
2. **JSON or nothing.** Free-form prose from a model is unvalidatable. Every
   call requests structured output and `complete_json` parses it, so
   `explain.py` can check claims against evidence ids mechanically.
3. **Same interface for every provider.** Gemini and Groq were named as
   targets, but the provider is one env var. urllib rather than three vendor
   SDKs keeps the dependency footprint at zero and the failure modes uniform.

Responses are content-addressed and cached on disk. Re-scoring the same job
after a code change should not re-bill the same tokens, and a deterministic
cache makes explanations reproducible while iterating on prompts.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jobengine.logging_config import get_logger

log = get_logger(__name__)

TIMEOUT = int(os.environ.get("ROLERADAR_LLM_TIMEOUT", "30"))
MAX_RETRIES = 2

# provider -> (env var holding the key, default model)
PROVIDERS: dict[str, tuple[str, str]] = {
    "gemini": ("GEMINI_API_KEY", "gemini-2.0-flash"),
    "groq": ("GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "openrouter": ("OPENROUTER_API_KEY", "x-ai/grok-4-fast"),
}
# Probed in this order when ROLERADAR_LLM_PROVIDER is unset. Groq first for
# latency, Gemini next for cost at this volume, OpenRouter last because it is
# the one jobengine already used and is the fallback aggregator.
_AUTO_ORDER = ("groq", "gemini", "openrouter")


def active_provider() -> tuple[str, str, str] | None:
    """(provider, api_key, model) for the first usable provider, else None."""
    explicit = os.environ.get("ROLERADAR_LLM_PROVIDER", "").strip().lower()
    order = (explicit,) if explicit else _AUTO_ORDER
    for name in order:
        spec = PROVIDERS.get(name)
        if not spec:
            log.warning("Unknown ROLERADAR_LLM_PROVIDER %r; ignoring.", name)
            continue
        env_key, default_model = spec
        key = os.environ.get(env_key)
        if key:
            model = os.environ.get("ROLERADAR_LLM_MODEL", "").strip() or default_model
            return name, key, model
    return None


def available() -> bool:
    return active_provider() is not None


# --- cache ------------------------------------------------------------------

def _cache_dir() -> Path:
    return Path(os.environ.get("ROLERADAR_LLM_CACHE",
                               Path.home() / ".cache" / "roleradar" / "llm"))


def _cache_key(provider: str, model: str, system: str, user: str) -> str:
    blob = f"{provider}|{model}|{system}|{user}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _cache_get(key: str) -> str | None:
    if os.environ.get("ROLERADAR_LLM_NO_CACHE") or not os.environ.get("ROLERADAR_LLM_CACHE"):
        return None
    path = _cache_dir() / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["response"]
    except (OSError, ValueError, KeyError):
        return None


def _cache_put(key: str, response: str) -> None:
    if os.environ.get("ROLERADAR_LLM_NO_CACHE") or not os.environ.get("ROLERADAR_LLM_CACHE"):
        return
    try:
        d = _cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(
            json.dumps({"response": response, "cached_at": time.time()}),
            encoding="utf-8")
    except OSError as exc:  # a read-only cache dir must not break scoring
        log.debug("LLM cache write skipped: %s", exc)


# --- request building -------------------------------------------------------

def _openai_style(url: str, key: str, model: str, system: str, user: str,
                  want_json: bool) -> urllib.request.Request:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
    }
    if want_json:
        body["response_format"] = {"type": "json_object"}
    return urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


def _gemini(key: str, model: str, system: str, user: str,
            want_json: bool) -> urllib.request.Request:
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.2},
    }
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    return urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )


def _parse(provider: str, payload: dict) -> str:
    if provider == "gemini":
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    return payload["choices"][0]["message"]["content"]


def complete(system: str, user: str, want_json: bool = True) -> str | None:
    """One completion, or None if the model could not be reached.

    Retries only on transient classes (429 / 5xx / socket errors). A 400 means
    the request is wrong and retrying it just burns the user's quota twice.
    """
    active = active_provider()
    if active is None:
        return None
    provider, key, model = active

    ckey = _cache_key(provider, model, system, user)
    hit = _cache_get(ckey)
    if hit is not None:
        return hit

    if provider == "gemini":
        req = _gemini(key, model, system, user, want_json)
    elif provider == "groq":
        req = _openai_style("https://api.groq.com/openai/v1/chat/completions",
                            key, model, system, user, want_json)
    else:
        req = _openai_style("https://openrouter.ai/api/v1/chat/completions",
                            key, model, system, user, want_json)

    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = (_parse(provider, payload) or "").strip()
            if text:
                _cache_put(ckey, text)
                return text
            return None
        except urllib.error.HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code < 600
            log.warning("%s HTTP %s on attempt %d%s", provider, exc.code,
                        attempt + 1, " (retrying)" if transient else "")
            if not transient or attempt == MAX_RETRIES:
                return None
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, OSError,
                KeyError, IndexError, ValueError) as exc:
            log.warning("%s call failed (%s) — falling back.", provider, exc)
            if attempt == MAX_RETRIES:
                return None
            time.sleep(2 ** attempt)
    return None


def _strip_fences(text: str) -> str:
    """Models wrap JSON in ```json fences even when told not to."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def complete_json(system: str, user: str) -> dict | None:
    """A completion parsed as a JSON object, or None.

    One repair attempt: slice from the first `{` to the last `}` before giving
    up, which recovers the common "here is your JSON:" preamble without
    inviting a second billed round-trip to fix formatting.
    """
    raw = complete(system, user, want_json=True)
    if raw is None:
        return None
    text = _strip_fences(raw)
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    log.warning("LLM returned unparseable JSON (%d chars) — falling back.", len(raw))
    return None
