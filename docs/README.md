# Pseudocode Documentation

This folder contains implementation-level pseudocode for the chat application and all MCP servers/tools currently implemented in this repository.

## Files

- `docs/pseudocode-chat-app.md`
- `docs/pseudocode-mcp-gmail.md`
- `docs/pseudocode-mcp-calendar.md`
- `docs/pseudocode-mcp-contacts.md`
- `docs/pseudocode-mcp-drive.md`
- `docs/pseudocode-mcp-maps.md`
- `docs/time-complexity-analysis.md`

## Scope

- Chat app bootstrap (`app.py`)
- Gradio UI flow (`src/chat_google/ui.py`)
- Chat orchestration and tool loop logic (`src/chat_google/chat_service.py`)
- MCP servers: `gmail`, `calendar`, `contacts`, `drive`, `maps`
- All exposed MCP tools in each server
- Time complexity analysis + performance improvement proposals
- Programmatic key setup scripts: `get_google_drive_access_token.py`, `get_google_maps_api_key.py`, `get_google_app_key.py` (manual-only helper guidance)

## Related Setup Docs

- Primary operational setup guide: `README.md`
- Drive OAuth credential guide:
- `How to Get GOOGLE_DRIVE_ACCESS_TOKEN (Individual Account)`
- `How to Get GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET`
- Maps API key guide:
- `How to Get GOOGLE_MAPS_API_KEY and Required APIs`
