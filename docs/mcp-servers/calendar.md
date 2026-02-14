# Calendar MCP Server

Source:

- `src/chat_google/mcp_servers/calendar_server.py`
- wrapper: `calendar_server.py`
- FastMCP server name: `GoogleCalendar`

## Purpose

Use this server for listing/searching agenda and creating basic calendar events through CalDAV.

## Required configuration

- `GOOGLE_ACCOUNT`
- `GOOGLE_APP_KEY`

## Tool catalog

- `summarize_agenda(timeframe='24h', days=None)`
- `list_events(days=7)`
- `add_event(summary, start_time, duration_minutes=60, description='')`
- `search_events(query)`

## Calling guidance

Agenda view:

- Recent/today/week context -> `summarize_agenda`
- Forward-looking event list -> `list_events`

Event creation:

- Use `add_event` for simple events only.
- Put extra context (location, invitee notes) in `description`.

Search:

- Title/keyword lookup -> `search_events`

## Output semantics

- Returns plain text blocks with event timestamps and summaries.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.
- `add_event` returns explicit success/failure sentence.
- `summarize_agenda` includes timeframe header and item notes.

## Error semantics

- Errors are string-based (`Error ...`).
- Typical causes:
- credentials missing/invalid
- no calendar found
- invalid datetime format

## Important limitations for calling agents

- `add_event` supports only:
- `summary`
- `start_time`
- `duration_minutes`
- `description`
- No structured attendee field.
- No structured location field.

Recommended workaround:

1. Place participant/location info in `description`.
2. Send participant invite via `gmail.send_calendar_invite_email`.

## Time parsing expectations

- `start_time` format is strict: `YYYY-MM-DD HH:MM`.
- Relative dates should be normalized before call (handled by orchestration layer in `chat_service`).
