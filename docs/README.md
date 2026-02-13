# Pseudocode Documentation

This folder contains implementation-level pseudocode for the chat application and all MCP servers/tools currently implemented in this repository.

## Files

- `docs/pseudocode-chat-app.md`
- `docs/pseudocode-mcp-gmail.md`
- `docs/pseudocode-mcp-calendar.md`
- `docs/pseudocode-mcp-contacts.md`
- `docs/pseudocode-mcp-drive.md`
- `docs/time-complexity-analysis.md`

## Scope

- Chat app bootstrap (`app.py`)
- Gradio UI flow (`src/chat_google/ui.py`)
- Chat orchestration and tool loop logic (`src/chat_google/chat_service.py`)
- MCP servers: `gmail`, `calendar`, `contacts`, `drive`
- All exposed MCP tools in each server
- Time complexity analysis + performance improvement proposals
