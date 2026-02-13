import json
from types import SimpleNamespace

import pytest

from chat_google import chat_service


async def _collect_stream(gen):
    results = []
    async for item in gen:
        results.append(item)
    return results


@pytest.mark.asyncio
async def test_chat_empty_message():
    outputs = await _collect_stream(chat_service.chat("", [{"role": "user", "content": "x"}], "gemini-3-flash-preview"))
    assert outputs == [[{"role": "user", "content": "x"}]]


def test_normalize_content_text_list_payload():
    payload = [{"type": "text", "text": "ringkas email"}, {"type": "text", "text": "hari ini"}]
    assert chat_service.normalize_content_text(payload) == "ringkas email\nhari ini"


def test_sanitize_schema_for_gemini():
    schema = {
        "type": "object",
        "title": "IgnoredTitle",
        "properties": {
            "name": {"type": "string", "title": "Name", "default": "abc"},
            "age": {"type": "integer"},
        },
        "default": {},
    }
    sanitized = chat_service.sanitize_schema_for_gemini(schema)
    assert "title" not in sanitized
    assert "default" not in sanitized
    assert "title" not in sanitized["properties"]["name"]
    assert "default" not in sanitized["properties"]["name"]


@pytest.mark.asyncio
async def test_chat_gemini_missing_key(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "")
    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))
    outputs = await _collect_stream(chat_service.chat("halo", [], "gemini-3-flash-preview"))
    assert outputs[-1][-1]["content"] == "Error: GOOGLE_GEMINI_API_KEY not found in .env"
    assert metrics and metrics[0]["status"] == "error_missing_gemini_key"


@pytest.mark.asyncio
async def test_chat_gemini_tool_flow(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [SimpleNamespace(text="tool-output")]

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return FakeResult()

    fake_session = FakeSession()

    async def fake_collect(*args, **kwargs):
        return (
            {"search_contacts": fake_session},
            {"search_contacts": "contacts"},
            [],
            [],
        )

    class FakeAioClient:
        def __init__(self):
            self._step = 0
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def generate_content(self, **kwargs):
            self._step += 1
            if self._step == 1:
                return SimpleNamespace(
                    function_calls=[SimpleNamespace(name="search_contacts", args={"query": "Alice"})],
                    candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
                    text=None,
                )
            return SimpleNamespace(function_calls=[], candidates=[], text="Final answer")

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = FakeAioClient()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "Client", FakeClient)

    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))
    outputs = await _collect_stream(chat_service.chat("Cari kontak Alice", [], "gemini-3-flash-preview"))

    assert outputs[-1][-1]["content"] == "Final answer"
    assert fake_session.calls == [("search_contacts", {"query": "Alice"})]
    assert metrics and metrics[0]["invoked_tools"] == ["search_contacts"]


@pytest.mark.asyncio
async def test_chat_openai_non_200(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    class FakeResponse:
        status_code = 500

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())

    outputs = await _collect_stream(chat_service.chat("hello", [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Error: 500"


@pytest.mark.asyncio
async def test_chat_openai_tool_and_stream(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [SimpleNamespace(text="tool-resp")]

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return FakeResult()

    fake_session = FakeSession()

    async def fake_collect(*args, **kwargs):
        return (
            {"list_recent_emails": fake_session},
            {"list_recent_emails": "gmail"},
            [{"type": "function", "function": {"name": "list_recent_emails"}}],
            [],
        )

    class FirstResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "list_recent_emails",
                                        "arguments": json.dumps({"count": 2}),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            lines = [
                'data: {"choices":[{"delta":{"content":"Halo "}}]}',
                'data: {"choices":[{"delta":{"content":"dunia"}}]}',
                "data: [DONE]",
            ]
            for line in lines:
                yield line

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FirstResponse()

        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(chat_service.chat("cek inbox", [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Halo dunia"
    assert fake_session.calls == [("list_recent_emails", {"count": 2})]
    assert metrics and metrics[0]["invoked_servers"] == ["gmail"]


@pytest.mark.asyncio
async def test_chat_metrics_accepts_list_message_payload(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    class FakeResponse:
        status_code = 500

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    payload = [{"text": "ringkas email hari ini", "type": "text"}]
    outputs = await _collect_stream(chat_service.chat(payload, [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Error: 500"
    assert metrics[0]["user_question"] == "ringkas email hari ini"


@pytest.mark.asyncio
async def test_chat_openai_tool_error_is_captured_in_metrics(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [SimpleNamespace(text="Error: Search failed: 500")]

    class FakeSession:
        async def call_tool(self, name, args):
            return FakeResult()

    async def fake_collect(*args, **kwargs):
        return (
            {"search_contacts": FakeSession()},
            {"search_contacts": "contacts"},
            [{"type": "function", "function": {"name": "search_contacts"}}],
            [],
        )

    class FirstResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "search_contacts",
                                        "arguments": json.dumps({"query": "Alice"}),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Done"}}]}'
            yield "data: [DONE]"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FirstResponse()

        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(chat_service.chat("cari alice", [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Done"
    assert metrics and metrics[0]["status"] == "success_with_tool_errors"
    assert metrics[0]["tool_errors"]
    assert "search_contacts" in metrics[0]["tool_errors"][0]
