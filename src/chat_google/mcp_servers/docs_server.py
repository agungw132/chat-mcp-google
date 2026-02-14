import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

load_dotenv()
mcp = FastMCP("GoogleDocs")

DOCS_API_BASE = "https://docs.googleapis.com/v1"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
HTTP_TIMEOUT = httpx.Timeout(timeout=20.0, connect=5.0)
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60
DOC_SHARE_ROLES = {"reader", "commenter", "writer"}
DOC_EXPORT_FORMATS = {
    "txt": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_CACHED_ACCESS_TOKEN: str | None = None
_CACHED_ACCESS_TOKEN_EXPIRES_AT: datetime | None = None


class _ListDocsInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, strict=True)


class _SearchDocsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100, strict=True)


class _DocumentIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str = Field(min_length=1)


class _ReadDocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str = Field(min_length=1)
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)


class _CreateDocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    title: str = Field(min_length=1)
    initial_content: str = Field(default="")


class _AppendTextInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class _ReplaceTextInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    document_id: str = Field(min_length=1)
    find_text: str = Field(min_length=1)
    replace_text: str = Field(default="")
    match_case: bool = False


class _ShareDocsToUserInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str = Field(min_length=1)
    user_email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="reader")
    send_notification: bool = True
    message: str = Field(default="")


class _ExportDocsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str = Field(min_length=1)
    export_format: str = Field(default="pdf")
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)


class _AppendStructuredContentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    document_id: str = Field(min_length=1)
    heading: str = Field(default="")
    paragraph: str = Field(default="")
    bullet_items: list[str] = Field(default_factory=list, max_length=100)
    numbered_items: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_non_empty_content(self):
        has_heading = bool(self.heading.strip())
        has_paragraph = bool(self.paragraph.strip())
        has_bullets = any(str(item).strip() for item in self.bullet_items)
        has_numbered = any(str(item).strip() for item in self.numbered_items)
        if not (has_heading or has_paragraph or has_bullets or has_numbered):
            raise ValueError(
                "Provide at least one of: heading, paragraph, bullet_items, numbered_items."
            )
        return self


class _ReplaceTextIfRevisionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    document_id: str = Field(min_length=1)
    expected_revision_id: str = Field(min_length=1)
    find_text: str = Field(min_length=1)
    replace_text: str = Field(default="")
    match_case: bool = False


def _get_cached_access_token() -> str | None:
    global _CACHED_ACCESS_TOKEN, _CACHED_ACCESS_TOKEN_EXPIRES_AT
    if not _CACHED_ACCESS_TOKEN or not _CACHED_ACCESS_TOKEN_EXPIRES_AT:
        return None
    if datetime.now(timezone.utc) >= _CACHED_ACCESS_TOKEN_EXPIRES_AT:
        _CACHED_ACCESS_TOKEN = None
        _CACHED_ACCESS_TOKEN_EXPIRES_AT = None
        return None
    return _CACHED_ACCESS_TOKEN


def _invalidate_cached_access_token() -> None:
    global _CACHED_ACCESS_TOKEN, _CACHED_ACCESS_TOKEN_EXPIRES_AT
    _CACHED_ACCESS_TOKEN = None
    _CACHED_ACCESS_TOKEN_EXPIRES_AT = None


def _set_cached_access_token(token: str, expires_in_seconds: int) -> None:
    global _CACHED_ACCESS_TOKEN, _CACHED_ACCESS_TOKEN_EXPIRES_AT
    safe_ttl = max(0, int(expires_in_seconds) - TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS)
    _CACHED_ACCESS_TOKEN = token
    _CACHED_ACCESS_TOKEN_EXPIRES_AT = datetime.now(timezone.utc) + timedelta(seconds=safe_ttl)


def _refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> tuple[str, int]:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    with httpx.Client(**_client_kwargs()) as client:
        response = client.post(GOOGLE_OAUTH_TOKEN_ENDPOINT, data=payload)

    if response.status_code != 200:
        detail = ""
        try:
            body = response.json()
            error = body.get("error", "")
            error_description = body.get("error_description", "")
            detail = f"{error}: {error_description}".strip(": ").strip()
        except Exception:
            detail = response.text.strip()[:300]
        detail_part = f" - {detail}" if detail else ""
        raise ValueError(
            f"Docs OAuth refresh failed with HTTP {response.status_code}{detail_part}"
        )

    try:
        data = response.json()
    except Exception as exc:
        raise ValueError(f"Docs OAuth refresh response parse error: {exc}") from exc

    token = str(data.get("access_token", "")).strip()
    if not token:
        raise ValueError("Docs OAuth refresh response missing access_token")

    expires_in_raw = data.get("expires_in", 3600)
    try:
        expires_in = int(expires_in_raw)
    except Exception:
        expires_in = 3600
    return token, expires_in


