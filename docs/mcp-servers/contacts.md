# Contacts MCP Server

Source:

- `src/chat_google/mcp_servers/contacts_server.py`
- wrapper: `contacts_server.py`
- FastMCP server name: `GoogleContacts`

## Purpose

Use this server to resolve people identities (name/email/phone) from Google Contacts through CardDAV.

## Required configuration

- `GOOGLE_ACCOUNT`
- `GOOGLE_APP_KEY`

## Tool catalog

- `list_contacts(limit=10)`
- `search_contacts(query)`

## Calling guidance

Use `list_contacts` when:

- User asks for generic contact overview.
- You need a shortlist for follow-up disambiguation.

Use `search_contacts` when:

- User provides name fragment.
- You need best-match email/phone for downstream tools.

## Output semantics

- `list_contacts` returns compact lines: `name: email`.
- `search_contacts` returns richer blocks: `Name`, `Email`, `Phone`.
- No structured JSON contract; output is plain text.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.

## Error semantics

- Errors are string-based.
- Server attempts resilient search:
- tries CardDAV `REPORT` first
- falls back to `PROPFIND` + local filtering when needed

## Reliability notes for calling agents

- Search can be slower on large contact sets.
- Prefer narrow query terms for better latency.
- If no match returned, request clarification from user or fallback to manual email entry.

## Recommended downstream patterns

- Invite flow:
- `search_contacts` -> extract email -> `gmail.send_calendar_invite_email`
- Message flow:
- `search_contacts` -> extract email -> `gmail.send_email`
