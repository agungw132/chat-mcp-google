# Pseudocode - MCP Calendar Server

Source: `src/chat_google/mcp_servers/calendar_server.py`

## 1) Server initialization

```text
LOAD .env
CREATE FastMCP server named "GoogleCalendar"
DEFINE pydantic input models for tool params
```

## 2) Core helpers

### `_get_credentials()`

```text
READ GOOGLE_ACCOUNT and GOOGLE_APP_KEY
IF missing -> raise ValueError
RETURN (email, app_key)
```

### `_get_calendar()`

```text
creds = _get_credentials()
dav_url = "https://calendar.google.com/calendar/dav/<email>/user"
client = caldav.DAVClient(dav_url, creds)
principal = client.principal()
calendars = principal.calendars()

IF no calendars: return None
TRY return calendar whose URL contains account email or "primary"
ELSE return first calendar
```

## 3) Tool pseudocode

## 3.1 `summarize_agenda(timeframe="24h", days=None)`

```text
VALIDATE timeframe in {"24h","today","yesterday","week","custom"}
VALIDATE days when provided (1..365)

calendar = _get_calendar()
IF no calendar: return "No calendars found."

now = current datetime
IF timeframe == "today":
    start = start-of-today
    end = start + 1 day
ELIF timeframe == "yesterday":
    end = start-of-today
    start = end - 1 day
ELIF timeframe == "week":
    start = now - 7 days
    end = now + 7 days
ELIF timeframe == "custom" and days provided:
    start = now
    end = now + days
ELSE:
    start = now - 24h
    end = now + 24h

events = calendar.search(start, end, event=True, expand=True)
IF no events: return "No events found ..."

FOR each event:
    read vevent fields: summary, dtstart, description
    skip if dtstart missing
    format line "- <time>: <summary>\n  Note: <description>"
    ignore parse failures per event

IF no parseable results: return "No parseable events ..."
RETURN header + sorted event lines
ON exception: return "Error fetching agenda for summary: ..."
```

## 3.2 `list_events(days=7)`

```text
VALIDATE days (1..365)
calendar = _get_calendar()
IF no calendar: return "No calendars found."

start = now - 1 day
end = now + days
events = calendar.search(start, end, event=True, expand=True)
IF no events: return "No events found ..."

FOR each event:
    extract summary + dtstart
    skip malformed events
    append "- <time>: <summary>"

IF no parseable results: return "No parseable events ..."
RETURN "Events (Next <days> days):\n..." sorted
ON exception: return "Error listing events: ..."
```

## 3.3 `add_event(summary, start_time, duration_minutes=60, description="")`

```text
VALIDATE summary, start_time, duration (1..1440), description
calendar = _get_calendar()
IF no calendar: return "No calendars found."

PARSE start_time using format "%Y-%m-%d %H:%M"
end_dt = start_dt + duration_minutes

calendar.add_event(
    summary=summary,
    dtstart=start_dt,
    dtend=end_dt,
    description=description
)

RETURN success message
ON exception: return "Error adding event: ..."
```

## 3.4 `search_events(query)`

```text
VALIDATE query non-empty
calendar = _get_calendar()
IF no calendar: return "No calendars found."

start = now - 30 days
end = start + 120 days
events = calendar.search(start, end, event=True, expand=True)

query_lower = query.lower()
FOR each event:
    extract summary + dtstart
    IF query_lower not in summary.lower(): skip
    append "- <dtstart>: <summary>"
    ignore parse failures per event

IF no matches: return "No events found matching '<query>'"
RETURN "Search results for '<query>':\n..." sorted
ON exception: return "Error searching events: ..."
```

## 4) Server runner

```text
def run():
    mcp.run()

if __name__ == "__main__":
    run()
```
