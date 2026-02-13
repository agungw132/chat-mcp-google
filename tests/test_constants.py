import chat_google.constants as constants


def test_resolve_default_model_from_env(monkeypatch):
    monkeypatch.setenv("MODEL", "gemini-2.5-flash")
    assert constants.resolve_default_model() == "gemini-2.5-flash"


def test_resolve_default_model_from_env_sumopod_model(monkeypatch):
    monkeypatch.setenv("MODEL", "azure_ai/kimi-k2.5")
    assert constants.resolve_default_model() == "azure_ai/kimi-k2.5"


def test_resolve_default_model_from_env_new_sumopod_model(monkeypatch):
    monkeypatch.setenv("MODEL", "kimi-k2-thinking-251104")
    assert constants.resolve_default_model() == "kimi-k2-thinking-251104"


def test_resolve_default_model_fallback_when_invalid(monkeypatch):
    monkeypatch.setenv("MODEL", "unknown-model")
    assert constants.resolve_default_model() == "azure_ai/kimi-k2.5"