def _get_access_token() -> str:
    # Reload .env so token rotation scripts can update running MCP processes without restart.
    load_dotenv(override=True)

    cached = _get_cached_access_token()
    if cached:
        return cached

    static_token = (os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN") or "").strip()
    refresh_token = (os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN") or "").strip()
    client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()

    has_any_refresh_inputs = any([refresh_token, client_id, client_secret])
    has_full_refresh_inputs = all([refresh_token, client_id, client_secret])

    if has_full_refresh_inputs:
        try:
            refreshed_token, expires_in = _refresh_access_token(
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            _set_cached_access_token(refreshed_token, expires_in)
            os.environ["GOOGLE_DRIVE_ACCESS_TOKEN"] = refreshed_token
            return refreshed_token
        except Exception as exc:
            if static_token:
                return static_token
            raise ValueError(f"Failed to refresh Docs access token: {exc}") from exc

    if has_any_refresh_inputs and not has_full_refresh_inputs:
        missing = []
        if not refresh_token:
            missing.append("GOOGLE_DRIVE_REFRESH_TOKEN")
        if not client_id:
            missing.append("GOOGLE_OAUTH_CLIENT_ID")
        if not client_secret:
            missing.append("GOOGLE_OAUTH_CLIENT_SECRET")
        if static_token:
            return static_token
        raise ValueError(
            "Incomplete Docs OAuth refresh configuration. Missing: " + ", ".join(missing)
        )

    if static_token:
        return static_token

    raise ValueError(
        "Set GOOGLE_DRIVE_ACCESS_TOKEN or configure refresh flow with "
        "GOOGLE_DRIVE_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, and GOOGLE_OAUTH_CLIENT_SECRET in .env"
    )


def _client_kwargs() -> dict:
    return {"follow_redirects": True, "timeout": HTTP_TIMEOUT}


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _format_docs_error(response: httpx.Response) -> str:
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
    detail_part = f" - {detail}" if detail else ""
    hint = ""
    if status == 401:
        hint = (
            " Hint: access token expired/invalid. Configure refresh flow with "
            "GOOGLE_DRIVE_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET."
        )
    elif status == 403:
        hint = (
            " Hint: ensure Google Docs API is enabled and token scope allows Docs/Drive access."
        )
    reason_part = f" ({reason})" if reason else ""
    return f"Error: Google Docs API request failed: {status}{reason_part}{detail_part}.{hint}".strip()


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
    detail_part = f" - {detail}" if detail else ""
    hint = ""
    if status == 401:
        hint = (
            " Hint: access token expired/invalid. Configure refresh flow with "
            "GOOGLE_DRIVE_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET."
        )
    reason_part = f" ({reason})" if reason else ""
    return f"Error: Drive API request failed: {status}{reason_part}{detail_part}.{hint}".strip()


def _extract_document_text(document: dict) -> str:
    body = document.get("body", {})
    content_blocks = body.get("content", []) if isinstance(body, dict) else []
    chunks: list[str] = []
    for block in content_blocks:
        paragraph = block.get("paragraph", {}) if isinstance(block, dict) else {}
        elements = paragraph.get("elements", []) if isinstance(paragraph, dict) else []
        for element in elements:
            text_run = element.get("textRun", {}) if isinstance(element, dict) else {}
            text = text_run.get("content", "") if isinstance(text_run, dict) else ""
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


def _document_insert_index(document: dict) -> int:
    body = document.get("body", {})
    content_blocks = body.get("content", []) if isinstance(body, dict) else []
    if not content_blocks:
        return 1
    last = content_blocks[-1]
    end_index = 1
    if isinstance(last, dict):
        try:
            end_index = int(last.get("endIndex", 1))
        except Exception:
            end_index = 1
    return max(1, end_index - 1)


def _normalize_share_role(role: str) -> tuple[str | None, str | None]:
    lowered = role.lower().strip()
    if lowered not in DOC_SHARE_ROLES:
        return None, f"Invalid role '{role}'. Allowed roles: {', '.join(sorted(DOC_SHARE_ROLES))}"
    return lowered, None


def _normalize_export_format(export_format: str) -> tuple[str | None, str | None]:
    normalized = export_format.lower().strip()
    mime_type = DOC_EXPORT_FORMATS.get(normalized)
    if not mime_type:
        return None, (
            f"Invalid export_format '{export_format}'. "
            f"Allowed: {', '.join(sorted(DOC_EXPORT_FORMATS))}"
        )
    return mime_type, None


def _build_structured_append_text(params: _AppendStructuredContentInput) -> str:
    lines: list[str] = []
    heading = params.heading.strip()
    if heading:
        lines.append(heading)
        lines.append("")

    paragraph = params.paragraph.strip()
    if paragraph:
        lines.append(paragraph)
        lines.append("")

    bullet_lines = [str(item).strip() for item in params.bullet_items if str(item).strip()]
    for item in bullet_lines:
        lines.append(f"- {item}")
    if bullet_lines:
        lines.append("")

    numbered_lines = [str(item).strip() for item in params.numbered_items if str(item).strip()]
    for idx, item in enumerate(numbered_lines, start=1):
        lines.append(f"{idx}. {item}")

    text = "\n".join(lines).rstrip()
    if not text:
        return ""
    return "\n\n" + text


async def _docs_get(path: str) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DOCS_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token))
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.get(url, headers=_auth_headers(retry_token))
    if response.status_code != 200:
        return None, _format_docs_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Google Docs API response parse error: {str(exc)}"


async def _docs_post(path: str, json_body: dict | None = None) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DOCS_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.post(url, headers=_auth_headers(token), json=json_body)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.post(url, headers=_auth_headers(retry_token), json=json_body)
    if response.status_code not in (200, 201):
        return None, _format_docs_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Google Docs API response parse error: {str(exc)}"


async def _drive_get(path: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token), params=params)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.get(url, headers=_auth_headers(retry_token), params=params)
    if response.status_code != 200:
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Drive API response parse error: {str(exc)}"


