import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("GoogleDrive")

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"
HTTP_TIMEOUT = httpx.Timeout(timeout=20.0, connect=5.0)
GOOGLE_WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."
SUPPORTED_TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/yaml",
    "application/x-yaml",
    "application/csv",
    "text/csv",
    "text/markdown",
    "text/x-markdown",
    "application/x-www-form-urlencoded",
}
SHARE_ROLES = {"reader", "commenter", "writer"}


class _ListDriveFilesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    limit: int = Field(default=10, ge=1, le=100, strict=True)
    folder_id: str | None = Field(default=None, min_length=1)
    mime_type: str | None = Field(default=None, min_length=1)


class _SearchDriveFilesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100, strict=True)
    folder_id: str | None = Field(default=None, min_length=1)


class _GetDriveFileMetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)


class _ReadDriveTextFileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)


class _ListSharedWithMeInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, strict=True)


class _CreateDriveFolderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    parent_id: str | None = Field(default=None, min_length=1)


class _UploadTextFileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    content: str = Field(default="")
    parent_id: str | None = Field(default=None, min_length=1)


class _MoveDriveFileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)
    new_parent_id: str = Field(min_length=1)


class _CreateDriveSharedLinkToUserInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_id: str = Field(min_length=1)
    user_email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="reader")
    send_notification: bool = True
    message: str = Field(default="")
    expires_in_days: int = Field(default=7, ge=1, le=365, strict=True)


class _CreateDrivePublicLinkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_id: str = Field(min_length=1)
    role: str = Field(default="reader")
    allow_discovery: bool = False


def _get_access_token() -> str:
    token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    if not token:
        raise ValueError("GOOGLE_DRIVE_ACCESS_TOKEN must be set in .env")
    return token


def _client_kwargs() -> dict:
    return {"follow_redirects": True, "timeout": HTTP_TIMEOUT}


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _is_text_like_mime_type(mime_type: str) -> bool:
    lowered = mime_type.lower()
    return lowered.startswith("text/") or lowered in SUPPORTED_TEXT_MIME_TYPES


def _format_file_line(file_data: dict) -> str:
    name = file_data.get("name") or "Untitled"
    file_id = file_data.get("id") or "-"
    mime_type = file_data.get("mimeType") or "-"
    modified = file_data.get("modifiedTime") or "-"
    size = file_data.get("size") or "-"
    web_link = file_data.get("webViewLink") or "-"
    return (
        f"- {name} | ID: {file_id} | Type: {mime_type} | Modified: {modified} | "
        f"Size: {size} | Link: {web_link}"
    )


def _format_drive_error(response: httpx.Response) -> str:
    status = response.status_code
    detail = ""
    reason = ""
    try:
        payload = response.json()
        error_obj = payload.get("error", {}) if isinstance(payload, dict) else {}
        detail = str(error_obj.get("message", "")).strip()
        errors = error_obj.get("errors", []) if isinstance(error_obj, dict) else []
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                reason = str(first.get("reason", "")).strip()
    except Exception:
        detail = response.text.strip()[:300]

    hint = ""
    if status == 403:
        hint = (
            " Hint: ensure token has scope https://www.googleapis.com/auth/drive "
            "and your account has permission to share/edit this item."
        )
    reason_part = f" ({reason})" if reason else ""
    detail_part = f" - {detail}" if detail else ""
    return f"Error: Drive API request failed: {status}{reason_part}{detail_part}.{hint}".strip()


def _normalize_role(role: str) -> tuple[str | None, str | None]:
    lowered = role.lower().strip()
    if lowered not in SHARE_ROLES:
        return None, f"Invalid role '{role}'. Allowed roles: {', '.join(sorted(SHARE_ROLES))}"
    return lowered, None


def _to_rfc3339_after_days(days: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    return expires_at.isoformat().replace("+00:00", "Z")


async def _request_json(path: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token), params=params)

    if response.status_code != 200:
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Drive API response parse error: {str(exc)}"


async def _request_bytes(path: str, params: dict | None = None) -> tuple[bytes | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token), params=params)

    if response.status_code != 200:
        return None, _format_drive_error(response)
    return response.content, None


async def _post_json(path: str, params: dict | None = None, json_body: dict | None = None):
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.post(url, headers=_auth_headers(token), params=params, json=json_body)

    if response.status_code not in (200, 201):
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Drive API response parse error: {str(exc)}"


async def _patch_json(path: str, params: dict | None = None, json_body: dict | None = None):
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.patch(url, headers=_auth_headers(token), params=params, json=json_body)

    if response.status_code != 200:
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Drive API response parse error: {str(exc)}"


