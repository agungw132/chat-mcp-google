# Slides MCP Server

Source:

- `src/chat_google/mcp_servers/slides_server.py`
- wrapper: `slides_server.py`
- FastMCP server name: `GoogleSlides`

## Purpose

Use this server for Google Slides presentation discovery, template discovery, metadata retrieval, content read, presentation creation, slide insertion, sharing, export, and PowerPoint interoperability (`.pptx/.ppt`).

## Required configuration

- `GOOGLE_DRIVE_ACCESS_TOKEN`

Optional long-lived auth (recommended):

- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

When all three are set, Slides MCP auto-refreshes access tokens and avoids short-lived token failures.

Required Google API enablement:

- Google Slides API
- Google Drive API (used for file discovery/metadata, sharing, export, and conversion)

## Tool catalog

- `list_slides_presentations(limit=10)`
- `search_slides_presentations(query, limit=10)`
- `get_slides_presentation_metadata(presentation_id)`
- `read_slides_presentation(presentation_id, max_chars=8000)`
- `create_slides_presentation(title, initial_slide_title='')`
- `add_text_slide(presentation_id, title, body='')`
- `list_presentations(limit=10, include_powerpoint=True)` (native Slides + optional `.pptx/.ppt`)
- `list_presentation_templates(limit=10, folder_name='Documents', name_contains='template', include_powerpoint=True)` (template candidates in target folder)
- `search_presentations(query, limit=10, include_powerpoint=True)` (native Slides + optional `.pptx/.ppt`)
- `get_presentation_metadata(file_id)` (native Slides and PowerPoint files)
- `read_powerpoint_document(file_id, max_chars=8000)` (direct `.pptx` read)
- `convert_powerpoint_to_google_slides(file_id, new_title='', move_to_parent=True)` (`.pptx/.ppt` -> native Slides)
- `share_presentation_to_user(presentation_id, user_email, role='reader', send_notification=True, message='')`
- `export_slides_presentation(presentation_id, export_format='pdf', max_chars=8000)` (`pdf`, `pptx`, `txt`)

## Calling guidance

Discovery:

- recent native slides overview -> `list_slides_presentations`
- title-based native slides lookup -> `search_slides_presentations`
- mixed slides + PowerPoint inventory -> `list_presentations` / `search_presentations`
- template lookup in a folder (default `Documents`) -> `list_presentation_templates`

Read:

- native slide metadata -> `get_slides_presentation_metadata`
- native slide text extraction -> `read_slides_presentation`
- unified metadata for native/PowerPoint files -> `get_presentation_metadata`
- direct `.pptx` text read -> `read_powerpoint_document`

Write:

- create presentation -> `create_slides_presentation`
- add textual content slide -> `add_text_slide`
- convert `.pptx/.ppt` to native Slides -> `convert_powerpoint_to_google_slides`

Collaboration:

- share presentation access to one user -> `share_presentation_to_user`

Export:

- export native Slides to `pdf` / `pptx` / `txt` -> `export_slides_presentation`

## Output semantics

- Server returns plain text summaries and action results.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding model context.
- Write/share tools include direct file links when possible.

## Error semantics

- Slides API errors are normalized as:
- `Error: Google Slides API request failed: <status> ...`
- Drive API errors are normalized as:
- `Error: Drive API request failed: <status> ...`

Typical causes:

- missing/expired OAuth token
- Slides API not enabled in GCP project
- insufficient OAuth scope for Slides/Drive
- presentation permission mismatch

## Constraints and limits

- `read_slides_presentation` caps text output with `max_chars`.
- `read_powerpoint_document` supports direct read for `.pptx`; legacy `.ppt` must be converted first.
- `share_presentation_to_user` roles are limited to `reader`, `commenter`, `writer`.
- `export_slides_presentation` only exports native Google Slides input files.
- `convert_powerpoint_to_google_slides` supports `.pptx` and `.ppt`.
- `list_presentation_templates` defaults to `name_contains='template'`; set `name_contains=''` to list all presentation candidates in the target folder.

## Recommended patterns

Create and enrich:

1. `create_slides_presentation(title, initial_slide_title=...)`
2. `add_text_slide(presentation_id=..., title=..., body=...)`

PowerPoint workflow:

1. `search_presentations(query=..., include_powerpoint=True)`
2. `get_presentation_metadata(file_id=...)`
3. `.pptx`: `read_powerpoint_document(file_id=...)`
4. optional conversion to native Slides: `convert_powerpoint_to_google_slides(file_id=...)`
5. `.ppt`: convert first, then use native Slides tools

Share workflow:

1. `search_presentations(query=..., include_powerpoint=True)` or `list_presentations(...)`
2. `share_presentation_to_user(presentation_id=..., user_email=..., role='reader')`