async def _drive_post_json(
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.post(url, headers=_auth_headers(token), params=params, json=json_body)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.post(
                    url,
                    headers=_auth_headers(retry_token),
                    params=params,
                    json=json_body,
                )
    if response.status_code not in (200, 201):
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception:
        return {}, None


async def _drive_get_bytes(path: str, params: dict | None = None) -> tuple[bytes | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token), params=params)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.get(url, headers=_auth_headers(retry_token), params=params)
    if response.status_code != 200:
        return None, _format_drive_error(response)
    return response.content, None


def _format_doc_line(item: dict) -> str:
    name = item.get("name", "Untitled")
    doc_id = item.get("id", "-")
    modified = item.get("modifiedTime", "-")
    link = item.get("webViewLink", "-")
    return f"- {name} | ID: {doc_id} | Modified: {modified} | Link: {link}"


@mcp.tool()
async def list_docs_documents(limit: int = 10) -> str:
    """Lists Google Docs documents from Drive."""
    try:
        params = _ListDocsInput.model_validate({"limit": limit})
        data, err = await _drive_get(
            "/files",
            params={
                "q": f"mimeType='{GOOGLE_DOC_MIME}' and trashed=false",
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,modifiedTime,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err
        files = data.get("files", []) if data else []
        if not files:
            return "No Google Docs documents found."
        lines = [_format_doc_line(item) for item in files]
        return f"Google Docs Documents (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error listing Google Docs documents: {str(exc)}"


@mcp.tool()
async def search_docs_documents(query: str, limit: int = 10) -> str:
    """Searches Google Docs documents by title/name."""
    try:
        params = _SearchDocsInput.model_validate({"query": query, "limit": limit})
        safe_query = _escape_query(params.query)
        q = (
            f"mimeType='{GOOGLE_DOC_MIME}' and trashed=false and "
            f"name contains '{safe_query}'"
        )
        data, err = await _drive_get(
            "/files",
            params={
                "q": q,
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,modifiedTime,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err
        files = data.get("files", []) if data else []
        if not files:
            return f"No Google Docs documents found matching '{params.query}'"
        lines = [_format_doc_line(item) for item in files]
        return (
            f"Google Docs search results for '{params.query}' (showing {len(lines)}):\n"
            + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error searching Google Docs documents: {str(exc)}"


@mcp.tool()
async def get_docs_document_metadata(document_id: str) -> str:
    """Gets metadata for a Google Docs document."""
    try:
        params = _DocumentIdInput.model_validate({"document_id": document_id})
        doc_data, doc_err = await _docs_get(f"/documents/{params.document_id}")
        if doc_err:
            return doc_err
        drive_data, drive_err = await _drive_get(
            f"/files/{params.document_id}",
            params={
                "fields": "id,name,modifiedTime,owners(displayName,emailAddress),webViewLink",
                "supportsAllDrives": "true",
            },
        )
        owners = []
        if drive_data:
            owners = drive_data.get("owners", []) or []
        owners_text = ", ".join(
            [
                f"{owner.get('displayName', '-') } <{owner.get('emailAddress', '-')}>"
                for owner in owners
            ]
        ) or "-"
        if drive_err and not drive_data:
            owners_text = f"- (warning: {drive_err})"

        return (
            "Google Docs Metadata:\n"
            f"Title: {doc_data.get('title', '-')}\n"
            f"Document ID: {doc_data.get('documentId', params.document_id)}\n"
            f"Revision ID: {doc_data.get('revisionId', '-')}\n"
            f"Last Modified: {(drive_data or {}).get('modifiedTime', '-')}\n"
            f"Owners: {owners_text}\n"
            f"Link: {(drive_data or {}).get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error getting Google Docs metadata: {str(exc)}"


@mcp.tool()
async def read_docs_document(document_id: str, max_chars: int = 8000) -> str:
    """Reads plain text content from a Google Docs document."""
    try:
        params = _ReadDocumentInput.model_validate(
            {"document_id": document_id, "max_chars": max_chars}
        )
        doc_data, err = await _docs_get(f"/documents/{params.document_id}")
        if err:
            return err

        title = doc_data.get("title", params.document_id)
        text = _extract_document_text(doc_data)
        if not text:
            return f"Google Docs document '{title}' is empty."
        if len(text) > params.max_chars:
            text = text[: params.max_chars].rstrip() + "\n\n[Truncated]"
        return f"Google Docs Content: {title}\n\n{text}"
    except Exception as exc:
        return f"Error reading Google Docs document: {str(exc)}"


@mcp.tool()
async def create_docs_document(title: str, initial_content: str = "") -> str:
    """Creates a new Google Docs document, optionally with initial content."""
    try:
        params = _CreateDocumentInput.model_validate(
            {"title": title, "initial_content": initial_content}
        )
        created, err = await _docs_post("/documents", json_body={"title": params.title})
        if err:
            return err
        if not created:
            return "Failed to create Google Docs document."

        document_id = created.get("documentId", "-")
        if params.initial_content and document_id != "-":
            _, update_err = await _docs_post(
                f"/documents/{document_id}:batchUpdate",
                json_body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": params.initial_content,
                            }
                        }
                    ]
                },
            )
            if update_err:
                return (
                    "Document created but failed to insert initial content.\n"
                    f"Document ID: {document_id}\n"
                    f"Error: {update_err}"
                )

        link = (
            f"https://docs.google.com/document/d/{document_id}/edit"
            if document_id != "-"
            else "-"
        )
        return (
            "Google Docs document created:\n"
            f"Title: {created.get('title', params.title)}\n"
            f"Document ID: {document_id}\n"
            f"Revision ID: {created.get('revisionId', '-')}\n"
            f"Link: {link}"
        )
    except Exception as exc:
        return f"Error creating Google Docs document: {str(exc)}"


@mcp.tool()
async def append_docs_text(document_id: str, text: str) -> str:
    """Appends text at the end of a Google Docs document."""
    try:
        params = _AppendTextInput.model_validate({"document_id": document_id, "text": text})
        doc_data, err = await _docs_get(f"/documents/{params.document_id}")
        if err:
            return err

        index = _document_insert_index(doc_data)
        _, update_err = await _docs_post(
            f"/documents/{params.document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": index},
                            "text": params.text,
                        }
                    }
                ]
            },
        )
        if update_err:
            return update_err

        link = f"https://docs.google.com/document/d/{params.document_id}/edit"
        return (
            "Text appended to Google Docs document:\n"
            f"Document ID: {params.document_id}\n"
            f"Inserted At Index: {index}\n"
            f"Link: {link}"
        )
    except Exception as exc:
        return f"Error appending text to Google Docs document: {str(exc)}"


