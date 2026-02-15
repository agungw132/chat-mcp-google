import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
import xml.etree.ElementTree as ET
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

load_dotenv()
mcp = FastMCP("GoogleSlides")

SLIDES_API_BASE = "https://slides.googleapis.com/v1"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"
GOOGLE_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
HTTP_TIMEOUT = httpx.Timeout(timeout=20.0, connect=5.0)
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPT_MIME = "application/vnd.ms-powerpoint"
PPT_MIMES = {PPTX_MIME, PPT_MIME}
TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60
PRESENTATION_SHARE_ROLES = {"reader", "commenter", "writer"}
PRESENTATION_EXPORT_FORMATS = {
    "pdf": {"mime_type": "application/pdf", "binary": True},
    "pptx": {"mime_type": PPTX_MIME, "binary": True},
    "txt": {"mime_type": "text/plain", "binary": False},
}

_CACHED_ACCESS_TOKEN: str | None = None
_CACHED_ACCESS_TOKEN_EXPIRES_AT: datetime | None = None


class _ListSlidesInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, strict=True)


class _ListPresentationsInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, strict=True)
    include_powerpoint: bool = True


class _SearchSlidesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100, strict=True)


class _SearchPresentationsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100, strict=True)
    include_powerpoint: bool = True


class _ListPresentationTemplatesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    limit: int = Field(default=10, ge=1, le=100, strict=True)
    folder_name: str = Field(default="Documents", min_length=1)
    name_contains: str = Field(default="template")
    include_powerpoint: bool = True


class _PresentationIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    presentation_id: str = Field(min_length=1)


class _PresentationFileIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)


class _ReadSlidesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    presentation_id: str = Field(min_length=1)
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)


class _ReadPowerPointInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)


class _CreatePresentationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    title: str = Field(min_length=1)
    initial_slide_title: str = Field(default="")


class _AddTextSlideInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    presentation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(default="")


class _SharePresentationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    presentation_id: str = Field(min_length=1)
    user_email: str = Field(min_length=5)
    role: str = Field(default="reader")
    send_notification: bool = True
    message: str = Field(default="")

    @model_validator(mode="after")
    def validate_values(self):
        email = self.user_email.strip()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("user_email must be a valid email address.")
        self.user_email = email

        normalized_role = self.role.lower().strip()
        if normalized_role not in PRESENTATION_SHARE_ROLES:
            raise ValueError(
                f"Invalid role '{self.role}'. Allowed: {', '.join(sorted(PRESENTATION_SHARE_ROLES))}"
            )
        self.role = normalized_role
        return self


class _ExportSlidesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    presentation_id: str = Field(min_length=1)
    export_format: str = Field(default="pdf")
    max_chars: int = Field(default=8000, ge=200, le=50000, strict=True)

    @model_validator(mode="after")
    def validate_values(self):
        normalized_format = self.export_format.lower().strip()
        if normalized_format not in PRESENTATION_EXPORT_FORMATS:
            raise ValueError(
                f"Invalid export_format '{self.export_format}'. "
                f"Allowed: {', '.join(sorted(PRESENTATION_EXPORT_FORMATS.keys()))}"
            )
        self.export_format = normalized_format
        return self


class _ConvertPowerPointInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_id: str = Field(min_length=1)
    new_title: str = Field(default="")
    move_to_parent: bool = True


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


def _client_kwargs() -> dict:
    return {"follow_redirects": True, "timeout": HTTP_TIMEOUT}


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
            f"Slides OAuth refresh failed with HTTP {response.status_code}{detail_part}"
        )

    try:
        data = response.json()
    except Exception as exc:
        raise ValueError(f"Slides OAuth refresh response parse error: {exc}") from exc

    token = str(data.get("access_token", "")).strip()
    if not token:
        raise ValueError("Slides OAuth refresh response missing access_token")

    expires_in_raw = data.get("expires_in", 3600)
    try:
        expires_in = int(expires_in_raw)
    except Exception:
        expires_in = 3600
    return token, expires_in


def _get_access_token() -> str:
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
            raise ValueError(f"Failed to refresh Slides access token: {exc}") from exc

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
            "Incomplete Slides OAuth refresh configuration. Missing: " + ", ".join(missing)
        )

    if static_token:
        return static_token

    raise ValueError(
        "Set GOOGLE_DRIVE_ACCESS_TOKEN or configure refresh flow with "
        "GOOGLE_DRIVE_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, and GOOGLE_OAUTH_CLIENT_SECRET in .env"
    )


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _format_slides_error(response: httpx.Response) -> str:
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
            " Hint: ensure Google Slides API is enabled and token scope allows Slides/Drive access."
        )
    reason_part = f" ({reason})" if reason else ""
    return f"Error: Google Slides API request failed: {status}{reason_part}{detail_part}.{hint}".strip()


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


