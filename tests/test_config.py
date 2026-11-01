import pytest

from src.config import load_settings


def test_offline_settings_load_without_api_key(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    settings = load_settings(require_llm=False)

    assert settings.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.llm_provider == "groq"
    assert settings.chroma_collection == "hdfc_mf_facts"
    assert settings.chunk_strategy == "section_prefix_v1"
    assert settings.top_k == 4
    assert settings.score_threshold == 0.35
    assert settings.llm_model == ""
    assert settings.api_key == ""
    assert settings.sources_path.is_file()
    assert "groww.in" in settings.allowed_hosts


def test_online_settings_require_model_before_any_provider(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="LLM_MODEL is empty"):
        load_settings(require_llm=True)
