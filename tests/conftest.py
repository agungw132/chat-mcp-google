import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def _default_env(monkeypatch, request):
    if request.node.get_closest_marker("live_smoke"):
        return
    monkeypatch.setenv("GOOGLE_ACCOUNT", "tester@example.com")
    monkeypatch.setenv("GOOGLE_APP_KEY", "app-password")
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "drive-test-token")
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("API_KEY", "openai-test-key")
