# Pseudocode - MCP Google Docs

Source implementation:
- `src/chat_google/mcp_servers/docs_server.py`

Wrapper entrypoint:
- `docs_server.py`

## 1) Bootstrap

```text
LOAD .env
CREATE FastMCP server named "GoogleDocs"
DEFINE API bases:
  DOCS_API_BASE = https://docs.googleapis.com/v1
  DRIVE_API_BASE = https://www.googleapis.com/drive/v3
  OAUTH_TOKEN_ENDPOINT = https://oauth2.googleapis.com/token
DEFINE token cache with expiry
```

## 2) Input Schemas

```text
List:
  limit (1..100)

Search:
  query (non-empty), limit (1..100)

Document ID operations:
  document_id (non-empty)

Read:
  document_id, max_chars (200..50000)

Create:
  title (non-empty), initial_content (optional)

Append:
  document_id, text (non-empty)

Replace:
  document_id, find_text (non-empty), replace_text (optional), match_case (bool)

Share:
  document_id, user_email, role(reader|commenter|writer),
  send_notification(bool), message(optional)

Export:
  document_id, export_format(txt|html|pdf|docx), max_chars (for text formats)

Structured append:
  document_id,
  heading(optional), paragraph(optional),
  bullet_items(list), numbered_items(list),
  at least one field must be non-empty

Safe replace:
  document_id, expected_revision_id, find_text, replace_text, match_case
```

## 3) Auth and HTTP Helpers

```text
FUNCTION _get_access_token():
  RELOAD .env (override enabled)
  IF cached token exists and not expired:
    RETURN cached token

  READ static token + refresh config:
    GOOGLE_DRIVE_ACCESS_TOKEN
    GOOGLE_DRIVE_REFRESH_TOKEN
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET

  IF full refresh config exists:
    REFRESH token via OAuth token endpoint
    CACHE token with safety margin
    WRITE token to process env
    RETURN refreshed token

  IF partial refresh config exists and no static token:
    RAISE ValueError with missing keys

  IF static token exists:
    RETURN static token

  RAISE ValueError with setup guidance

FUNCTION _auth_headers(token):
  RETURN {"Authorization": "Bearer <token>"}

FUNCTION _docs_get(path):
  GET DOCS_API_BASE + path with auth
  IF 401:
    invalidate cache
    retry once with refreshed/reloaded token
  IF non-200: return docs-formatted error
  RETURN json payload

FUNCTION _docs_post(path, json_body):
  POST DOCS_API_BASE + path with auth
  IF 401:
    invalidate cache
    retry once with refreshed/reloaded token
  IF non-200/201: return docs-formatted error
  RETURN json payload

FUNCTION _drive_get(path, params):
  GET DRIVE_API_BASE + path with auth
  IF 401:
    invalidate cache
    retry once with refreshed/reloaded token
  IF non-200: return drive-formatted error
  RETURN json payload

FUNCTION _drive_post_json(path, params, body):
  POST DRIVE_API_BASE + path with auth (same 401 retry rule)
  RETURN json payload

FUNCTION _drive_get_bytes(path, params):
  GET DRIVE_API_BASE + path with auth (same 401 retry rule)
  RETURN response bytes
```

## 4) Parsing Utilities

```text
FUNCTION _extract_document_text(document):
  WALK document.body.content[]
  FOR each paragraph element textRun.content:
    APPEND text
  RETURN merged plain text (trimmed)

FUNCTION _document_insert_index(document):
  GET endIndex from last body.content element
  RETURN max(1, endIndex - 1)

FUNCTION _build_structured_append_text(input):
  compose text block:
    heading
    paragraph
    bullet list lines prefixed "- "
    numbered list lines prefixed "1.", "2.", ...
  RETURN "\n\n" + composed block
```

## 5) Tool Flows

## 5.1 list_docs_documents(limit=10)

```text
VALIDATE input
QUERY Drive files where:
  mimeType == Google Docs
  trashed == false
ORDER by modifiedTime desc
FORMAT each file line (name, id, modified, link)
RETURN list text or "No Google Docs documents found."
```

## 5.2 search_docs_documents(query, limit=10)

```text
VALIDATE input
ESCAPE query
QUERY Drive files where:
  mimeType == Google Docs
  trashed == false
  name contains query
FORMAT results
RETURN search summary text
```

## 5.3 get_docs_document_metadata(document_id)

```text
VALIDATE input
GET document via Docs API (/documents/{id})
GET file metadata via Drive API (/files/{id})
FORMAT title, documentId, revisionId, modified time, owners, link
RETURN metadata text
```

## 5.4 read_docs_document(document_id, max_chars=8000)

```text
VALIDATE input
GET document via Docs API
EXTRACT plain text from body content
IF empty:
  RETURN "<title> is empty"
IF len(text) > max_chars:
  TRUNCATE and append "[Truncated]"
RETURN content block
```

## 5.5 create_docs_document(title, initial_content='')

```text
VALIDATE input
POST /documents with title
IF initial_content non-empty:
  POST /documents/{id}:batchUpdate with insertText at index 1
RETURN title, document id, revision id, docs link
```

## 5.6 append_docs_text(document_id, text)

```text
VALIDATE input
GET document structure
COMPUTE insert index with _document_insert_index
POST /documents/{id}:batchUpdate with insertText at computed index
RETURN success text with index and link
```

## 5.7 replace_docs_text(document_id, find_text, replace_text='', match_case=False)

```text
VALIDATE input
POST /documents/{id}:batchUpdate with replaceAllText request
READ replies[0].replaceAllText.occurrencesChanged
RETURN replacement summary + occurrences + link
```

## 5.8 share_docs_to_user(document_id, user_email, role='reader', send_notification=True, message='')

```text
VALIDATE input
VALIDATE role in {reader, commenter, writer}
POST /files/{document_id}/permissions (Drive API)
  body: type=user, role, emailAddress
  query: supportsAllDrives + notification options
GET /files/{document_id} for name + webViewLink
RETURN sharing summary + permission id + link
```

## 5.9 export_docs_document(document_id, export_format='pdf', max_chars=8000)

```text
VALIDATE input
MAP export_format -> mimeType
GET /files/{document_id}/export (Drive API) as bytes
GET /files/{document_id} for metadata
IF format is txt/html:
  decode UTF-8 (replace errors)
  truncate to max_chars + [Truncated]
  RETURN textual export content
ELSE (pdf/docx):
  RETURN binary export metadata (size, format, link)
```

## 5.10 append_docs_structured_content(document_id, heading='', paragraph='', bullet_items=[], numbered_items=[])

```text
VALIDATE input (at least one content field required)
GET /documents/{document_id}
COMPUTE insert index
BUILD structured text block from heading/paragraph/lists
POST /documents/{id}:batchUpdate with insertText
RETURN index + chars added + link
```

## 5.11 replace_docs_text_if_revision(document_id, expected_revision_id, find_text, replace_text='', match_case=False)

```text
VALIDATE input
GET /documents/{document_id}
READ current revisionId
IF current != expected:
  RETURN "Revision mismatch. No changes applied."
POST /documents/{id}:batchUpdate with replaceAllText
RETURN safe replacement summary + occurrences + link
```

## 6) Runtime Entry

```text
FUNCTION run():
  mcp.run()

IF __main__:
  run()
```
