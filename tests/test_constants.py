import chat_google.constants as constants


def test_resolve_default_model_from_env(monkeypatch):
    monkeypatch.setenv("MODEL", "gemini-2.5-flash")
    assert constants.resolve_default_model() == "gemini-2.5-flash"


def test_resolve_default_model_fallback_when_invalid(monkeypatch):
    monkeypatch.setenv("MODEL", "unknown-model")
    assert constants.resolve_default_model() == "gemini-3-flash-preview"