@mcp.tool()
async def replace_docs_text(
    document_id: str,
    find_text: str,
    replace_text: str = "",
    match_case: bool = False,
) -> str:
    """Replaces matching text in a Google Docs document using replaceAllText."""
    try:
        params = _ReplaceTextInput.model_validate(
            {
                "document_id": document_id,
                "find_text": find_text,
                "replace_text": replace_text,
                "match_case": match_case,
            }
        )
        data, err = await _docs_post(
            f"/documents/{params.document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": params.find_text,
                                "matchCase": params.match_case,
                            },
                            "replaceText": params.replace_text,
                        }
                    }
                ]
            },
        )
        if err:
            return err

        replies = data.get("replies", []) if data else []
        occurrences = 0
        if replies:
            first = replies[0]
            if isinstance(first, dict):
                replace_resp = first.get("replaceAllText", {})
                if isinstance(replace_resp, dict):
                    occurrences = int(replace_resp.get("occurrencesChanged", 0))

        link = f"https://docs.google.com/document/d/{params.document_id}/edit"
        return (
            "Text replacement completed in Google Docs document:\n"
            f"Document ID: {params.document_id}\n"
            f"Find Text: {params.find_text}\n"
            f"Replace Text: {params.replace_text}\n"
            f"Occurrences Changed: {occurrences}\n"
            f"Link: {link}"
        )
    except Exception as exc:
        return f"Error replacing text in Google Docs document: {str(exc)}"


