# Drive MCP Server

Source:

- `src/chat_google/mcp_servers/drive_server.py`
- wrapper: `drive_server.py`
- FastMCP server name: `GoogleDrive`

## Purpose

Use this server for Google Drive search, metadata, text file read/upload, folder operations, move operations, and sharing link operations.

## Authentication and credential modes

Mode A (minimal):

- `GOOGLE_DRIVE_ACCESS_TOKEN`

Mode B (recommended, long-lived):

- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

Behavior:

- If refresh config is complete, server refreshes access token automatically.
- If refresh fails and static access token exists, server falls back to static token.
- If no valid token path exists, tools return auth-related errors.

## Tool catalog

- `list_drive_files(limit=10, folder_id=None, mime_type=None)`
- `search_drive_files(query, limit=10, folder_id=None)`
- `get_drive_file_metadata(file_id)`
- `read_drive_text_file(file_id, max_chars=8000)`
- `list_shared_with_me(limit=10)`
- `create_drive_folder(name, parent_id=None)`
- `upload_text_file(name, content, parent_id=None)`
- `move_drive_file(file_id, new_parent_id)`
- `create_drive_shared_link_to_user(item_id, user_email, role='reader', send_notification=True, message='', expires_in_days=7)`
- `create_drive_public_link(item_id, role='reader', allow_discovery=False)`

## Calling guidance

Discovery:

- generic recent files -> `list_drive_files`
- name-based lookup -> `search_drive_files`
- deep inspection -> `get_drive_file_metadata`

Read/write:

- read text content -> `read_drive_text_file`
- create folder -> `create_drive_folder`
- upload plain text -> `upload_text_file`
- move item -> `move_drive_file`

Sharing:

- private user share with role -> `create_drive_shared_link_to_user`
- public link (anyone) -> `create_drive_public_link`

## Output semantics

- Plain text responses with key fields and links.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.
- Sharing tools include generated `webViewLink`.
- `create_drive_shared_link_to_user` may include note when expiration is unsupported and fallback is applied.

## Error semantics

- Standardized Drive errors:
- `Error: Drive API request failed: <status> ...`
- Includes permission/scope hint for common 403 cases.

Typical causes:

- invalid/expired token
- insufficient scope
- file permission mismatch
- unsupported file type for `read_drive_text_file`

## Constraints and limits

- `read_drive_text_file` supports non-Google-Workspace text-like MIME types.
- Google Docs/Sheets/Slides are intentionally out-of-scope for this MCP.
- Share role allowed values:
- `reader`
- `commenter`
- `writer`

## Recommended patterns

Find then share:

1. `search_drive_files(query=...)`
2. choose file ID
3. `create_drive_shared_link_to_user(...)` or `create_drive_public_link(...)`

Read then summarize:

1. `read_drive_text_file(file_id=...)`
2. pass content to model summarization response step