async def _upload_file_media(file_id: str, content: bytes, content_type: str = "text/plain; charset=utf-8"):
    token = _get_access_token()
    url = f"{DRIVE_UPLOAD_API_BASE}/files/{file_id}"
    headers = _auth_headers(token)
    headers["Content-Type"] = content_type
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.patch(
            url,
            headers=headers,
            params={
                "uploadType": "media",
                "supportsAllDrives": "true",
            },
            content=content,
        )

    if response.status_code != 200:
        return _format_drive_error(response)
    return None


@mcp.tool()
async def list_drive_files(limit: int = 10, folder_id: str | None = None, mime_type: str | None = None) -> str:
    """Lists files from Google Drive."""
    try:
        params = _ListDriveFilesInput.model_validate(
            {"limit": limit, "folder_id": folder_id, "mime_type": mime_type}
        )
        query_parts = ["trashed=false"]
        if params.folder_id:
            safe_folder = _escape_drive_query(params.folder_id)
            query_parts.append(f"'{safe_folder}' in parents")
        if params.mime_type:
            safe_mime = _escape_drive_query(params.mime_type)
            query_parts.append(f"mimeType='{safe_mime}'")

        data, err = await _request_json(
            "/files",
            {
                "q": " and ".join(query_parts),
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err

        files = data.get("files", []) if data else []
        if not files:
            return "No files found."
        lines = [_format_file_line(item) for item in files]
        return f"Drive Files (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error listing drive files: {str(exc)}"


@mcp.tool()
async def search_drive_files(query: str, limit: int = 10, folder_id: str | None = None) -> str:
    """Searches files in Google Drive by file name."""
    try:
        params = _SearchDriveFilesInput.model_validate(
            {"query": query, "limit": limit, "folder_id": folder_id}
        )
        safe_query = _escape_drive_query(params.query)
        query_parts = [f"name contains '{safe_query}'", "trashed=false"]
        if params.folder_id:
            safe_folder = _escape_drive_query(params.folder_id)
            query_parts.append(f"'{safe_folder}' in parents")

        data, err = await _request_json(
            "/files",
            {
                "q": " and ".join(query_parts),
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err

        files = data.get("files", []) if data else []
        if not files:
            return f"No files found matching '{params.query}'"
        lines = [_format_file_line(item) for item in files]
        return f"Search Results for '{params.query}' (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error searching drive files: {str(exc)}"


@mcp.tool()
async def get_drive_file_metadata(file_id: str) -> str:
    """Gets detailed metadata for a Google Drive file."""
    try:
        params = _GetDriveFileMetadataInput.model_validate({"file_id": file_id})
        data, err = await _request_json(
            f"/files/{params.file_id}",
            {
                "fields": (
                    "id,name,mimeType,size,createdTime,modifiedTime,webViewLink,"
                    "owners(displayName,emailAddress),parents,shared,trashed"
                ),
                "supportsAllDrives": "true",
            },
        )
        if err:
            return err
        if not data:
            return "No metadata found."

        owners = data.get("owners", [])
        owners_text = ", ".join(
            [
                f"{owner.get('displayName', '-') } <{owner.get('emailAddress', '-')}>"
                for owner in owners
            ]
        ) or "-"
        parents = ", ".join(data.get("parents", [])) or "-"

        return (
            "File Metadata:\n"
            f"Name: {data.get('name', '-')}\n"
            f"ID: {data.get('id', '-')}\n"
            f"Mime Type: {data.get('mimeType', '-')}\n"
            f"Size: {data.get('size', '-')}\n"
            f"Created: {data.get('createdTime', '-')}\n"
            f"Modified: {data.get('modifiedTime', '-')}\n"
            f"Shared: {data.get('shared', False)}\n"
            f"Trashed: {data.get('trashed', False)}\n"
            f"Owners: {owners_text}\n"
            f"Parents: {parents}\n"
            f"Web Link: {data.get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error getting drive file metadata: {str(exc)}"


@mcp.tool()
async def read_drive_text_file(file_id: str, max_chars: int = 8000) -> str:
    """Reads textual content from a regular (non-Google Workspace) Drive file."""
    try:
        params = _ReadDriveTextFileInput.model_validate({"file_id": file_id, "max_chars": max_chars})
        metadata, err = await _request_json(
            f"/files/{params.file_id}",
            {"fields": "id,name,mimeType,size", "supportsAllDrives": "true"},
        )
        if err:
            return err
        if not metadata:
            return "No metadata found."

        file_name = metadata.get("name", params.file_id)
        mime_type = metadata.get("mimeType", "")
        if mime_type.startswith(GOOGLE_WORKSPACE_MIME_PREFIX):
            return (
                f"Unsupported file type for this MCP phase: {mime_type}. "
                "Google Docs/Sheets/Slides are handled by a separate MCP."
            )
        if not _is_text_like_mime_type(mime_type):
            return f"Unsupported non-text file type: {mime_type}"

        content_bytes, err = await _request_bytes(
            f"/files/{params.file_id}",
            {"alt": "media", "supportsAllDrives": "true"},
        )
        if err:
            return err

        text = (content_bytes or b"").decode("utf-8", errors="replace").strip()
        if not text:
            return f"File '{file_name}' is empty."
        if len(text) > params.max_chars:
            text = text[: params.max_chars].rstrip() + "\n\n[Truncated]"
        return f"File Content: {file_name}\n\n{text}"
    except Exception as exc:
        return f"Error reading drive file: {str(exc)}"


@mcp.tool()
async def list_shared_with_me(limit: int = 10) -> str:
    """Lists files that are shared with the authenticated user."""
    try:
        params = _ListSharedWithMeInput.model_validate({"limit": limit})
        data, err = await _request_json(
            "/files",
            {
                "q": "sharedWithMe=true and trashed=false",
                "orderBy": "sharedWithMeTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err
        files = data.get("files", []) if data else []
        if not files:
            return "No shared files found."

        lines = [_format_file_line(item) for item in files]
        return f"Shared Files (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error listing shared files: {str(exc)}"


@mcp.tool()
async def create_drive_folder(name: str, parent_id: str | None = None) -> str:
    """Creates a folder in Google Drive."""
    try:
        params = _CreateDriveFolderInput.model_validate({"name": name, "parent_id": parent_id})
        payload = {
            "name": params.name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if params.parent_id:
            payload["parents"] = [params.parent_id]

        data, err = await _post_json(
            "/files",
            params={
                "supportsAllDrives": "true",
                "fields": "id,name,mimeType,parents,webViewLink",
            },
            json_body=payload,
        )
        if err:
            return err
        if not data:
            return "Failed to create folder."
        return (
            "Folder created:\n"
            f"Name: {data.get('name', '-')}\n"
            f"ID: {data.get('id', '-')}\n"
            f"Link: {data.get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error creating folder: {str(exc)}"


@mcp.tool()
async def upload_text_file(name: str, content: str, parent_id: str | None = None) -> str:
    """Uploads a plain text file to Google Drive."""
    try:
        params = _UploadTextFileInput.model_validate(
            {"name": name, "content": content, "parent_id": parent_id}
        )
        metadata_payload = {
            "name": params.name,
            "mimeType": "text/plain",
        }
        if params.parent_id:
            metadata_payload["parents"] = [params.parent_id]

        created, err = await _post_json(
            "/files",
            params={
                "supportsAllDrives": "true",
                "fields": "id,name,mimeType,webViewLink",
            },
            json_body=metadata_payload,
        )
        if err:
            return err
        if not created or not created.get("id"):
            return "Failed to create file metadata."

        file_id = created["id"]
        upload_err = await _upload_file_media(file_id, params.content.encode("utf-8"))
        if upload_err:
            return upload_err

        latest, latest_err = await _request_json(
            f"/files/{file_id}",
            params={
                "fields": "id,name,mimeType,size,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if latest_err and not latest:
            latest = created

        return (
            "File uploaded:\n"
            f"Name: {latest.get('name', '-')}\n"
            f"ID: {latest.get('id', '-')}\n"
            f"Type: {latest.get('mimeType', '-')}\n"
            f"Size: {latest.get('size', '-')}\n"
            f"Link: {latest.get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error uploading text file: {str(exc)}"


@mcp.tool()
async def move_drive_file(file_id: str, new_parent_id: str) -> str:
    """Moves a Drive file or folder to another parent folder."""
    try:
        params = _MoveDriveFileInput.model_validate(
            {"file_id": file_id, "new_parent_id": new_parent_id}
        )
        item, err = await _request_json(
            f"/files/{params.file_id}",
            params={
                "fields": "id,name,mimeType,parents,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if err:
            return err
        if not item:
            return "Drive item not found."

        current_parents = item.get("parents", [])
        patch_params = {
            "addParents": params.new_parent_id,
            "supportsAllDrives": "true",
            "fields": "id,name,mimeType,parents,webViewLink",
        }
        if current_parents:
            patch_params["removeParents"] = ",".join(current_parents)

        moved, err = await _patch_json(
            f"/files/{params.file_id}",
            params=patch_params,
            json_body={},
        )
        if err:
            return err
        if not moved:
            return "Failed to move drive item."

        return (
            "Drive item moved:\n"
            f"Name: {moved.get('name', '-')}\n"
            f"ID: {moved.get('id', '-')}\n"
            f"New Parents: {', '.join(moved.get('parents', [])) or '-'}\n"
            f"Link: {moved.get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error moving drive file: {str(exc)}"


@mcp.tool()
async def create_drive_shared_link_to_user(
    item_id: str,
    user_email: str,
    role: str = "reader",
    send_notification: bool = True,
    message: str = "",
    expires_in_days: int = 7,
) -> str:
    """
    Shares a Drive file/folder to a specific user with default expiration in 7 days.
    """
    try:
        params = _CreateDriveSharedLinkToUserInput.model_validate(
            {
                "item_id": item_id,
                "user_email": user_email,
                "role": role,
                "send_notification": send_notification,
                "message": message,
                "expires_in_days": expires_in_days,
            }
        )
        normalized_role, role_err = _normalize_role(params.role)
        if role_err:
            return role_err

        permission_payload = {
            "type": "user",
            "role": normalized_role,
            "emailAddress": params.user_email,
            "expirationTime": _to_rfc3339_after_days(params.expires_in_days),
        }
        permission_params = {
            "supportsAllDrives": "true",
            "sendNotificationEmail": str(params.send_notification).lower(),
            "fields": "id,type,role,emailAddress,expirationTime",
        }
        if params.message:
            permission_params["emailMessage"] = params.message

        permission, err = await _post_json(
            f"/files/{params.item_id}/permissions",
            params=permission_params,
            json_body=permission_payload,
        )
        shared_without_expiration = False
        if err and "cannotSetExpiration" in err:
            fallback_payload = {
                "type": "user",
                "role": normalized_role,
                "emailAddress": params.user_email,
            }
            permission, err = await _post_json(
                f"/files/{params.item_id}/permissions",
                params=permission_params,
                json_body=fallback_payload,
            )
            if not err:
                shared_without_expiration = True
        if err:
            return err

        item, item_err = await _request_json(
            f"/files/{params.item_id}",
            params={
                "fields": "id,name,mimeType,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if item_err and not item:
            return (
                "Permission created, but failed to fetch item metadata.\n"
                f"Permission ID: {permission.get('id', '-')}\n"
                f"Error: {item_err}"
            )

        result = (
            "Drive shared link created for user:\n"
            f"Item: {item.get('name', '-')}\n"
            f"Item ID: {item.get('id', params.item_id)}\n"
            f"Role: {permission.get('role', normalized_role)}\n"
            f"User: {permission.get('emailAddress', params.user_email)}\n"
            f"Permission ID: {permission.get('id', '-')}\n"
            f"Expires At: {permission.get('expirationTime', '-')}\n"
            f"Link: {item.get('webViewLink', '-')}"
        )
        if shared_without_expiration:
            result += (
                "\nNote: This item does not support expiration. "
                "Permission was created without expiration."
            )
        return result
    except Exception as exc:
        return f"Error creating drive shared link to user: {str(exc)}"


@mcp.tool()
async def create_drive_public_link(
    item_id: str,
    role: str = "reader",
    allow_discovery: bool = False,
) -> str:
    """
    Creates public access link ("anyone") for a Drive file/folder.
    Note: expiration is not supported by Google Drive API for 'anyone' permissions.
    """
    try:
        params = _CreateDrivePublicLinkInput.model_validate(
            {
                "item_id": item_id,
                "role": role,
                "allow_discovery": allow_discovery,
            }
        )
        normalized_role, role_err = _normalize_role(params.role)
        if role_err:
            return role_err

        permission_payload = {
            "type": "anyone",
            "role": normalized_role,
            "allowFileDiscovery": params.allow_discovery,
        }
        permission, err = await _post_json(
            f"/files/{params.item_id}/permissions",
            params={
                "supportsAllDrives": "true",
                "fields": "id,type,role,allowFileDiscovery",
            },
            json_body=permission_payload,
        )
        if err:
            return err

        item, item_err = await _request_json(
            f"/files/{params.item_id}",
            params={
                "fields": "id,name,mimeType,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if item_err and not item:
            return (
                "Public permission created, but failed to fetch item metadata.\n"
                f"Permission ID: {permission.get('id', '-')}\n"
                f"Error: {item_err}"
            )

        return (
            "Drive public link created:\n"
            f"Item: {item.get('name', '-')}\n"
            f"Item ID: {item.get('id', params.item_id)}\n"
            f"Type: {item.get('mimeType', '-')}\n"
            f"Role: {permission.get('role', normalized_role)}\n"
            f"Allow Discovery: {permission.get('allowFileDiscovery', params.allow_discovery)}\n"
            f"Permission ID: {permission.get('id', '-')}\n"
            f"Link: {item.get('webViewLink', '-')}\n"
            "Note: 'anyone' permission does not support expiration."
        )
    except Exception as exc:
        return f"Error creating drive public link: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
