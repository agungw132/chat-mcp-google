import os
from datetime import datetime, timedelta
from typing import Literal

import caldav
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("GoogleCalendar")


class _SummarizeAgendaInput(BaseModel):
    timeframe: Literal["24h", "today", "yesterday", "week", "custom"] = "24h"
    days: int | None = Field(default=None, ge=1, le=365, strict=True)


class _ListEventsInput(BaseModel):
    days: int = Field(default=7, ge=1, le=365, strict=True)


class _AddEventInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(min_length=1)
    start_time: str = Field(min_length=1)
    duration_minutes: int = Field(default=60, ge=1, le=1440, strict=True)
    description: str = Field(default="")


class _SearchEventsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)


def _get_credentials() -> tuple[str, str]:
    email_account = os.getenv("GOOGLE_ACCOUNT")
    app_password = os.getenv("GOOGLE_APP_KEY")
    if not email_account or not app_password:
        raise ValueError("GOOGLE_ACCOUNT and GOOGLE_APP_KEY must be set in .env")
    return email_account, app_password


def _get_calendar():
    email_account, app_password = _get_credentials()
    actual_url = f"https://calendar.google.com/calendar/dav/{email_account}/user"
    client = caldav.DAVClient(
        url=actual_url,
        username=email_account,
        password=app_password,
    )
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        return None

    for calendar in calendars:
        cal_url = str(calendar.url).lower()
        if email_account.lower() in cal_url or "primary" in cal_url:
            return calendar
    return calendars[0]


@mcp.tool()
async def summarize_agenda(timeframe: str = "24h", days: int = None) -> str:
    """
    Fetches events for a specific timeframe to be summarized by the AI.
    Args:
        timeframe: '24h', 'today', 'yesterday', 'week', or 'custom'.
        days: Number of days if timeframe is 'custom'.
    """
    try:
        params = _SummarizeAgendaInput.model_validate({"timeframe": timeframe, "days": days})
        timeframe = params.timeframe
        days = params.days

        calendar = _get_calendar()
        if not calendar:
            return "No calendars found."

        now = datetime.now()
        if timeframe == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif timeframe == "yesterday":
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(days=1)
        elif timeframe == "week":
            start = now - timedelta(days=7)
            end = now + timedelta(days=7)
        elif timeframe == "custom" and days:
            start = now
            end = now + timedelta(days=days)
        else:
            start = now - timedelta(hours=24)
            end = now + timedelta(hours=24)

        events = calendar.search(start=start, end=end, event=True, expand=True)
        if not events:
            return f"No events found for the timeframe: {timeframe}."

        results = []
        for event in events:
            try:
                ical = event.vobject_instance.vevent
                summary_obj = getattr(ical, "summary", None)
                summary = summary_obj.value if summary_obj else "No Title"

                dtstart_obj = getattr(ical, "dtstart", None)
                if not dtstart_obj:
                    continue
                dtstart = dtstart_obj.value

                description_obj = getattr(ical, "description", None)
                description = description_obj.value if description_obj else ""

                if isinstance(dtstart, datetime):
                    time_str = dtstart.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(dtstart)

                results.append(f"- {time_str}: {summary}\n  Note: {description}")
            except Exception:
                continue

        if not results:
            return f"No parseable events found for {timeframe}."

        header = (
            f"Agenda Summary for {timeframe} "
            f"(from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}):\n"
        )
        return header + "\n".join(sorted(results))
    except Exception as exc:
        return f"Error fetching agenda for summary: {str(exc)}"


@mcp.tool()
async def list_events(days: int = 7) -> str:
    """Lists calendar events for the next specified number of days."""
    try:
        params = _ListEventsInput.model_validate({"days": days})
        days = params.days

        calendar = _get_calendar()
        if not calendar:
            return "No calendars found."

        start = datetime.now() - timedelta(days=1)
        end = datetime.now() + timedelta(days=days)
        events = calendar.search(start=start, end=end, event=True, expand=True)
        if not events:
            return f"No events found for the next {days} days."

        results = []
        for event in events:
            try:
                ical = event.vobject_instance.vevent
                summary_obj = getattr(ical, "summary", None)
                summary = summary_obj.value if summary_obj else "No Title"

                dtstart_obj = getattr(ical, "dtstart", None)
                if not dtstart_obj:
                    continue
                dtstart = dtstart_obj.value

                if isinstance(dtstart, datetime):
                    time_str = dtstart.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(dtstart)

                results.append(f"- {time_str}: {summary}")
            except Exception:
                continue

        if not results:
            return f"No parseable events found for the next {days} days."

        return f"Events (Next {days} days):\n" + "\n".join(sorted(results))
    except Exception as exc:
        return f"Error listing events: {str(exc)}"


@mcp.tool()
async def add_event(
    summary: str,
    start_time: str,
    duration_minutes: int = 60,
    description: str = "",
) -> str:
    """
    Adds a new event to the calendar.
    Args:
        summary: Title of the event.
        start_time: Start time in 'YYYY-MM-DD HH:MM' format.
        duration_minutes: Duration in minutes (default 60).
        description: Optional description.
    """
    try:
        params = _AddEventInput.model_validate(
            {
                "summary": summary,
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "description": description,
            }
        )
        summary = params.summary
        start_time = params.start_time
        duration_minutes = params.duration_minutes
        description = params.description

        calendar = _get_calendar()
        if not calendar:
            return "No calendars found."

        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        calendar.add_event(
            summary=summary,
            dtstart=start_dt,
            dtend=end_dt,
            description=description,
        )
        return f"Successfully added event: '{summary}' on {start_time}"
    except Exception as exc:
        return f"Error adding event: {str(exc)}"


@mcp.tool()
async def search_events(query: str) -> str:
    """Searches for events matching a keyword in the summary."""
    try:
        params = _SearchEventsInput.model_validate({"query": query})
        query = params.query

        calendar = _get_calendar()
        if not calendar:
            return "No calendars found."

        start = datetime.now() - timedelta(days=30)
        end = start + timedelta(days=120)
        events = calendar.search(start=start, end=end, event=True, expand=True)

        query_lower = query.lower()
        results = []
        for event in events:
            try:
                ical = event.vobject_instance.vevent
                summary_obj = getattr(ical, "summary", None)
                summary = summary_obj.value if summary_obj else "No Title"
                if query_lower not in summary.lower():
                    continue
                dtstart_obj = getattr(ical, "dtstart", None)
                dtstart = dtstart_obj.value if dtstart_obj else "Unknown Date"
                results.append(f"- {dtstart}: {summary}")
            except Exception:
                continue

        if not results:
            return f"No events found matching '{query}'"
        return f"Search results for '{query}':\n" + "\n".join(sorted(results))
    except Exception as exc:
        return f"Error searching events: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
