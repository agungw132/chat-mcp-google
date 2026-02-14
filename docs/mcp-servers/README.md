# MCP Server READMEs (Agent-Oriented)

These documents are written for a calling/orchestrating agent (for example `chat_service` behind `app.py`) so tool selection and execution are predictable.

## Files

- `docs/mcp-servers/gmail.md`
- `docs/mcp-servers/calendar.md`
- `docs/mcp-servers/contacts.md`
- `docs/mcp-servers/drive.md`
- `docs/mcp-servers/docs.md`
- `docs/mcp-servers/maps.md`

## How to use this set

1. Pick the server based on user intent domain.
2. Choose the narrowest tool that satisfies the request.
3. Respect tool limits and input contracts.
4. Prefer structured output if provided (`success`, `error`, `data`); otherwise fallback to plain-text parsing.
5. For orchestration inside this repository, these docs are summarized and injected into model system prompts at runtime.
6. If a tool call fails, use `error.code`/`error.message` when available; otherwise fallback to plain `Error:` text handling.

## Cross-server orchestration quick map

- Email retrieval/sending -> `gmail`
- Event listing/creation -> `calendar`
- Contact lookup -> `contacts`
- File/storage/sharing -> `drive`
- Document authoring/editing -> `docs`
- Address/place/directions -> `maps`

Common multi-server patterns:

- Create event + invite participant:
- `calendar.add_event` -> `gmail.send_calendar_invite_email`
- Find contact then send message:
- `contacts.search_contacts` -> `gmail.send_email`
- Share Drive file with user:
- `drive.search_drive_files` -> `drive.create_drive_shared_link_to_user`
- Create and refine Google Doc:
- `docs.create_docs_document` -> `docs.append_docs_text` -> `docs.replace_docs_text`
- Find place then route:
- `maps.search_places_text` -> `maps.get_place_details` -> `maps.get_directions`
