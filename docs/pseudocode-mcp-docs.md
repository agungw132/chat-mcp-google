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
```

## 3) Auth and HTTP Helpers

```text
FUNCTION _get_access_token():
  READ GOOGLE_DRIVE_ACCESS_TOKEN
  IF empty:
    RAISE ValueError with guidance
  RETURN token

FUNCTION _auth_headers(token):
  RETURN {"Authorization": "Bearer <token>"}

FUNCTION _docs_get(path):
  GET DOCS_API_BASE + path with auth
  IF non-200: return docs-formatted error
  RETURN json payload

FUNCTION _docs_post(path, json_body):
  POST DOCS_API_BASE + path with auth
  IF non-200/201: return docs-formatted error
  RETURN json payload

FUNCTION _drive_get(path, params):
  GET DRIVE_API_BASE + path with auth
  IF non-200: return drive-formatted error
  RETURN json payload
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

## 6) Runtime Entry

```text
FUNCTION run():
  mcp.run()

IF __main__:
  run()
```
