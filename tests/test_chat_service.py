import json
from datetime import datetime
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


def test_get_servers_config_includes_drive_and_maps():
    names = [cfg.name for cfg in chat_service.get_servers_config()]
    scripts = [cfg.script for cfg in chat_service.get_servers_config()]
    assert "drive" in names
    assert "maps" in names
    assert "drive_server.py" in scripts
    assert "maps_server.py" in scripts


def test_normalize_content_text_list_payload():
    payload = [{"type": "text", "text": "ringkas email"}, {"type": "text", "text": "hari ini"}]
    assert chat_service.normalize_content_text(payload) == "ringkas email\nhari ini"


def test_normalize_add_event_args_from_message_tomorrow():
    args = {
        "summary": "Makan siang",
        "start_time": "2025-01-20 14:00",
        "duration_minutes": 120,
    }
    normalized = chat_service._normalize_add_event_args_from_message(
        args,
        'bikin agenda "Makan Siang" besok jam 14',
        now=datetime(2026, 2, 13, 9, 0),
    )
    assert normalized["start_time"] == "2026-02-14 14:00"


def test_normalize_add_event_args_from_message_tomorrow_english():
    args = {"start_time": "tomorrow at 2 pm", "summary": "Lunch"}
    normalized = chat_service._normalize_add_event_args_from_message(
        args,
        "create lunch event tomorrow at 14:30",
        now=datetime(2026, 2, 13, 9, 0),
    )
    assert normalized["start_time"] == "2026-02-14 14:30"


def test_normalize_add_event_args_from_message_explicit_date_kept():
    args = {"start_time": "2025-01-20 14:00", "summary": "Lunch"}
    normalized = chat_service._normalize_add_event_args_from_message(
        args,
        "create event on 2025-01-20 at 14:00",
        now=datetime(2026, 2, 13, 9, 0),
    )
    assert normalized["start_time"] == "2025-01-20 14:00"


def test_with_runtime_time_context_includes_date_hint():
    text = chat_service._with_runtime_time_context("Base instruction.")
    assert "Current local date:" in text
    assert "Current local time:" in text
    assert "do not ask the user to confirm current date" in text


def test_extract_invite_emails_and_intent():
    message = "please invite alice@example.com and ALICE@example.com, plus bob@test.io"
    emails = chat_service._extract_invite_emails(message)
    assert emails == ["alice@example.com", "bob@test.io"]
    assert chat_service._has_invite_intent(message) is True


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
async def test_chat_gemini_retries_503_then_succeeds(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    class FakeAPIError(Exception):
        def __init__(self, code):
            super().__init__(f"api error {code}")
            self.code = code

    class FakeAioClient:
        def __init__(self):
            self.models = self
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise FakeAPIError(503)
            return SimpleNamespace(function_calls=[], candidates=[], text="Recovered response")

    class FakeClient:
        instance = None

        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = FakeAioClient()
            FakeClient.instance = self

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "Client", FakeClient)
    monkeypatch.setattr(chat_service, "genai_errors", SimpleNamespace(APIError=FakeAPIError))
    monkeypatch.setattr(chat_service.asyncio, "sleep", fake_sleep)

    outputs = await _collect_stream(chat_service.chat("halo", [], "gemini-3-flash-preview"))
    assert outputs[-1][-1]["content"] == "Recovered response"
    assert FakeClient.instance is not None
    assert FakeClient.instance.aio.calls == 2


