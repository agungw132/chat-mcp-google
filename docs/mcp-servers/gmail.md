# Gmail MCP Server

Source:

- `src/chat_google/mcp_servers/gmail_server.py`
- wrapper: `gmail_server.py`
- FastMCP server name: `Gmail`

## Purpose

Use this server for mailbox retrieval, mailbox search, and outbound email/invitation sending.

## Required configuration

- `GOOGLE_ACCOUNT`
- `GOOGLE_APP_KEY`

Transport:

- IMAP (`imap.gmail.com`) for read/search actions
- SMTP (`smtp.gmail.com:465`) for send actions

## Tool catalog

- `list_recent_emails(count=5)`
- `read_email(email_id)`
- `summarize_emails(timeframe='24h', label='inbox', count=10)`
- `list_unread_emails(count=5)`
- `mark_as_read(email_id)`
- `list_labels()`
- `search_emails_by_label(label, count=5)`
- `search_emails(query)`
- `send_email(to_email, subject, body)`
- `send_calendar_invite_email(to_email, subject, body, summary, start_time, duration_minutes=60, description='', location='')`

## Calling guidance

Read-first tasks:

- Inbox overview -> `list_recent_emails`
- Drill down message content -> `read_email`
- Focused mailbox search -> `search_emails` or `search_emails_by_label`
- Human summary input data -> `summarize_emails`

Write tasks:

- Plain email -> `send_email`
- Calendar invite with accept/reject capability -> `send_calendar_invite_email`

## Output semantics

- Returns human-readable plain text.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.
- List/search tools return line-based entries with IDs/subjects/senders.
- Send tools return success sentence or `Error ...`.
- Invite tool embeds ICS calendar payload in outgoing email.

## Error semantics

- Errors are string-based (for example `Error sending email: ...`).
- Common causes:
- invalid app password
- missing env credentials
- inaccessible/invalid label
- mailbox message ID not found

## Orchestration patterns

Pattern: Event + invite (when calendar server lacks attendee fields)

1. Create event via `calendar.add_event`.
2. Send invitation via `send_calendar_invite_email`.
3. If invite fails, fallback to `send_email` plain text.

Pattern: Contact-driven outbound message

1. Resolve contact email via `contacts.search_contacts`.
2. Send content via `send_email`.

## Constraints

- `start_time` for invite must match `YYYY-MM-DD HH:MM`.
- `to_email` and `subject` are validated.
- Max list counts are bounded by tool input validation.
