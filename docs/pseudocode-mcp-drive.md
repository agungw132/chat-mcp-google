# Pseudocode - MCP Drive Server

Source: `src/chat_google/mcp_servers/drive_server.py`

## 1) Server initialization

```text
LOAD .env
CREATE FastMCP server named "GoogleDrive"
DEFINE API base URLs:
    DRIVE_API_BASE
    DRIVE_UPLOAD_API_BASE
DEFINE timeout constants and MIME helpers
DEFINE allowed share roles: {"reader","commenter","writer"}
DEFINE pydantic input models for all tools
```

## 2) Core helpers

### `_get_access_token()`

```text
READ GOOGLE_DRIVE_ACCESS_TOKEN from env
IF missing -> raise ValueError
RETURN token
```

### `_auth_headers(token)`

```text
RETURN {"Authorization": "Bearer <token>"}
```

### `_escape_drive_query(value)`

```text
ESCAPE backslash and single quote for Drive query syntax
RETURN escaped string
```

### `_is_text_like_mime_type(mime_type)`

```text
RETURN True when:
    mime starts with "text/"
    OR mime in supported text MIME set
ELSE False
```

### `_format_drive_error(response)`

```text
READ status + parse JSON error payload if possible
EXTRACT message + reason
IF status == 403:
    append token/permission hint
RETURN standardized:
    "Error: Drive API request failed: <status>(<reason>) - <detail>. <hint>"
```

### `_normalize_role(role)`

```text
lower = role.lower().strip()
IF lower not in allowed roles:
    RETURN (None, "Invalid role ...")
RETURN (lower, None)
```

### `_to_rfc3339_after_days(days)`

```text
expires_at = now_utc + days
RETURN RFC3339 string ending with "Z"
```

### HTTP wrapper helpers

`_request_json`, `_request_bytes`, `_post_json`, `_patch_json`, `_upload_file_media`:

```text
1. Build full URL
2. Attach bearer token authorization
3. Execute HTTP request with timeout and redirects enabled
4. Validate expected status codes
5. Parse response (JSON/bytes) or return standardized error text
```

## 3) Tool pseudocode

## 3.1 `list_drive_files(limit=10, folder_id=None, mime_type=None)`

```text
VALIDATE inputs
BUILD Drive query:
    "trashed=false"
    optionally "'<folder_id>' in parents"
    optionally "mimeType='<mime_type>'"

GET /files with ordering and selected fields
IF error: return error text
IF no files: return "No files found."

FORMAT each file line:
    name, id, mime, modified, size, webViewLink
RETURN "Drive Files (showing N):\n..."
ON exception: return "Error listing drive files: ..."
```

## 3.2 `search_drive_files(query, limit=10, folder_id=None)`

```text
VALIDATE inputs
BUILD query:
    "name contains '<query>' and trashed=false"
    optionally parent folder filter

GET /files with ordering + fields
IF error: return error
IF no file: return "No files found matching '<query>'"
RETURN formatted results
ON exception: return "Error searching drive files: ..."
```

## 3.3 `get_drive_file_metadata(file_id)`

```text
VALIDATE file_id
GET /files/{file_id} with metadata fields:
    id,name,mime,size,created,modified,webViewLink,owners,parents,shared,trashed
IF error: return error
IF no data: return "No metadata found."

FORMAT owners and parents
RETURN multi-line "File Metadata" report
ON exception: return "Error getting drive file metadata: ..."
```

## 3.4 `read_drive_text_file(file_id, max_chars=8000)`

```text
VALIDATE input
GET file metadata (name,mime,size)
IF error: return error
IF Google Workspace mime (application/vnd.google-apps.*):
    return unsupported message (handled by separate MCP)

IF mime is not text-like:
    return "Unsupported non-text file type: <mime>"

DOWNLOAD bytes with alt=media
IF error: return error
DECODE UTF-8 with replacement
IF empty after strip: return "File '<name>' is empty."
IF len(text) > max_chars: truncate and append "[Truncated]"
RETURN "File Content: <name>\n\n<text>"
ON exception: return "Error reading drive file: ..."
```

## 3.5 `list_shared_with_me(limit=10)`

```text
VALIDATE limit
GET /files with query "sharedWithMe=true and trashed=false"
IF error: return error
IF empty: return "No shared files found."
FORMAT and return list
ON exception: return "Error listing shared files: ..."
```

## 3.6 `create_drive_folder(name, parent_id=None)`

```text
VALIDATE name/parent_id
payload = {name, mimeType=folder}
IF parent_id provided:
    payload.parents = [parent_id]

POST /files with supportsAllDrives
IF error: return error
IF no data: return "Failed to create folder."
RETURN folder details: name/id/link
ON exception: return "Error creating folder: ..."
```

## 3.7 `upload_text_file(name, content, parent_id=None)`

```text
VALIDATE input
CREATE metadata first:
    POST /files with name + mimeType "text/plain" (+ optional parent)
IF error: return error
IF missing created id: return "Failed to create file metadata."

UPLOAD media bytes:
    PATCH upload endpoint /files/{id}?uploadType=media
IF upload error: return error

FETCH latest metadata for final output
IF latest fetch fails but created exists:
    fallback to created metadata

RETURN uploaded file details (name/id/type/size/link)
ON exception: return "Error uploading text file: ..."
```

## 3.8 `move_drive_file(file_id, new_parent_id)`

```text
VALIDATE input
GET current file metadata to read existing parents
IF error: return error
IF not found: return "Drive item not found."

PATCH /files/{id} with:
    addParents = new_parent_id
    removeParents = current parent list (if any)
IF error: return error
IF no moved data: return "Failed to move drive item."

RETURN moved item details with new parent ids
ON exception: return "Error moving drive file: ..."
```

## 3.9 `create_drive_shared_link_to_user(...)`

Args:

- `item_id`
- `user_email`
- `role` default `reader`
- `send_notification` default `True`
- `message` optional
- `expires_in_days` default `7`

```text
VALIDATE inputs (including email regex and expires_in_days range)
NORMALIZE role
IF invalid role: return role error

BUILD permission payload:
    type=user
    role=<normalized>
    emailAddress=<user_email>
    expirationTime=now+expires_in_days (RFC3339)
BUILD permission params:
    supportsAllDrives=true
    sendNotificationEmail=true/false
    fields includes permission details
    optional emailMessage

POST /files/{item_id}/permissions
IF error contains "cannotSetExpiration":
    RETRY without expirationTime
    mark shared_without_expiration=True on success
IF still error: return error

FETCH item metadata (id,name,mimeType,webViewLink)
IF metadata fails:
    return partial success message with permission id + metadata error

RETURN success report with:
    item info, role, user, permission id, expiration, web link
IF shared_without_expiration:
    append explanatory note
ON exception: return "Error creating drive shared link to user: ..."
```

## 3.10 `create_drive_public_link(item_id, role="reader", allow_discovery=False)`

```text
VALIDATE inputs
NORMALIZE role
IF invalid: return role error

payload = {
    type: "anyone",
    role: normalized_role,
    allowFileDiscovery: allow_discovery
}
POST /files/{item_id}/permissions
IF error: return error

FETCH item metadata (id,name,mimeType,webViewLink)
IF metadata fails:
    return partial success with permission id + metadata error

RETURN success report with:
    item info, permission id, role, discovery flag, web link
    plus note: anyone permission has no expiration support
ON exception: return "Error creating drive public link: ..."
```

## 4) Server runner

```text
def run():
    mcp.run()

if __name__ == "__main__":
    run()
```
