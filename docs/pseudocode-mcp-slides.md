# Pseudocode - MCP Google Slides

Source implementation:
- `src/chat_google/mcp_servers/slides_server.py`

Wrapper entrypoint:
- `slides_server.py`

## 1) Bootstrap

```text
LOAD .env
CREATE FastMCP server named "GoogleSlides"
DEFINE API bases:
  SLIDES_API_BASE = https://slides.googleapis.com/v1
  DRIVE_API_BASE = https://www.googleapis.com/drive/v3
  OAUTH_TOKEN_ENDPOINT = https://oauth2.googleapis.com/token
```

## 2) Input Schemas

```text
List/Search:
  limit (1..100), query non-empty

Native Slides:
  presentation_id non-empty
  max_chars for read (200..50000)

Create/Add slide:
  title non-empty
  body optional

Unified presentation tools:
  list/search with include_powerpoint flag
  metadata by file_id for native Slides or .pptx/.ppt
  list_presentation_templates(limit, folder_name, name_contains, include_powerpoint)

PowerPoint tools:
  read_powerpoint_document(file_id, max_chars)
  convert_powerpoint_to_google_slides(file_id, new_title, move_to_parent)

Sharing:
  role in {reader, commenter, writer}
  user_email validation

Export:
  export_format in {pdf, pptx, txt}
```

## 3) Auth and HTTP Helpers

```text
FUNCTION _get_access_token():
  RELOAD .env (override enabled)
  IF cached token exists and valid: return cached

  READ static + refresh config:
    GOOGLE_DRIVE_ACCESS_TOKEN
    GOOGLE_DRIVE_REFRESH_TOKEN
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET

  IF refresh config complete:
    REFRESH token via OAuth endpoint
    CACHE token with expiry margin
    STORE refreshed token in process env
    RETURN refreshed token

  IF static token exists: return static token
  ELSE raise ValueError with setup guidance

FUNCTION _slides_get/_slides_post:
  SEND request with bearer token
  IF 401:
    invalidate cache
    retry once with refreshed/reloaded token
  IF non-success:
    return normalized Slides error
  RETURN JSON payload

FUNCTION _drive_get/_drive_post_json/_drive_get_bytes:
  same retry/auth logic, with normalized Drive errors

FUNCTION _drive_upload_multipart:
  upload media bytes as multipart for conversion fallback path
```

## 4) Utility Helpers

```text
_presentation_query(include_powerpoint):
  include native Slides only
  or native + .pptx + .ppt

_presentation_type_label:
  normalize mime -> google_slides / powerpoint_pptx / powerpoint_ppt

_extract_slide_text:
  walk slide.pageElements -> shape.text.textElements -> textRun.content

_extract_presentation_text:
  for each slide with text:
    emit block "[Slide N]\n..."

_extract_pptx_text(payload):
  unzip pptx
  read ppt/slides/slideN.xml
  parse XML <a:t> nodes
  return slide_count + joined blocks
```

## 5) Tool Flows

## 5.1 list_slides_presentations(limit=10)

```text
QUERY Drive files with mimeType=google-apps.presentation
ORDER by modifiedTime desc
FORMAT output lines
RETURN summary
```

## 5.2 search_slides_presentations(query, limit=10)

```text
BUILD Drive query with native Slides mime + name contains query
RETURN formatted results
```

## 5.3 get_slides_presentation_metadata(presentation_id)

```text
GET presentation from Slides API
GET file metadata from Drive (modified, owners, link)
FOR each slide:
  capture object id, element count, short text preview
RETURN metadata summary
```

## 5.4 read_slides_presentation(presentation_id, max_chars=8000)

```text
GET presentation from Slides API
EXTRACT text blocks per slide
JOIN blocks and truncate by max_chars
RETURN content summary + truncation status
```

## 5.5 create_slides_presentation(title, initial_slide_title='')

```text
POST /presentations with title
IF initial_slide_title provided:
  create text slide via batchUpdate
RETURN created presentation id + link (+ warning if initial slide insert fails)
```

## 5.6 add_text_slide(presentation_id, title, body='')

```text
BUILD batchUpdate requests:
  create blank slide
  create title textbox + insert title text
  optional body textbox + insert body text
POST batchUpdate
RETURN slide id + link
```

## 5.7 list_presentations(limit=10, include_powerpoint=True)

```text
QUERY Drive using unified presentation mime filter
FORMAT lines with normalized type labels
RETURN summary
```

## 5.7b list_presentation_templates(limit=10, folder_name='Documents', name_contains='template', include_powerpoint=True)

```text
VALIDATE input
RESOLVE folder id by folder_name:
  QUERY Drive folders where name == folder_name and trashed=false
BUILD unified presentation mime query from include_powerpoint
ADD parent filter: '<folder_id>' in parents
IF name_contains is non-empty:
  ADD name contains filter
QUERY Drive files
FORMAT lines with normalized presentation type labels
RETURN template candidate summary
```

## 5.8 search_presentations(query, limit=10, include_powerpoint=True)

```text
BUILD unified mime query + name contains query
FORMAT lines with normalized type labels
RETURN summary
```

## 5.9 get_presentation_metadata(file_id)

```text
GET Drive file metadata
IF native Slides:
  GET Slides API metadata and derive text length
IF .pptx:
  download bytes and parse slide count/text length
IF .ppt:
  return conversion guidance hint
RETURN unified metadata summary
```

## 5.10 read_powerpoint_document(file_id, max_chars=8000)

```text
GET Drive metadata
IF native Slides:
  return guidance to use read_slides_presentation
IF .ppt:
  return conversion-first guidance
IF .pptx:
  download bytes
  parse text blocks from slide XML
  truncate by max_chars
  return content summary
```

## 5.11 convert_powerpoint_to_google_slides(file_id, new_title='', move_to_parent=True)

```text
GET source Drive metadata
IF already native Slides:
  return current link
VALIDATE source mime is .pptx/.ppt

TRY Drive copy conversion:
  POST /files/{id}/copy with mimeType=google-apps.presentation
IF copy fails:
  download source bytes
  multipart upload with target mimeType=google-apps.presentation

RETURN new presentation id + link
```

## 5.12 share_presentation_to_user(presentation_id, user_email, role='reader', send_notification=True, message='')

```text
GET Drive metadata and validate presentation mime
POST Drive permissions.create with target user + role
RETURN permission id + share details
```

## 5.13 export_slides_presentation(presentation_id, export_format='pdf', max_chars=8000)

```text
GET Drive metadata and verify native Slides mime
DOWNLOAD export bytes via Drive export endpoint using selected mime
IF binary format (pdf/pptx):
  return metadata + byte size
IF text format (txt):
  decode text, truncate by max_chars, return preview
```