@pytest.mark.asyncio
async def test_chat_gemini_503_after_retries_returns_actionable_error(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    class FakeAPIError(Exception):
        def __init__(self, code):
            super().__init__(f"api error {code}")
            self.code = code

    class FakeAioClient:
        def __init__(self):
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def generate_content(self, **kwargs):
            raise FakeAPIError(503)

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = FakeAioClient()

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "Client", FakeClient)
    monkeypatch.setattr(chat_service, "genai_errors", SimpleNamespace(APIError=FakeAPIError))
    monkeypatch.setattr(chat_service.asyncio, "sleep", fake_sleep)

    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))
    outputs = await _collect_stream(chat_service.chat("halo", [], "gemini-3-flash-preview"))

    assert "temporarily unavailable (503) after retries" in outputs[-1][-1]["content"]
    assert metrics and metrics[0]["status"] == "error_gemini_api"


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
async def test_chat_openai_timeout(monkeypatch):
    async def fake_collect(*args, **kwargs):
        return {}, {}, [], []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise chat_service.httpx.ReadTimeout("timeout")

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat("find recent emails from social school, summarize", [], "azure_ai/kimi-k2.5")
    )
    assert "Model API request timed out" in outputs[-1][-1]["content"]
    assert metrics and metrics[0]["status"] == "error_http_timeout"


