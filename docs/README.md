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
- `docs/mcp-server-addition-runbook.md`
- `docs/mcp-server-addition-checklist.md`
- `docs/mcp-servers/README.md`
- `docs/mcp-servers/gmail.md`
- `docs/mcp-servers/calendar.md`
- `docs/mcp-servers/contacts.md`
- `docs/mcp-servers/drive.md`
- `docs/mcp-servers/maps.md`

## Scope

- Chat app bootstrap (`app.py`)
- Gradio UI flow (`src/chat_google/ui.py`)
- Chat orchestration and tool loop logic (`src/chat_google/chat_service.py`)
- Runtime MCP policy loading from `docs/mcp-servers/*.md` into system instructions
- Intent-based server/tool gating before model tool-calling
- Structured tool-result contract (`success/error/data`) passed back to models
- MCP servers: `gmail`, `calendar`, `contacts`, `drive`, `maps`
- All exposed MCP tools in each server
- Time complexity analysis + performance improvement proposals
- Standard operating procedure for adding a new MCP server: `docs/mcp-server-addition-runbook.md`
- Quick execution checklist for adding a new MCP server: `docs/mcp-server-addition-checklist.md`
- Programmatic key setup scripts: `get_google_drive_access_token.py`, `get_google_maps_api_key.py`, `get_google_app_key.py` (manual-only helper guidance)
- Agent-oriented MCP usage guides per server: `docs/mcp-servers/*.md`

## Related Setup Docs

- Primary operational setup guide: `README.md`
- Drive OAuth credential guides in `README.md`:
  - `How to Get GOOGLE_DRIVE_ACCESS_TOKEN (Individual Account)`
  - `How to Get GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET`
- Maps API key guide in `README.md`:
  - `How to Get GOOGLE_MAPS_API_KEY and Required APIs`