@mcp.tool()
async def share_docs_to_user(
    document_id: str,
    user_email: str,
    role: str = "reader",
    send_notification: bool = True,
    message: str = "",
) -> str:
    """Shares a Google Docs document to a specific user using Drive permissions."""
    try:
        params = _ShareDocsToUserInput.model_validate(
            {
                "document_id": document_id,
                "user_email": user_email,
                "role": role,
                "send_notification": send_notification,
                "message": message,
            }
        )
        normalized_role, role_err = _normalize_share_role(params.role)
        if role_err:
            return role_err

        query_params: dict[str, str] = {
            "supportsAllDrives": "true",
            "sendNotificationEmail": "true" if params.send_notification else "false",
        }
        note = params.message.strip()
        if params.send_notification and note:
            query_params["emailMessage"] = note

        perm_resp, perm_err = await _drive_post_json(
            f"/files/{params.document_id}/permissions",
            params=query_params,
            json_body={
                "type": "user",
                "role": normalized_role,
                "emailAddress": params.user_email,
            },
        )
        if perm_err:
            return perm_err

        meta, meta_err = await _drive_get(
            f"/files/{params.document_id}",
            params={
                "fields": "id,name,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if meta_err:
            return (
                "Document shared, but failed to fetch metadata.\n"
                f"Permission ID: {(perm_resp or {}).get('id', '-')}\n"
                f"Error: {meta_err}"
            )

        return (
            "Google Docs sharing completed:\n"
            f"Document ID: {params.document_id}\n"
            f"Document Name: {(meta or {}).get('name', '-')}\n"
            f"Shared To: {params.user_email}\n"
            f"Role: {normalized_role}\n"
            f"Notification Sent: {params.send_notification}\n"
            f"Permission ID: {(perm_resp or {}).get('id', '-')}\n"
            f"Link: {(meta or {}).get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error sharing Google Docs document: {str(exc)}"


@mcp.tool()
async def export_docs_document(
    document_id: str,
    export_format: str = "pdf",
    max_chars: int = 8000,
) -> str:
    """Exports a Google Docs document to txt/html/pdf/docx."""
    try:
        params = _ExportDocsInput.model_validate(
            {
                "document_id": document_id,
                "export_format": export_format,
                "max_chars": max_chars,
            }
        )
        mime_type, format_err = _normalize_export_format(params.export_format)
        if format_err:
            return format_err

        payload, export_err = await _drive_get_bytes(
            f"/files/{params.document_id}/export",
            params={"mimeType": mime_type},
        )
        if export_err:
            return export_err
        if payload is None:
            return "Failed to export Google Docs document."

        meta, meta_err = await _drive_get(
            f"/files/{params.document_id}",
            params={
                "fields": "id,name,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if meta_err:
            meta = {"name": "-", "webViewLink": "-"}

        size_bytes = len(payload)
        normalized_format = params.export_format.lower().strip()
        if normalized_format in {"txt", "html"}:
            text = payload.decode("utf-8", errors="replace")
            if len(text) > params.max_chars:
                text = text[: params.max_chars].rstrip() + "\n\n[Truncated]"
            return (
                "Google Docs export completed:\n"
                f"Document ID: {params.document_id}\n"
                f"Document Name: {(meta or {}).get('name', '-')}\n"
                f"Format: {normalized_format}\n"
                f"Size Bytes: {size_bytes}\n"
                f"Link: {(meta or {}).get('webViewLink', '-')}\n\n"
                f"{text}"
            )

        return (
            "Google Docs export completed:\n"
            f"Document ID: {params.document_id}\n"
            f"Document Name: {(meta or {}).get('name', '-')}\n"
            f"Format: {normalized_format}\n"
            f"MIME Type: {mime_type}\n"
            f"Size Bytes: {size_bytes}\n"
            f"Link: {(meta or {}).get('webViewLink', '-')}\n"
            "Binary export generated successfully (content not printed in chat)."
        )
    except Exception as exc:
        return f"Error exporting Google Docs document: {str(exc)}"


@mcp.tool()
async def append_docs_structured_content(
    document_id: str,
    heading: str = "",
    paragraph: str = "",
    bullet_items: list[str] | None = None,
    numbered_items: list[str] | None = None,
) -> str:
    """Appends heading/paragraph/bullets/numbered items as a structured block."""
    try:
        params = _AppendStructuredContentInput.model_validate(
            {
                "document_id": document_id,
                "heading": heading,
                "paragraph": paragraph,
                "bullet_items": bullet_items or [],
                "numbered_items": numbered_items or [],
            }
        )
        doc_data, err = await _docs_get(f"/documents/{params.document_id}")
        if err:
            return err
        text = _build_structured_append_text(params)
        if not text:
            return "Nothing to append."

        index = _document_insert_index(doc_data)
        _, update_err = await _docs_post(
            f"/documents/{params.document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": index},
                            "text": text,
                        }
                    }
                ]
            },
        )
        if update_err:
            return update_err

        link = f"https://docs.google.com/document/d/{params.document_id}/edit"
        return (
            "Structured content appended to Google Docs document:\n"
            f"Document ID: {params.document_id}\n"
            f"Inserted At Index: {index}\n"
            f"Characters Added: {len(text)}\n"
            f"Link: {link}"
        )
    except Exception as exc:
        return f"Error appending structured content to Google Docs document: {str(exc)}"