def _presentation_query(include_powerpoint: bool) -> str:
    if include_powerpoint:
        return (
            f"(mimeType='{GOOGLE_SLIDES_MIME}' or mimeType='{PPTX_MIME}' or mimeType='{PPT_MIME}') "
            "and trashed=false"
        )
    return f"mimeType='{GOOGLE_SLIDES_MIME}' and trashed=false"


def _presentation_type_label(mime_type: str) -> str:
    if mime_type == GOOGLE_SLIDES_MIME:
        return "google_slides"
    if mime_type == PPTX_MIME:
        return "powerpoint_pptx"
    if mime_type == PPT_MIME:
        return "powerpoint_ppt"
    return mime_type or "-"


def _strip_presentation_extension(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pptx"):
        return filename[:-5]
    if lowered.endswith(".ppt"):
        return filename[:-4]
    return filename


def _format_presentation_line(item: dict) -> str:
    name = item.get("name", "Untitled")
    presentation_id = item.get("id", "-")
    modified = item.get("modifiedTime", "-")
    link = item.get("webViewLink", "-")
    return f"- {name} | ID: {presentation_id} | Modified: {modified} | Link: {link}"


def _format_presentation_file_line(item: dict) -> str:
    name = item.get("name", "Untitled")
    file_id = item.get("id", "-")
    modified = item.get("modifiedTime", "-")
    link = item.get("webViewLink", "-")
    mime_type = str(item.get("mimeType", "")).strip()
    return (
        f"- {name} | ID: {file_id} | Type: {_presentation_type_label(mime_type)} "
        f"| Modified: {modified} | Link: {link}"
    )


async def _resolve_folder_id_by_name(folder_name: str) -> tuple[str | None, str | None]:
    safe_folder_name = _escape_query(folder_name)
    data, err = await _drive_get(
        "/files",
        params={
            "q": (
                "mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false and name='{safe_folder_name}'"
            ),
            "orderBy": "modifiedTime desc",
            "pageSize": 1,
            "fields": "files(id,name),nextPageToken",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    if err:
        return None, err

    folders = data.get("files", []) if isinstance(data, dict) else []
    if not folders:
        return None, f"Drive folder '{folder_name}' was not found."

    folder_id = str((folders[0] or {}).get("id", "")).strip()
    if not folder_id:
        return None, f"Drive folder '{folder_name}' was found but has no id."
    return folder_id, None


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def _extract_slide_text(slide: dict) -> str:
    page_elements = slide.get("pageElements", []) if isinstance(slide, dict) else []
    chunks: list[str] = []
    for element in page_elements:
        shape = element.get("shape", {}) if isinstance(element, dict) else {}
        text_obj = shape.get("text", {}) if isinstance(shape, dict) else {}
        text_elements = text_obj.get("textElements", []) if isinstance(text_obj, dict) else []
        for text_element in text_elements:
            text_run = text_element.get("textRun", {}) if isinstance(text_element, dict) else {}
            content = text_run.get("content", "") if isinstance(text_run, dict) else ""
            if content:
                chunks.append(content)
    return "".join(chunks).strip()


def _extract_presentation_text(presentation: dict) -> tuple[list[str], str]:
    slides = presentation.get("slides", []) if isinstance(presentation, dict) else []
    slide_blocks: list[str] = []
    for idx, slide in enumerate(slides, start=1):
        slide_text = _extract_slide_text(slide)
        if not slide_text:
            continue
        slide_blocks.append(f"[Slide {idx}]\n{slide_text}")
    return slide_blocks, "\n\n".join(slide_blocks).strip()


def _extract_pptx_text(payload: bytes) -> tuple[int, str]:
    slide_name_pattern = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    slides_xml: list[tuple[int, str]] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            for name in zf.namelist():
                match = slide_name_pattern.match(name)
                if not match:
                    continue
                slides_xml.append((int(match.group(1)), name))
            if not slides_xml:
                raise ValueError("No slide XML entries found.")
            slides_xml.sort(key=lambda item: item[0])

            slide_texts: list[str] = []
            for _, xml_name in slides_xml:
                xml_bytes = zf.read(xml_name)
                root = ET.fromstring(xml_bytes)
                texts = [
                    str(node.text).strip()
                    for node in root.findall(".//a:t", namespace)
                    if node.text and str(node.text).strip()
                ]
                if texts:
                    slide_texts.append("\n".join(texts))
                else:
                    slide_texts.append("")
    except Exception as exc:
        raise ValueError(f"Invalid .pptx payload: {exc}") from exc

    blocks: list[str] = []
    for idx, slide_text in enumerate(slide_texts, start=1):
        if slide_text:
            blocks.append(f"[Slide {idx}]\n{slide_text}")
    return len(slide_texts), "\n\n".join(blocks).strip()


def _build_add_text_slide_requests(title: str, body: str) -> tuple[list[dict], str]:
    slide_id = f"slide_{uuid4().hex[:12]}"
    title_shape_id = f"title_{uuid4().hex[:12]}"
    body_shape_id = f"body_{uuid4().hex[:12]}"

    requests: list[dict] = [
        {
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "BLANK"},
            }
        },
        {
            "createShape": {
                "objectId": title_shape_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {
                        "width": {"magnitude": 8000000, "unit": "EMU"},
                        "height": {"magnitude": 900000, "unit": "EMU"},
                    },
                    "transform": {
                        "scaleX": 1,
                        "scaleY": 1,
                        "translateX": 500000,
                        "translateY": 500000,
                        "unit": "EMU",
                    },
                },
            }
        },
        {
            "insertText": {
                "objectId": title_shape_id,
                "insertionIndex": 0,
                "text": title.strip(),
            }
        },
    ]

    body_text = body.strip()
    if body_text:
        requests.extend(
            [
                {
                    "createShape": {
                        "objectId": body_shape_id,
                        "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": slide_id,
                            "size": {
                                "width": {"magnitude": 8500000, "unit": "EMU"},
                                "height": {"magnitude": 3500000, "unit": "EMU"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 500000,
                                "translateY": 1700000,
                                "unit": "EMU",
                            },
                        },
                    }
                },
                {
                    "insertText": {
                        "objectId": body_shape_id,
                        "insertionIndex": 0,
                        "text": body_text,
                    }
                },
            ]
        )

    return requests, slide_id