@pytest.mark.asyncio
async def test_chat_openai_timeout_after_tool_returns_last_tool_result(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [SimpleNamespace(text="Successfully added event: 'Lunch' on 2026-02-14 14:00")]

    class FakeSession:
        async def call_tool(self, name, args):
            return FakeResult()

    async def fake_collect(*args, **kwargs):
        return (
            {"add_event": FakeSession()},
            {"add_event": "calendar"},
            [{"type": "function", "function": {"name": "add_event"}}],
            [],
        )

    class FakeResponse:
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
                                        "name": "add_event",
                                        "arguments": json.dumps(
                                            {
                                                "summary": "Lunch",
                                                "start_time": "2025-01-20 14:00",
                                                "duration_minutes": 60,
                                                "description": "",
                                            }
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse()
            raise chat_service.httpx.ReadTimeout("timeout")

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat(
            "bikin agenda lunch besok jam 14",
            [],
            "azure_ai/kimi-k2.5",
        )
    )
    final_text = outputs[-1][-1]["content"]
    assert "timed out after tool execution" in final_text
    assert "Successfully added event: 'Lunch' on 2026-02-14 14:00" in final_text
    assert metrics and metrics[0]["status"] == "error_http_timeout_after_tool"


@pytest.mark.asyncio
async def test_chat_openai_auto_send_invite_email_after_add_event(monkeypatch):
    class FakeResult:
        def __init__(self, text):
            self.content = [SimpleNamespace(text=text)]

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            if name == "add_event":
                return FakeResult("Successfully added event: 'Lunch' on 2026-02-14 14:00")
            return FakeResult("Email sent to alice@example.com")

    fake_session = FakeSession()

    async def fake_collect(*args, **kwargs):
        return (
            {"add_event": fake_session, "send_email": fake_session},
            {"add_event": "calendar", "send_email": "gmail"},
            [
                {"type": "function", "function": {"name": "add_event"}},
                {"type": "function", "function": {"name": "send_email"}},
            ],
            [],
        )

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "add_event",
                                                "arguments": json.dumps(
                                                    {
                                                        "summary": "Lunch",
                                                        "start_time": "2026-02-14 14:00",
                                                        "duration_minutes": 60,
                                                        "description": "",
                                                    }
                                                ),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            return FakeResponse({"choices": [{"message": {"content": "Agenda created."}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat(
            "please create lunch event and invite alice@example.com",
            [],
            "azure_ai/kimi-k2.5",
        )
    )
    final_text = outputs[-1][-1]["content"]
    assert "Agenda created." in final_text
    assert "Invitation delivery result(s):" in final_text
    assert "Email sent to alice@example.com" in final_text
    assert fake_session.calls[0][0] == "add_event"
    assert fake_session.calls[1][0] == "send_email"
    assert metrics and metrics[0]["invoked_tools"] == ["add_event", "send_email"]


@pytest.mark.asyncio
async def test_chat_openai_auto_send_calendar_invite_email_when_available(monkeypatch):
    class FakeResult:
        def __init__(self, text):
            self.content = [SimpleNamespace(text=text)]

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            if name == "add_event":
                return FakeResult("Successfully added event: 'Lunch' on 2026-02-14 14:00")
            if name == "send_calendar_invite_email":
                return FakeResult("Calendar invitation email successfully sent to alice@example.com")
            return FakeResult("unexpected")

    fake_session = FakeSession()

    async def fake_collect(*args, **kwargs):
        return (
            {
                "add_event": fake_session,
                "send_calendar_invite_email": fake_session,
                "send_email": fake_session,
            },
            {
                "add_event": "calendar",
                "send_calendar_invite_email": "gmail",
                "send_email": "gmail",
            },
            [
                {"type": "function", "function": {"name": "add_event"}},
                {"type": "function", "function": {"name": "send_calendar_invite_email"}},
                {"type": "function", "function": {"name": "send_email"}},
            ],
            [],
        )

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "add_event",
                                                "arguments": json.dumps(
                                                    {
                                                        "summary": "Lunch",
                                                        "start_time": "2026-02-14 14:00",
                                                        "duration_minutes": 60,
                                                        "description": "Location: Tatsu",
                                                    }
                                                ),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            return FakeResponse({"choices": [{"message": {"content": "Agenda created."}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat(
            "please create lunch event and invite alice@example.com",
            [],
            "azure_ai/kimi-k2.5",
        )
    )
    final_text = outputs[-1][-1]["content"]
    assert "Invitation delivery result(s):" in final_text
    assert "Calendar invitation email successfully sent to alice@example.com" in final_text
    assert fake_session.calls[0][0] == "add_event"
    assert fake_session.calls[1][0] == "send_calendar_invite_email"
    assert metrics and metrics[0]["invoked_tools"] == ["add_event", "send_calendar_invite_email"]


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

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
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
                )
            return FakeResponse({"choices": [{"message": {"content": "Halo dunia"}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(chat_service.chat("cek inbox", [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Halo dunia"
    assert fake_session.calls == [("list_recent_emails", {"count": 2})]
    assert metrics and metrics[0]["invoked_servers"] == ["gmail"]


@pytest.mark.asyncio
async def test_chat_openai_multi_round_tool_calls(monkeypatch):
    class FakeResult:
        def __init__(self, text):
            self.content = [SimpleNamespace(text=text)]

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            if name == "search_emails":
                return FakeResult("Search Results:\n- message_id: m1")
            return FakeResult("Email Detail:\nBody: announcement from social school")

    fake_session = FakeSession()

    async def fake_collect(*args, **kwargs):
        return (
            {"search_emails": fake_session, "read_email": fake_session},
            {"search_emails": "gmail", "read_email": "gmail"},
            [
                {"type": "function", "function": {"name": "search_emails"}},
                {"type": "function", "function": {"name": "read_email"}},
            ],
            [],
        )

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "search_emails",
                                                "arguments": json.dumps({"query": "social school"}),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            if self._step == 2:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        "Let me read the most recent emails to provide you with a summary:"
                                    ),
                                    "tool_calls": [
                                        {
                                            "id": "call_2",
                                            "function": {
                                                "name": "read_email",
                                                "arguments": json.dumps({"message_id": "m1"}),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            return FakeResponse({"choices": [{"message": {"content": "Summary: social school updates."}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat("find recent emails from social school, summarize", [], "azure_ai/kimi-k2.5")
    )
    assert outputs[-1][-1]["content"] == "Summary: social school updates."
    assert fake_session.calls == [
        ("search_emails", {"query": "social school"}),
        ("read_email", {"message_id": "m1"}),
    ]
    assert metrics and metrics[0]["invoked_tools"] == ["search_emails", "read_email"]


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

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
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
                )
            return FakeResponse({"choices": [{"message": {"content": "Done"}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(chat_service.chat("cari alice", [], "deepseek-v3-2-251201"))
    assert outputs[-1][-1]["content"] == "Done"
    assert metrics and metrics[0]["status"] == "success_with_tool_errors"
    assert metrics[0]["tool_errors"]
    assert "search_contacts" in metrics[0]["tool_errors"][0]


@pytest.mark.asyncio
async def test_chat_gemini_stops_after_repeated_tool_failures(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [SimpleNamespace(text="Error: Drive API request failed: 403")]

    class FakeSession:
        async def call_tool(self, name, args):
            return FakeResult()

    async def fake_collect(*args, **kwargs):
        return (
            {"create_drive_shared_link_to_user": FakeSession()},
            {"create_drive_shared_link_to_user": "drive"},
            [],
            [],
        )

    class FakeAioClient:
        def __init__(self):
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def generate_content(self, **kwargs):
            return SimpleNamespace(
                function_calls=[
                    SimpleNamespace(
                        name="create_drive_shared_link_to_user",
                        args={"item_id": "x", "user_email": "u@example.com"},
                    )
                ],
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
                text=None,
            )

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = FakeAioClient()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "Client", FakeClient)
    metrics = []
    monkeypatch.setattr(chat_service, "log_metrics", lambda data: metrics.append(data))

    outputs = await _collect_stream(
        chat_service.chat(
            "share this book with user@example.com",
            [],
            "gemini-3-flash-preview",
        )
    )
    assert "Tool execution failed repeatedly" in outputs[-1][-1]["content"]
    assert metrics and metrics[0]["status"] == "error_tool_repeated_failures"


@pytest.mark.asyncio
async def test_chat_openai_share_tool_always_shows_url(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [
                SimpleNamespace(
                    text=(
                        "Drive shared link created for user:\n"
                        "Item: Book\n"
                        "Link: https://drive.google.com/file/d/abc/view"
                    )
                )
            ]

    class FakeSession:
        async def call_tool(self, name, args):
            return FakeResult()

    async def fake_collect(*args, **kwargs):
        return (
            {"create_drive_shared_link_to_user": FakeSession()},
            {"create_drive_shared_link_to_user": "drive"},
            [{"type": "function", "function": {"name": "create_drive_shared_link_to_user"}}],
            [],
        )

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self._step = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self._step += 1
            if self._step == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "create_drive_shared_link_to_user",
                                                "arguments": json.dumps(
                                                    {"item_id": "abc", "user_email": "u@example.com"}
                                                ),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            return FakeResponse({"choices": [{"message": {"content": "Shared successfully."}}]})

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", lambda: FakeClient())

    outputs = await _collect_stream(
        chat_service.chat(
            "share file with u@example.com",
            [],
            "deepseek-v3-2-251201",
        )
    )
    final_text = outputs[-1][-1]["content"]
    assert "Shared successfully." in final_text
    assert "Shared URL(s):" in final_text
    assert "https://drive.google.com/file/d/abc/view" in final_text


@pytest.mark.asyncio
async def test_chat_gemini_share_tool_always_shows_url(monkeypatch):
    class FakeResult:
        def __init__(self):
            self.content = [
                SimpleNamespace(
                    text=(
                        "Drive shared link created for user:\n"
                        "Item: Folder A\n"
                        "Link: https://drive.google.com/drive/folders/f123"
                    )
                )
            ]

    class FakeSession:
        async def call_tool(self, name, args):
            return FakeResult()

    async def fake_collect(*args, **kwargs):
        return (
            {"create_drive_shared_link_to_user": FakeSession()},
            {"create_drive_shared_link_to_user": "drive"},
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
                    function_calls=[
                        SimpleNamespace(
                            name="create_drive_shared_link_to_user",
                            args={"item_id": "f123", "user_email": "u@example.com"},
                        )
                    ],
                    candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
                    text=None,
                )
            return SimpleNamespace(function_calls=[], candidates=[], text="Done sharing.")

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = FakeAioClient()

    monkeypatch.setattr(chat_service, "_collect_mcp_tools", fake_collect)
    monkeypatch.setattr(chat_service.genai, "Client", FakeClient)

    outputs = await _collect_stream(
        chat_service.chat(
            "share folder with u@example.com",
            [],
            "gemini-3-flash-preview",
        )
    )
    final_text = outputs[-1][-1]["content"]
    assert "Done sharing." in final_text
    assert "Shared URL(s):" in final_text
    assert "https://drive.google.com/drive/folders/f123" in final_text
