from roleradar import llm_client


def test_empty_model_configuration_uses_provider_default(monkeypatch):
    monkeypatch.setenv("ROLERADAR_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("ROLERADAR_LLM_MODEL", "  ")
    assert llm_client.active_provider()[2] == llm_client.PROVIDERS["groq"][1]


def test_default_never_persists_or_reads_resume_explanations(monkeypatch):
    monkeypatch.delenv("ROLERADAR_LLM_CACHE", raising=False)
    monkeypatch.delenv("ROLERADAR_LLM_NO_CACHE", raising=False)

    def forbidden():
        raise AssertionError("default explanation path must not touch disk")

    monkeypatch.setattr(llm_client, "_cache_dir", forbidden)
    llm_client._cache_put("key", "candidate evidence")
    assert llm_client._cache_get("key") is None


def test_explicit_cache_opt_in_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLERADAR_LLM_CACHE", str(tmp_path))
    monkeypatch.delenv("ROLERADAR_LLM_NO_CACHE", raising=False)
    llm_client._cache_put("key", "candidate evidence")
    assert llm_client._cache_get("key") == "candidate evidence"
    monkeypatch.setenv("ROLERADAR_LLM_NO_CACHE", "1")
    assert llm_client._cache_get("key") is None
