from datetime import datetime
from types import SimpleNamespace

import pytest

from chat_google.mcp_servers import calendar_server


def _event(summary: str, start, description: str = ""):
    vevent = SimpleNamespace(
        summary=SimpleNamespace(value=summary),
        dtstart=SimpleNamespace(value=start),
        description=SimpleNamespace(value=description),
    )
    return SimpleNamespace(vobject_instance=SimpleNamespace(vevent=vevent))


@pytest.mark.asyncio
async def test_summarize_agenda(monkeypatch):
    fake_calendar = SimpleNamespace(
        search=lambda **kwargs: [
            _event("Standup", datetime(2026, 1, 1, 9, 0), "Daily sync"),
        ]
    )
    monkeypatch.setattr(calendar_server, "_get_calendar", lambda: fake_calendar)
    result = await calendar_server.summarize_agenda(timeframe="today")
    assert "Agenda Summary for today" in result
    assert "Standup" in result
    assert "Daily sync" in result


@pytest.mark.asyncio
async def test_list_events(monkeypatch):
    fake_calendar = SimpleNamespace(
        search=lambda **kwargs: [
            _event("Planning", datetime(2026, 1, 2, 14, 30)),
            _event("Retro", datetime(2026, 1, 3, 16, 0)),
        ]
    )
    monkeypatch.setattr(calendar_server, "_get_calendar", lambda: fake_calendar)
    result = await calendar_server.list_events(days=7)
    assert "Events (Next 7 days)" in result
    assert "Planning" in result
    assert "Retro" in result


@pytest.mark.asyncio
async def test_add_event(monkeypatch):
    captured = {}

    class FakeCalendar:
        def add_event(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(calendar_server, "_get_calendar", lambda: FakeCalendar())
    result = await calendar_server.add_event(
        summary="Interview",
        start_time="2026-02-01 10:00",
        duration_minutes=45,
        description="Candidate call",
    )
    assert "Successfully added event" in result
    assert captured["summary"] == "Interview"
    assert captured["description"] == "Candidate call"
    assert (captured["dtend"] - captured["dtstart"]).seconds == 45 * 60


@pytest.mark.asyncio
async def test_search_events(monkeypatch):
    fake_calendar = SimpleNamespace(
        search=lambda **kwargs: [
            _event("Team Interview", datetime(2026, 1, 5, 11, 0)),
            _event("Budget Review", datetime(2026, 1, 5, 15, 0)),
        ]
    )
    monkeypatch.setattr(calendar_server, "_get_calendar", lambda: fake_calendar)
    result = await calendar_server.search_events("interview")
    assert "Search results for 'interview'" in result
    assert "Team Interview" in result
    assert "Budget Review" not in result


@pytest.mark.asyncio
async def test_tools_return_no_calendar(monkeypatch):
    monkeypatch.setattr(calendar_server, "_get_calendar", lambda: None)
    result_1 = await calendar_server.summarize_agenda()
    result_2 = await calendar_server.list_events()
    result_3 = await calendar_server.add_event("X", "2026-01-01 09:00")
    result_4 = await calendar_server.search_events("X")
    assert result_1 == "No calendars found."
    assert result_2 == "No calendars found."
    assert result_3 == "No calendars found."
    assert result_4 == "No calendars found."


@pytest.mark.asyncio
async def test_add_event_invalid_duration(monkeypatch):
    monkeypatch.setattr(
        calendar_server,
        "_get_calendar",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = await calendar_server.add_event(
        summary="Meeting",
        start_time="2026-02-01 10:00",
        duration_minutes=0,
        description="x",
    )
    assert result.startswith("Error adding event:")
    assert "greater than or equal to 1" in result