@mcp.tool()
async def replace_docs_text_if_revision(
    document_id: str,
    expected_revision_id: str,
    find_text: str,
    replace_text: str = "",
    match_case: bool = False,
) -> str:
    """Replaces text only when current document revision matches expected_revision_id."""
    try:
        params = _ReplaceTextIfRevisionInput.model_validate(
            {
                "document_id": document_id,
                "expected_revision_id": expected_revision_id,
                "find_text": find_text,
                "replace_text": replace_text,
                "match_case": match_case,
            }
        )
        doc_data, doc_err = await _docs_get(f"/documents/{params.document_id}")
        if doc_err:
            return doc_err
        current_revision_id = str(doc_data.get("revisionId", "")).strip()
        if current_revision_id != params.expected_revision_id:
            return (
                "Revision mismatch. No changes applied.\n"
                f"Document ID: {params.document_id}\n"
                f"Expected Revision ID: {params.expected_revision_id}\n"
                f"Current Revision ID: {current_revision_id or '-'}"
            )

        data, err = await _docs_post(
            f"/documents/{params.document_id}:batchUpdate",
            json_body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": params.find_text,
                                "matchCase": params.match_case,
                            },
                            "replaceText": params.replace_text,
                        }
                    }
                ]
            },
        )
        if err:
            return err
        replies = data.get("replies", []) if data else []
        occurrences = 0
        if replies:
            first = replies[0]
            if isinstance(first, dict):
                replace_resp = first.get("replaceAllText", {})
                if isinstance(replace_resp, dict):
                    occurrences = int(replace_resp.get("occurrencesChanged", 0))

        link = f"https://docs.google.com/document/d/{params.document_id}/edit"
        return (
            "Safe text replacement completed in Google Docs document:\n"
            f"Document ID: {params.document_id}\n"
            f"Revision ID: {current_revision_id or '-'}\n"
            f"Find Text: {params.find_text}\n"
            f"Replace Text: {params.replace_text}\n"
            f"Occurrences Changed: {occurrences}\n"
            f"Link: {link}"
        )
    except Exception as exc:
        return f"Error replacing text with revision check in Google Docs document: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
