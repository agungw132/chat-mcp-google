from io import BytesIO
import zipfile

import pytest

from chat_google.mcp_servers import slides_server


def _build_pptx_bytes(slide_texts: list[str] | None = None) -> bytes:
    texts = slide_texts or ["Slide one", "Slide two"]
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, text in enumerate(texts, start=1):
            xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""
            zf.writestr(f"ppt/slides/slide{idx}.xml", xml)
    return buf.getvalue()


def test_get_access_token_missing(monkeypatch):
    monkeypatch.setattr(slides_server, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(slides_server, "_CACHED_ACCESS_TOKEN", None)
    monkeypatch.setattr(slides_server, "_CACHED_ACCESS_TOKEN_EXPIRES_AT", None)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError):
        slides_server._get_access_token()


def test_get_access_token_uses_refresh_flow(monkeypatch):
    monkeypatch.setattr(slides_server, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(slides_server, "_CACHED_ACCESS_TOKEN", None)
    monkeypatch.setattr(slides_server, "_CACHED_ACCESS_TOKEN_EXPIRES_AT", None)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")

    def fake_refresh_access_token(refresh_token, client_id, client_secret):
        assert refresh_token == "refresh-token"
        assert client_id == "client-id"
        assert client_secret == "client-secret"
        return "refreshed-access-token", 3600

    monkeypatch.setattr(slides_server, "_refresh_access_token", fake_refresh_access_token)
    token = slides_server._get_access_token()
    assert token == "refreshed-access-token"


@pytest.mark.asyncio
async def test_list_slides_presentations(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files"
        return (
            {
                "files": [
                    {
                        "id": "pres1",
                        "name": "Quarterly Update",
                        "modifiedTime": "2026-02-14T09:00:00Z",
                        "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.list_slides_presentations(limit=1)
    assert "Google Slides presentations (showing 1):" in result
    assert "Quarterly Update" in result
    assert "pres1" in result


@pytest.mark.asyncio
async def test_search_slides_presentations_no_results(monkeypatch):
    async def fake_drive_get(path, params=None):
        return {"files": []}, None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.search_slides_presentations("Roadmap")
    assert result == "No Google Slides presentations found matching 'Roadmap'"


@pytest.mark.asyncio
async def test_get_slides_presentation_metadata(monkeypatch):
    async def fake_slides_get(path, params=None):
        assert path == "/presentations/pres1"
        return (
            {
                "presentationId": "pres1",
                "title": "Quarterly Update",
                "slides": [
                    {
                        "objectId": "s1",
                        "pageElements": [
                            {
                                "shape": {
                                    "text": {"textElements": [{"textRun": {"content": "Title A"}}]}
                                }
                            }
                        ],
                    }
                ],
            },
            None,
        )

    async def fake_drive_get(path, params=None):
        assert path == "/files/pres1"
        return (
            {
                "modifiedTime": "2026-02-14T09:00:00Z",
                "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_slides_get", fake_slides_get)
    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.get_slides_presentation_metadata("pres1")
    assert "Google Slides Metadata:" in result
    assert "Title: Quarterly Update" in result
    assert "Total Slides: 1" in result
    assert "Alice <alice@example.com>" in result


@pytest.mark.asyncio
async def test_read_slides_presentation_truncated(monkeypatch):
    async def fake_slides_get(path, params=None):
        return (
            {
                "presentationId": "pres1",
                "title": "Quarterly Update",
                "slides": [
                    {
                        "pageElements": [
                            {
                                "shape": {
                                    "text": {
                                        "textElements": [{"textRun": {"content": "A" * 400}}]
                                    }
                                }
                            }
                        ]
                    }
                ],
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_slides_get", fake_slides_get)
    result = await slides_server.read_slides_presentation("pres1", max_chars=200)
    assert "Google Slides Content: Quarterly Update" in result
    assert "Truncated: yes" in result


@pytest.mark.asyncio
async def test_create_slides_presentation_with_initial_slide(monkeypatch):
    calls = []

    async def fake_slides_post(path, json_body=None):
        calls.append((path, json_body))
        if path == "/presentations":
            return {"presentationId": "pres1", "title": "Deck"}, None
        if path == "/presentations/pres1:batchUpdate":
            return {"replies": [{}]}, None
        return {}, None

    monkeypatch.setattr(slides_server, "_slides_post", fake_slides_post)
    result = await slides_server.create_slides_presentation("Deck", initial_slide_title="Intro")
    assert "Google Slides presentation created:" in result
    assert "Presentation ID: pres1" in result
    assert calls[0][0] == "/presentations"
    assert calls[1][0] == "/presentations/pres1:batchUpdate"


@pytest.mark.asyncio
async def test_add_text_slide(monkeypatch):
    async def fake_slides_post(path, json_body=None):
        assert path == "/presentations/pres1:batchUpdate"
        requests = json_body["requests"]
        assert any("createSlide" in req for req in requests)
        assert any("insertText" in req for req in requests)
        return {"replies": [{}]}, None

    monkeypatch.setattr(slides_server, "_slides_post", fake_slides_post)
    result = await slides_server.add_text_slide("pres1", "Agenda", body="Line one")
    assert "Text slide added to Google Slides presentation:" in result
    assert "Presentation ID: pres1" in result


@pytest.mark.asyncio
async def test_list_presentations_include_powerpoint(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files"
        assert "application/vnd.ms-powerpoint" in params["q"]
        return (
            {
                "files": [
                    {
                        "id": "p1",
                        "name": "Deck.pptx",
                        "mimeType": slides_server.PPTX_MIME,
                        "modifiedTime": "2026-02-14T09:00:00Z",
                        "webViewLink": "https://drive.google.com/file/d/p1/view",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.list_presentations(limit=1, include_powerpoint=True)
    assert "Presentation files (include_powerpoint=True, showing 1):" in result
    assert "Type: powerpoint_pptx" in result


@pytest.mark.asyncio
async def test_list_presentation_templates(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files"
        query = (params or {}).get("q", "")
        if "mimeType='application/vnd.google-apps.folder'" in query:
            return {"files": [{"id": "folder-docs", "name": "Documents"}]}, None
        assert "'folder-docs' in parents" in query
        assert "name contains 'template'" in query
        return (
            {
                "files": [
                    {
                        "id": "tmpl-slide-1",
                        "name": "Template Pitch.pptx",
                        "mimeType": slides_server.PPTX_MIME,
                        "modifiedTime": "2026-02-14T09:00:00Z",
                        "webViewLink": "https://drive.google.com/file/d/tmpl-slide-1/view",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.list_presentation_templates(
        limit=3,
        folder_name="Documents",
        name_contains="template",
        include_powerpoint=True,
    )
    assert "Presentation templates in folder 'Documents'" in result
    assert "Template Pitch.pptx" in result
    assert "Type: powerpoint_pptx" in result


@pytest.mark.asyncio
async def test_get_presentation_metadata_pptx(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files/p1"
        return (
            {
                "id": "p1",
                "name": "Deck.pptx",
                "mimeType": slides_server.PPTX_MIME,
                "modifiedTime": "2026-02-14T09:00:00Z",
                "size": "2345",
                "webViewLink": "https://drive.google.com/file/d/p1/view",
                "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
            },
            None,
        )

    async def fake_drive_get_bytes(path, params=None):
        return _build_pptx_bytes(["Alpha", "Beta"]), None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_drive_get_bytes", fake_drive_get_bytes)
    result = await slides_server.get_presentation_metadata("p1")
    assert "Presentation Metadata:" in result
    assert "Type: powerpoint_pptx" in result
    assert "Slide Count: 2" in result


@pytest.mark.asyncio
async def test_read_powerpoint_document_pptx(monkeypatch):
    async def fake_drive_get(path, params=None):
        return (
            {
                "id": "p1",
                "name": "Deck.pptx",
                "mimeType": slides_server.PPTX_MIME,
                "webViewLink": "https://drive.google.com/file/d/p1/view",
            },
            None,
        )

    async def fake_drive_get_bytes(path, params=None):
        return _build_pptx_bytes(["Alpha", "Beta"]), None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_drive_get_bytes", fake_drive_get_bytes)
    result = await slides_server.read_powerpoint_document("p1", max_chars=400)
    assert "PowerPoint Content:" in result
    assert "Slide Count: 2" in result
    assert "Alpha" in result


@pytest.mark.asyncio
async def test_read_powerpoint_document_ppt_returns_guidance(monkeypatch):
    async def fake_drive_get(path, params=None):
        return (
            {
                "id": "l1",
                "name": "Legacy.ppt",
                "mimeType": slides_server.PPT_MIME,
                "webViewLink": "https://drive.google.com/file/d/l1/view",
            },
            None,
        )

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    result = await slides_server.read_powerpoint_document("l1")
    assert "Legacy .ppt format cannot be read directly." in result


@pytest.mark.asyncio
async def test_convert_powerpoint_to_google_slides(monkeypatch):
    async def fake_drive_get(path, params=None):
        return (
            {
                "id": "p1",
                "name": "Deck.pptx",
                "mimeType": slides_server.PPTX_MIME,
                "parents": ["folder-a"],
            },
            None,
        )

    async def fake_drive_post_json(path, params=None, json_body=None):
        assert path == "/files/p1/copy"
        assert json_body["mimeType"] == slides_server.GOOGLE_SLIDES_MIME
        return {"id": "pres-new", "name": "Deck"}, None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_drive_post_json", fake_drive_post_json)
    result = await slides_server.convert_powerpoint_to_google_slides("p1")
    assert "conversion completed" in result.lower()
    assert "Presentation ID: pres-new" in result


@pytest.mark.asyncio
async def test_share_presentation_to_user(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files/pres1"
        return (
            {
                "id": "pres1",
                "name": "Deck",
                "mimeType": slides_server.GOOGLE_SLIDES_MIME,
                "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
            },
            None,
        )

    async def fake_drive_post_json(path, params=None, json_body=None):
        assert path == "/files/pres1/permissions"
        assert json_body["emailAddress"] == "alice@example.com"
        assert json_body["role"] == "reader"
        return {"id": "perm1"}, None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_drive_post_json", fake_drive_post_json)
    result = await slides_server.share_presentation_to_user("pres1", "alice@example.com")
    assert "Presentation share completed:" in result
    assert "Permission ID: perm1" in result


@pytest.mark.asyncio
async def test_export_slides_presentation_txt(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files/pres1"
        return (
            {
                "id": "pres1",
                "name": "Deck",
                "mimeType": slides_server.GOOGLE_SLIDES_MIME,
                "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
            },
            None,
        )

    async def fake_drive_get_bytes(path, params=None):
        assert path == "/files/pres1/export"
        assert params["mimeType"] == "text/plain"
        return b"Slide text preview", None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_drive_get_bytes", fake_drive_get_bytes)
    result = await slides_server.export_slides_presentation("pres1", export_format="txt", max_chars=300)
    assert "Google Slides export completed:" in result
    assert "Format: txt" in result
    assert "Slide text preview" in result