async def _slides_get(path: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{SLIDES_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, headers=_auth_headers(token), params=params)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.get(
                    url,
                    headers=_auth_headers(retry_token),
                    params=params,
                )
    if response.status_code != 200:
        return None, _format_slides_error(response)
    try:
        return response.json(), None
    except Exception as exc:
        return None, f"Google Slides API response parse error: {str(exc)}"


async def _slides_post(path: str, json_body: dict | None = None) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{SLIDES_API_BASE}{path}"
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.post(url, headers=_auth_headers(token), json=json_body)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.post(url, headers=_auth_headers(retry_token), json=json_body)
    if response.status_code not in (200, 201):
        return None, _format_slides_error(response)
    try:
        return response.json(), None
    except Exception:
        return {}, None


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


async def _drive_upload_multipart(
    metadata: dict,
    media_bytes: bytes,
    media_mime: str,
    media_filename: str = "source.bin",
) -> tuple[dict | None, str | None]:
    token = _get_access_token()
    url = f"{DRIVE_UPLOAD_API_BASE}/files"
    params = {"uploadType": "multipart", "supportsAllDrives": "true"}
    files = {
        "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
        "media": (media_filename, media_bytes, media_mime),
    }
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.post(url, headers=_auth_headers(token), params=params, files=files)
        if response.status_code == 401:
            _invalidate_cached_access_token()
            retry_token = _get_access_token()
            if retry_token:
                response = await client.post(
                    url,
                    headers=_auth_headers(retry_token),
                    params=params,
                    files=files,
                )
    if response.status_code not in (200, 201):
        return None, _format_drive_error(response)
    try:
        return response.json(), None
    except Exception:
        return {}, None


@mcp.tool()
async def list_slides_presentations(limit: int = 10) -> str:
    """Lists native Google Slides presentations from Drive."""
    try:
        params = _ListSlidesInput.model_validate({"limit": limit})
        data, err = await _drive_get(
            "/files",
            params={
                "q": f"mimeType='{GOOGLE_SLIDES_MIME}' and trashed=false",
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
            return "No Google Slides presentations found."
        lines = [_format_presentation_line(item) for item in files]
        return f"Google Slides presentations (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error listing Google Slides presentations: {str(exc)}"


@mcp.tool()
async def search_slides_presentations(query: str, limit: int = 10) -> str:
    """Searches native Google Slides presentations by title."""
    try:
        params = _SearchSlidesInput.model_validate({"query": query, "limit": limit})
        safe_query = _escape_query(params.query)
        q = (
            f"mimeType='{GOOGLE_SLIDES_MIME}' and trashed=false and "
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
            return f"No Google Slides presentations found matching '{params.query}'"
        lines = [_format_presentation_line(item) for item in files]
        return (
            f"Google Slides search results for '{params.query}' (showing {len(lines)}):\n"
            + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error searching Google Slides presentations: {str(exc)}"


@mcp.tool()
async def get_slides_presentation_metadata(presentation_id: str) -> str:
    """Gets metadata for a native Google Slides presentation."""
    try:
        params = _PresentationIdInput.model_validate({"presentation_id": presentation_id})
        presentation, slides_err = await _slides_get(f"/presentations/{params.presentation_id}")
        if slides_err:
            return slides_err
        if not presentation:
            return "Presentation metadata not found."

        drive_data, drive_err = await _drive_get(
            f"/files/{params.presentation_id}",
            params={
                "fields": "modifiedTime,owners(displayName,emailAddress),webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if drive_err:
            drive_data = {}

        slides = presentation.get("slides", []) if isinstance(presentation, dict) else []
        slide_lines: list[str] = []
        for idx, slide in enumerate(slides[:50], start=1):
            object_id = slide.get("objectId", "-") if isinstance(slide, dict) else "-"
            page_elements = slide.get("pageElements", []) if isinstance(slide, dict) else []
            preview = _extract_slide_text(slide).replace("\n", " ").strip()
            if len(preview) > 80:
                preview = preview[:80].rstrip() + "..."
            preview = preview or "-"
            slide_lines.append(
                f"- Slide {idx} | Object ID: {object_id} | Elements: {len(page_elements)} | Preview: {preview}"
            )
        if len(slides) > 50:
            slide_lines.append(f"- ... truncated ({len(slides) - 50} more slides)")

        owners = drive_data.get("owners", []) if isinstance(drive_data, dict) else []
        owners_text = ", ".join(
            [
                f"{owner.get('displayName', '-')} <{owner.get('emailAddress', '-')}>"
                for owner in owners
                if isinstance(owner, dict)
            ]
        ) or "-"

        return (
            "Google Slides Metadata:\n"
            f"Presentation ID: {presentation.get('presentationId', params.presentation_id)}\n"
            f"Title: {presentation.get('title', '-')}\n"
            f"Total Slides: {len(slides)}\n"
            f"Modified: {(drive_data or {}).get('modifiedTime', '-')}\n"
            f"Owners: {owners_text}\n"
            f"Link: {(drive_data or {}).get('webViewLink', f'https://docs.google.com/presentation/d/{params.presentation_id}/edit')}\n"
            f"Slides:\n{chr(10).join(slide_lines) if slide_lines else '- (none)'}"
        )
    except Exception as exc:
        return f"Error getting Google Slides metadata: {str(exc)}"


@mcp.tool()
async def read_slides_presentation(presentation_id: str, max_chars: int = 8000) -> str:
    """Reads textual content from a native Google Slides presentation."""
    try:
        params = _ReadSlidesInput.model_validate(
            {"presentation_id": presentation_id, "max_chars": max_chars}
        )
        presentation, slides_err = await _slides_get(f"/presentations/{params.presentation_id}")
        if slides_err:
            return slides_err
        if not presentation:
            return "Presentation content not found."

        slide_blocks, joined_text = _extract_presentation_text(presentation)
        if not joined_text:
            return (
                "Google Slides Content:\n"
                f"Presentation ID: {params.presentation_id}\n"
                f"Title: {presentation.get('title', '-')}\n"
                "Content: (no text content found in slides)"
            )

        preview, truncated = _truncate_text(joined_text, params.max_chars)
        return (
            f"Google Slides Content: {presentation.get('title', '-')}\n"
            f"Presentation ID: {params.presentation_id}\n"
            f"Slides with Text: {len(slide_blocks)}\n"
            f"Text Length: {len(joined_text)}\n"
            f"Truncated: {'yes' if truncated else 'no'}\n"
            f"Content:\n{preview}"
        )
    except Exception as exc:
        return f"Error reading Google Slides content: {str(exc)}"


@mcp.tool()
async def create_slides_presentation(title: str, initial_slide_title: str = "") -> str:
    """Creates a new native Google Slides presentation, optionally with an initial text slide."""
    try:
        params = _CreatePresentationInput.model_validate(
            {"title": title, "initial_slide_title": initial_slide_title}
        )
        created, create_err = await _slides_post("/presentations", json_body={"title": params.title})
        if create_err:
            return create_err
        if not created:
            return "Failed to create Google Slides presentation."

        presentation_id = str(created.get("presentationId", "")).strip()
        if not presentation_id:
            return "Presentation created but API returned no presentationId."

        warning = ""
        initial_title = params.initial_slide_title.strip()
        if initial_title:
            requests, _ = _build_add_text_slide_requests(initial_title, "")
            _, add_err = await _slides_post(
                f"/presentations/{presentation_id}:batchUpdate",
                json_body={"requests": requests},
            )
            if add_err:
                warning = f"\nWarning: failed to add initial slide title ({add_err})"

        return (
            "Google Slides presentation created:\n"
            f"Presentation ID: {presentation_id}\n"
            f"Title: {created.get('title', params.title)}\n"
            f"Link: https://docs.google.com/presentation/d/{presentation_id}/edit"
            f"{warning}"
        )
    except Exception as exc:
        return f"Error creating Google Slides presentation: {str(exc)}"


@mcp.tool()
async def add_text_slide(presentation_id: str, title: str, body: str = "") -> str:
    """Adds a new text slide to an existing Google Slides presentation."""
    try:
        params = _AddTextSlideInput.model_validate(
            {"presentation_id": presentation_id, "title": title, "body": body}
        )
        requests, slide_id = _build_add_text_slide_requests(params.title, params.body)
        _, err = await _slides_post(
            f"/presentations/{params.presentation_id}:batchUpdate",
            json_body={"requests": requests},
        )
        if err:
            return err
        return (
            "Text slide added to Google Slides presentation:\n"
            f"Presentation ID: {params.presentation_id}\n"
            f"Slide Object ID: {slide_id}\n"
            f"Title: {params.title}\n"
            f"Body Added: {'yes' if params.body.strip() else 'no'}\n"
            f"Link: https://docs.google.com/presentation/d/{params.presentation_id}/edit"
        )
    except Exception as exc:
        return f"Error adding text slide: {str(exc)}"


@mcp.tool()
async def list_presentations(limit: int = 10, include_powerpoint: bool = True) -> str:
    """Lists presentations, optionally including PowerPoint files (.pptx/.ppt)."""
    try:
        params = _ListPresentationsInput.model_validate(
            {"limit": limit, "include_powerpoint": include_powerpoint}
        )
        data, err = await _drive_get(
            "/files",
            params={
                "q": _presentation_query(params.include_powerpoint),
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err
        files = data.get("files", []) if data else []
        if not files:
            return "No presentation files found."
        lines = [_format_presentation_file_line(item) for item in files]
        return (
            f"Presentation files (include_powerpoint={params.include_powerpoint}, showing {len(lines)}):\n"
            + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error listing presentation files: {str(exc)}"


@mcp.tool()
async def search_presentations(query: str, limit: int = 10, include_powerpoint: bool = True) -> str:
    """Searches presentations by title, optionally including .pptx/.ppt files."""
    try:
        params = _SearchPresentationsInput.model_validate(
            {
                "query": query,
                "limit": limit,
                "include_powerpoint": include_powerpoint,
            }
        )
        safe_query = _escape_query(params.query)
        q = _presentation_query(params.include_powerpoint) + f" and name contains '{safe_query}'"
        data, err = await _drive_get(
            "/files",
            params={
                "q": q,
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err
        files = data.get("files", []) if data else []
        if not files:
            return f"No presentation files found matching '{params.query}'"
        lines = [_format_presentation_file_line(item) for item in files]
        return (
            f"Presentation search results for '{params.query}' (showing {len(lines)}):\n"
            + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error searching presentation files: {str(exc)}"


@mcp.tool()
async def list_presentation_templates(
    limit: int = 10,
    folder_name: str = "Documents",
    name_contains: str = "template",
    include_powerpoint: bool = True,
) -> str:
    """Lists presentation template candidates from a Drive folder."""
    try:
        params = _ListPresentationTemplatesInput.model_validate(
            {
                "limit": limit,
                "folder_name": folder_name,
                "name_contains": name_contains,
                "include_powerpoint": include_powerpoint,
            }
        )
        folder_id, folder_err = await _resolve_folder_id_by_name(params.folder_name)
        if folder_err:
            return folder_err
        if not folder_id:
            return f"Drive folder '{params.folder_name}' was not found."

        query = _presentation_query(params.include_powerpoint) + f" and '{folder_id}' in parents"
        name_filter = params.name_contains.strip()
        if name_filter:
            query += f" and name contains '{_escape_query(name_filter)}'"

        data, err = await _drive_get(
            "/files",
            params={
                "q": query,
                "orderBy": "modifiedTime desc",
                "pageSize": params.limit,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink),nextPageToken",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if err:
            return err

        files = data.get("files", []) if isinstance(data, dict) else []
        if not files:
            filter_text = name_filter if name_filter else "(none)"
            return (
                "No presentation templates found.\n"
                f"Folder: {params.folder_name}\n"
                f"Filter: {filter_text}\n"
                f"include_powerpoint: {params.include_powerpoint}"
            )

        lines = [_format_presentation_file_line(item) for item in files]
        filter_text = name_filter if name_filter else "(none)"
        return (
            f"Presentation templates in folder '{params.folder_name}' "
            f"(include_powerpoint={params.include_powerpoint}, filter={filter_text}, showing {len(lines)}):\n"
            + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error listing presentation templates: {str(exc)}"


@mcp.tool()
async def get_presentation_metadata(file_id: str) -> str:
    """Gets metadata for a presentation file (Google Slides or .pptx/.ppt)."""
    try:
        params = _PresentationFileIdInput.model_validate({"file_id": file_id})
        drive_data, drive_err = await _drive_get(
            f"/files/{params.file_id}",
            params={
                "fields": (
                    "id,name,mimeType,modifiedTime,size,webViewLink,"
                    "owners(displayName,emailAddress),parents"
                ),
                "supportsAllDrives": "true",
            },
        )
        if drive_err:
            return drive_err
        if not drive_data:
            return "Presentation file metadata not found."

        mime_type = str(drive_data.get("mimeType", "")).strip()
        kind = _presentation_type_label(mime_type)
        owners = drive_data.get("owners", []) if isinstance(drive_data, dict) else []
        owners_text = ", ".join(
            [
                f"{owner.get('displayName', '-')} <{owner.get('emailAddress', '-')}>"
                for owner in owners
                if isinstance(owner, dict)
            ]
        ) or "-"

        slide_count = "-"
        content_hint = "-"
        if mime_type == GOOGLE_SLIDES_MIME:
            pres_data, pres_err = await _slides_get(f"/presentations/{params.file_id}")
            if pres_err:
                content_hint = f"(warning: {pres_err})"
            elif pres_data:
                slides = pres_data.get("slides", []) if isinstance(pres_data, dict) else []
                slide_count = str(len(slides))
                _, joined = _extract_presentation_text(pres_data)
                content_hint = f"text_length={len(joined)}"
        elif mime_type == PPTX_MIME:
            payload, bytes_err = await _drive_get_bytes(
                f"/files/{params.file_id}",
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            if bytes_err or payload is None:
                content_hint = f"(warning: {bytes_err or 'unable to read .pptx bytes'})"
            else:
                slide_total, text = _extract_pptx_text(payload)
                slide_count = str(slide_total)
                content_hint = f"text_length={len(text)}"
        elif mime_type == PPT_MIME:
            content_hint = "legacy .ppt cannot be read directly; convert to Google Slides first."

        return (
            "Presentation Metadata:\n"
            f"File ID: {drive_data.get('id', params.file_id)}\n"
            f"Name: {drive_data.get('name', '-')}\n"
            f"Type: {kind}\n"
            f"MIME Type: {mime_type or '-'}\n"
            f"Modified: {drive_data.get('modifiedTime', '-')}\n"
            f"Size: {drive_data.get('size', '-')}\n"
            f"Owners: {owners_text}\n"
            f"Link: {drive_data.get('webViewLink', '-')}\n"
            f"Slide Count: {slide_count}\n"
            f"Content Hint: {content_hint}"
        )
    except Exception as exc:
        return f"Error getting presentation metadata: {str(exc)}"


@mcp.tool()
async def read_powerpoint_document(file_id: str, max_chars: int = 8000) -> str:
    """Reads text from a .pptx file in Drive without converting it."""
    try:
        params = _ReadPowerPointInput.model_validate({"file_id": file_id, "max_chars": max_chars})
        meta, meta_err = await _drive_get(
            f"/files/{params.file_id}",
            params={"fields": "id,name,mimeType,webViewLink", "supportsAllDrives": "true"},
        )
        if meta_err:
            return meta_err
        if not meta:
            return "Presentation file not found."

        mime_type = str(meta.get("mimeType", "")).strip()
        if mime_type == GOOGLE_SLIDES_MIME:
            return (
                "File is a native Google Slides presentation. "
                "Use read_slides_presentation(presentation_id=...) for this file."
            )
        if mime_type == PPT_MIME:
            return (
                "Legacy .ppt format cannot be read directly. "
                "Use convert_powerpoint_to_google_slides(file_id=...) first."
            )
        if mime_type != PPTX_MIME:
            return (
                f"File MIME type '{mime_type or '-'}' is not supported by read_powerpoint_document. "
                f"Expected '{PPTX_MIME}'."
            )

        payload, bytes_err = await _drive_get_bytes(
            f"/files/{params.file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
        )
        if bytes_err:
            return bytes_err
        if payload is None:
            return "Failed to download .pptx file bytes."

        slide_total, extracted_text = _extract_pptx_text(payload)
        if not extracted_text:
            return (
                "PowerPoint Content:\n"
                f"File ID: {params.file_id}\n"
                f"File Name: {meta.get('name', '-')}\n"
                f"Slide Count: {slide_total}\n"
                "Content: (no text content found in slides)"
            )

        preview, truncated = _truncate_text(extracted_text, params.max_chars)
        return (
            "PowerPoint Content:\n"
            f"File ID: {params.file_id}\n"
            f"File Name: {meta.get('name', '-')}\n"
            f"Slide Count: {slide_total}\n"
            f"Text Length: {len(extracted_text)}\n"
            f"Truncated: {'yes' if truncated else 'no'}\n"
            f"Link: {meta.get('webViewLink', '-')}\n"
            f"Content:\n{preview}"
        )
    except Exception as exc:
        return f"Error reading PowerPoint document: {str(exc)}"


@mcp.tool()
async def convert_powerpoint_to_google_slides(
    file_id: str,
    new_title: str = "",
    move_to_parent: bool = True,
) -> str:
    """Converts an existing .pptx/.ppt file in Drive into a native Google Slides presentation."""
    try:
        params = _ConvertPowerPointInput.model_validate(
            {"file_id": file_id, "new_title": new_title, "move_to_parent": move_to_parent}
        )
        src_meta, src_err = await _drive_get(
            f"/files/{params.file_id}",
            params={
                "fields": "id,name,mimeType,parents,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        if src_err:
            return src_err
        if not src_meta:
            return "Source file not found."

        source_mime = str(src_meta.get("mimeType", "")).strip()
        if source_mime == GOOGLE_SLIDES_MIME:
            return (
                "File is already a native Google Slides presentation.\n"
                f"Presentation ID: {src_meta.get('id', params.file_id)}\n"
                f"Link: {src_meta.get('webViewLink', '-')}"
            )
        if source_mime not in PPT_MIMES:
            return (
                f"Source file MIME '{source_mime or '-'}' is not supported for conversion. "
                f"Expected one of: {PPTX_MIME}, {PPT_MIME}."
            )

        source_name = str(src_meta.get("name", "Untitled")).strip() or "Untitled"
        title = params.new_title.strip() or _strip_presentation_extension(source_name)
        parents = src_meta.get("parents", []) if isinstance(src_meta, dict) else []
        copy_body: dict = {"name": title, "mimeType": GOOGLE_SLIDES_MIME}
        if params.move_to_parent and isinstance(parents, list) and parents:
            copy_body["parents"] = parents

        copied, copy_err = await _drive_post_json(
            f"/files/{params.file_id}/copy",
            params={"supportsAllDrives": "true"},
            json_body=copy_body,
        )
        if not copy_err and copied and copied.get("id"):
            new_id = copied.get("id")
            return (
                "PowerPoint to Google Slides conversion completed:\n"
                f"Source File ID: {params.file_id}\n"
                f"Source Name: {source_name}\n"
                f"Presentation ID: {new_id}\n"
                f"Presentation Name: {copied.get('name', title)}\n"
                f"Link: https://docs.google.com/presentation/d/{new_id}/edit"
            )

        payload, bytes_err = await _drive_get_bytes(
            f"/files/{params.file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
        )
        if bytes_err:
            return (
                "Failed to convert via Drive copy and failed to download source bytes.\n"
                f"Copy Error: {copy_err or '-'}\n"
                f"Download Error: {bytes_err}"
            )
        if payload is None:
            return f"Failed to convert file: {copy_err or 'unknown error'}"

        upload_metadata: dict = {"name": title, "mimeType": GOOGLE_SLIDES_MIME}
        if params.move_to_parent and isinstance(parents, list) and parents:
            upload_metadata["parents"] = parents

        uploaded, upload_err = await _drive_upload_multipart(
            metadata=upload_metadata,
            media_bytes=payload,
            media_mime=source_mime,
            media_filename=source_name,
        )
        if upload_err:
            return (
                "Failed to convert via Drive copy and multipart upload fallback.\n"
                f"Copy Error: {copy_err or '-'}\n"
                f"Upload Error: {upload_err}"
            )

        new_id = uploaded.get("id", "-") if isinstance(uploaded, dict) else "-"
        return (
            "PowerPoint to Google Slides conversion completed (upload fallback):\n"
            f"Source File ID: {params.file_id}\n"
            f"Source Name: {source_name}\n"
            f"Presentation ID: {new_id}\n"
            f"Presentation Name: {(uploaded or {}).get('name', title)}\n"
            f"Link: https://docs.google.com/presentation/d/{new_id}/edit"
        )
    except Exception as exc:
        return f"Error converting PowerPoint to Google Slides: {str(exc)}"


@mcp.tool()
async def share_presentation_to_user(
    presentation_id: str,
    user_email: str,
    role: str = "reader",
    send_notification: bool = True,
    message: str = "",
) -> str:
    """Shares a presentation file (Google Slides or .pptx/.ppt) with one user."""
    try:
        params = _SharePresentationInput.model_validate(
            {
                "presentation_id": presentation_id,
                "user_email": user_email,
                "role": role,
                "send_notification": send_notification,
                "message": message,
            }
        )
        meta, meta_err = await _drive_get(
            f"/files/{params.presentation_id}",
            params={"fields": "id,name,mimeType,webViewLink", "supportsAllDrives": "true"},
        )
        if meta_err:
            return meta_err
        if not meta:
            return "Presentation file not found."

        mime_type = str(meta.get("mimeType", "")).strip()
        if mime_type not in ({GOOGLE_SLIDES_MIME} | PPT_MIMES):
            return (
                f"File MIME type '{mime_type or '-'}' is not a presentation type supported by "
                "share_presentation_to_user."
            )

        request_params = {
            "supportsAllDrives": "true",
            "sendNotificationEmail": "true" if params.send_notification else "false",
        }
        if params.send_notification and params.message:
            request_params["emailMessage"] = params.message

        perm, perm_err = await _drive_post_json(
            f"/files/{params.presentation_id}/permissions",
            params=request_params,
            json_body={
                "type": "user",
                "role": params.role,
                "emailAddress": params.user_email,
            },
        )
        if perm_err:
            return perm_err

        return (
            "Presentation share completed:\n"
            f"File ID: {params.presentation_id}\n"
            f"File Name: {meta.get('name', '-')}\n"
            f"Type: {_presentation_type_label(mime_type)}\n"
            f"Shared With: {params.user_email}\n"
            f"Role: {params.role}\n"
            f"Notification Sent: {params.send_notification}\n"
            f"Permission ID: {(perm or {}).get('id', '-')}\n"
            f"Link: {meta.get('webViewLink', '-')}"
        )
    except Exception as exc:
        return f"Error sharing presentation: {str(exc)}"


@mcp.tool()
async def export_slides_presentation(
    presentation_id: str,
    export_format: str = "pdf",
    max_chars: int = 8000,
) -> str:
    """Exports a native Google Slides presentation to a supported format."""
    try:
        params = _ExportSlidesInput.model_validate(
            {
                "presentation_id": presentation_id,
                "export_format": export_format,
                "max_chars": max_chars,
            }
        )
        meta, meta_err = await _drive_get(
            f"/files/{params.presentation_id}",
            params={"fields": "id,name,mimeType,webViewLink", "supportsAllDrives": "true"},
        )
        if meta_err:
            return meta_err
        if not meta:
            return "Presentation file not found."

        mime_type = str(meta.get("mimeType", "")).strip()
        if mime_type != GOOGLE_SLIDES_MIME:
            if mime_type in PPT_MIMES:
                return (
                    "File is a PowerPoint file (.pptx/.ppt), not a native Google Slides presentation. "
                    "Use convert_powerpoint_to_google_slides(file_id=...) first, then export."
                )
            return (
                f"File MIME type '{mime_type or '-'}' is not exportable by export_slides_presentation. "
                f"Expected '{GOOGLE_SLIDES_MIME}'."
            )

        export_meta = PRESENTATION_EXPORT_FORMATS[params.export_format]
        payload, export_err = await _drive_get_bytes(
            f"/files/{params.presentation_id}/export",
            params={"mimeType": str(export_meta["mime_type"])},
        )
        if export_err:
            return export_err
        if payload is None:
            return "Failed to export Google Slides presentation."

        size = len(payload)
        is_binary = bool(export_meta["binary"])
        base = (
            "Google Slides export completed:\n"
            f"Presentation ID: {params.presentation_id}\n"
            f"Presentation Name: {meta.get('name', '-')}\n"
            f"Format: {params.export_format}\n"
            f"Export MIME: {export_meta['mime_type']}\n"
            f"Byte Size: {size}\n"
            f"Source Link: {meta.get('webViewLink', '-')}"
        )
        if is_binary:
            return (
                f"{base}\n"
                "Preview: (binary export, preview omitted).\n"
                "Tip: use format=txt for text preview."
            )

        decoded = payload.decode("utf-8", errors="replace")
        preview, truncated = _truncate_text(decoded, params.max_chars)
        return (
            f"{base}\n"
            f"Preview Truncated: {'yes' if truncated else 'no'}\n"
            f"Preview:\n{preview}"
        )
    except Exception as exc:
        return f"Error exporting Google Slides presentation: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
