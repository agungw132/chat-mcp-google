# Docs MCP Server

Source:

- `src/chat_google/mcp_servers/docs_server.py`
- wrapper: `docs_server.py`
- FastMCP server name: `GoogleDocs`

## Purpose

Use this server for Google Docs document discovery, template discovery, metadata retrieval, content read, creation, text editing, sharing, export, revision-safe updates, and Word file interoperability (`.docx/.doc`).

## Required configuration

- `GOOGLE_DRIVE_ACCESS_TOKEN`

Optional long-lived auth (recommended):

- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

When all three are set, Docs MCP auto-refreshes access tokens and avoids short-lived token failures.

Required Google API enablement:

- Google Docs API
- Google Drive API (used for listing/search metadata and links)

## Tool catalog

- `list_docs_documents(limit=10)`
- `search_docs_documents(query, limit=10)`
- `get_docs_document_metadata(document_id)`
- `read_docs_document(document_id, max_chars=8000)`
- `create_docs_document(title, initial_content='')`
- `append_docs_text(document_id, text)`
- `replace_docs_text(document_id, find_text, replace_text='', match_case=False)`
- `share_docs_to_user(document_id, user_email, role='reader', send_notification=True, message='')`
- `export_docs_document(document_id, export_format='pdf', max_chars=8000)` where `export_format` is one of `txt|html|pdf|docx`
- `append_docs_structured_content(document_id, heading='', paragraph='', bullet_items=[], numbered_items=[])`
- `replace_docs_text_if_revision(document_id, expected_revision_id, find_text, replace_text='', match_case=False)`
- `list_documents(limit=10, include_word=True)` (native Docs + optional `.docx/.doc`)
- `list_document_templates(limit=10, folder_name='Documents', name_contains='template', include_word=True)` (template candidates in target folder)
- `search_documents(query, limit=10, include_word=True)` (native Docs + optional `.docx/.doc`)
- `get_document_metadata(file_id)` (native Docs and Word files)
- `read_word_document(file_id, max_chars=8000)` (direct `.docx` read)
- `convert_word_to_google_doc(file_id, new_title='', move_to_parent=True)` (`.docx/.doc` -> native Docs)

## Calling guidance

Discovery:

- recent docs overview -> `list_docs_documents`
- title-based lookup -> `search_docs_documents`
- mixed docs/word discovery -> `list_documents` / `search_documents`
- template lookup in a folder (default `Documents`) -> `list_document_templates`

Read:

- metadata and owner/link details -> `get_docs_document_metadata`
- plain text extraction -> `read_docs_document`
- unified metadata by file id -> `get_document_metadata`
- direct `.docx` text read -> `read_word_document`

Write:

- create document -> `create_docs_document`
- append additional section text -> `append_docs_text`
- targeted find/replace update -> `replace_docs_text`
- append heading/paragraph/list block -> `append_docs_structured_content`
- revision-safe replace -> `replace_docs_text_if_revision`

Collaboration:

- share to user with role + notification -> `share_docs_to_user`

Export:

- export doc as txt/html/pdf/docx -> `export_docs_document`

Word conversion:

- convert `.docx/.doc` to native Docs -> `convert_word_to_google_doc`

## Output semantics

- Server returns plain text summaries and action results.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.
- Most write tools include a direct Google Docs link.

## Error semantics

- Docs API errors are normalized as:
- `Error: Google Docs API request failed: <status> ...`
- Drive API errors are normalized as:
- `Error: Drive API request failed: <status> ...`

Typical causes:

- missing/expired token
- Docs API not enabled in GCP project
- insufficient OAuth scope for Docs/Drive
- document permission mismatch

## Constraints and limits

- `max_chars` in `read_docs_document` is validated and truncated with `[Truncated]` marker.
- `max_chars` in `export_docs_document` is used when returning textual formats (`txt`, `html`) to avoid oversized chat payloads.
- Text append uses the last document insertion index available from Docs structure.
- `replace_docs_text` reports `Occurrences Changed` based on Docs `replaceAllText` response.
- `replace_docs_text_if_revision` performs optimistic concurrency guard by comparing current revision before update.
- `share_docs_to_user` accepts roles: `reader`, `commenter`, `writer`.
- `read_word_document` supports `.docx` only; `.doc` must be converted first.
- `convert_word_to_google_doc` supports Word input types `.docx` and `.doc`.
- `list_document_templates` defaults to `name_contains='template'`; set `name_contains=''` to list all document candidates in the target folder.

## Recommended patterns

Create and populate:

1. `create_docs_document(title, initial_content=...)`
2. `append_docs_text(document_id, text=...)`

Find and update:

1. `search_docs_documents(query=...)`
2. `get_docs_document_metadata(document_id=...)` to get revision
3. `replace_docs_text_if_revision(document_id, expected_revision_id=..., find_text=..., replace_text=...)`

Read and summarize:

1. `read_docs_document(document_id=...)`
2. pass output to model summarization response step

Word file workflow:

1. `search_documents(query=..., include_word=True)`
2. `get_document_metadata(file_id=...)`
3. `.docx`:
4. `read_word_document(file_id=...)`
5. optional: `convert_word_to_google_doc(file_id=...)` then use native Docs tools
6. `.doc`:
7. `convert_word_to_google_doc(file_id=...)` first, then use native Docs tools

Collaborative handoff:

1. `share_docs_to_user(document_id, user_email, role='commenter')`
2. provide returned `Link` in assistant response
