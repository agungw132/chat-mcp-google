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
            [{"name": "search_contacts", "description": "Search contacts", "parameters": {}}],
        )

    class FakeResponse:
        def __init__(self, parts):
            self.parts = parts

    class FakeChatSession:
        def __init__(self):
            self.history = []
            self.step = 0

        async def send_message_async(self, payload):
            self.step += 1
            if self.step == 1:
                fn = SimpleNamespace(name="search_contacts", args={"query": "Alice"})
                return FakeResponse([SimpleNamespace(function_call=fn)])
            return FakeResponse([SimpleNamespace(text="Jawaban final")])

    class FakeModel:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start_chat(self, history=None):
            return FakeChatSession()

    class FakeContentModule:
        class Content:
            def __init__(self, role=None, parts=None):
                self.role = role
                self.parts = parts or []

        class Part:
            def __init__(self, text=None, function_response=None):
                self.text = text
                self.function_response = function_response

        class FunctionResponse:
            def __init__(self, name, response):
                self.name = name
                self.response = response

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "configure", lambda **kwargs: None)
    monkeypatch.setattr(chat_service.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(chat_service, "content", FakeContentModule)

    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))
    outputs = await _collect_stream(chat_service.chat("Cari kontak Alice", [], "gemini-3-flash-preview"))

    assert outputs[-1][-1]["content"] == "Jawaban final"
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
