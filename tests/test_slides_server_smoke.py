from io import BytesIO
import zipfile

import pytest

from chat_google.mcp_servers import slides_server


def _build_pptx_bytes(text: str = "Hello from pptx") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
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
        zf.writestr("ppt/slides/slide1.xml", xml)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_slides_tools_smoke(monkeypatch):
    async def fake_drive_get(path, params=None):
        if path == "/files" and "mimeType='application/vnd.google-apps.folder'" in (params or {}).get("q", ""):
            return ({"files": [{"id": "folder-docs", "name": "Documents"}]}, None)
        if path == "/files" and "name contains" not in (params or {}).get("q", ""):
            return (
                {
                    "files": [
                        {
                            "id": "pres1",
                            "name": "Quarterly Deck",
                            "mimeType": slides_server.GOOGLE_SLIDES_MIME,
                            "modifiedTime": "2026-02-14T08:00:00Z",
                            "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
                        },
                        {
                            "id": "pptx1",
                            "name": "Pitch.pptx",
                            "mimeType": slides_server.PPTX_MIME,
                            "modifiedTime": "2026-02-13T08:00:00Z",
                            "webViewLink": "https://drive.google.com/file/d/pptx1/view",
                        },
                    ]
                },
                None,
            )
        if path == "/files" and "name contains" in (params or {}).get("q", ""):
            return (
                {
                    "files": [
                        {
                            "id": "pres1",
                            "name": "Quarterly Deck",
                            "mimeType": slides_server.GOOGLE_SLIDES_MIME,
                            "modifiedTime": "2026-02-14T08:00:00Z",
                            "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
                        }
                    ]
                },
                None,
            )
        if path == "/files/pres1":
            return (
                {
                    "id": "pres1",
                    "name": "Quarterly Deck",
                    "mimeType": slides_server.GOOGLE_SLIDES_MIME,
                    "modifiedTime": "2026-02-14T08:00:00Z",
                    "size": "45678",
                    "webViewLink": "https://docs.google.com/presentation/d/pres1/edit",
                    "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                    "parents": ["parent-1"],
                },
                None,
            )
        if path == "/files/pptx1":
            return (
                {
                    "id": "pptx1",
                    "name": "Pitch.pptx",
                    "mimeType": slides_server.PPTX_MIME,
                    "modifiedTime": "2026-02-13T08:00:00Z",
                    "size": "12345",
                    "webViewLink": "https://drive.google.com/file/d/pptx1/view",
                    "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                    "parents": ["parent-1"],
                },
                None,
            )
        return {}, None

    async def fake_slides_get(path, params=None):
        if path == "/presentations/pres1":
            return (
                {
                    "presentationId": "pres1",
                    "title": "Quarterly Deck",
                    "slides": [
                        {
                            "objectId": "s1",
                            "pageElements": [
                                {
                                    "shape": {
                                        "text": {
                                            "textElements": [
                                                {"textRun": {"content": "Revenue summary"}}
                                            ]
                                        }
                                    }
                                }
                            ],
                        }
                    ],
                },
                None,
            )
        return {}, None

    async def fake_drive_get_bytes(path, params=None):
        if path == "/files/pptx1" and (params or {}).get("alt") == "media":
            return _build_pptx_bytes("Pitch highlights"), None
        if path == "/files/pres1/export":
            return b"slides export text", None
        return b"", None

    async def fake_drive_post_json(path, params=None, json_body=None):
        if path == "/files/pptx1/copy":
            return {"id": "pres-new", "name": "Pitch"}, None
        if path == "/files/pres1/permissions":
            return {"id": "perm1"}, None
        return {}, None

    async def fake_slides_post(path, json_body=None):
        if path == "/presentations":
            return {"presentationId": "pres-created", "title": "New Deck"}, None
        if path in {
            "/presentations/pres-created:batchUpdate",
            "/presentations/pres1:batchUpdate",
        }:
            return {"replies": [{}]}, None
        return {}, None

    monkeypatch.setattr(slides_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(slides_server, "_slides_get", fake_slides_get)
    monkeypatch.setattr(slides_server, "_drive_get_bytes", fake_drive_get_bytes)
    monkeypatch.setattr(slides_server, "_drive_post_json", fake_drive_post_json)
    monkeypatch.setattr(slides_server, "_slides_post", fake_slides_post)

    listed_native = await slides_server.list_slides_presentations()
    searched_native = await slides_server.search_slides_presentations("Quarterly")
    metadata_native = await slides_server.get_slides_presentation_metadata("pres1")
    read_native = await slides_server.read_slides_presentation("pres1")
    created = await slides_server.create_slides_presentation("New Deck", initial_slide_title="Intro")
    added_slide = await slides_server.add_text_slide("pres1", "Agenda", body="Item 1")
    listed_unified = await slides_server.list_presentations(limit=3, include_powerpoint=True)
    template_list = await slides_server.list_presentation_templates(limit=3, folder_name="Documents")
    searched_unified = await slides_server.search_presentations("Quarterly", include_powerpoint=True)
    metadata_unified = await slides_server.get_presentation_metadata("pptx1")
    read_pptx = await slides_server.read_powerpoint_document("pptx1")
    converted = await slides_server.convert_powerpoint_to_google_slides("pptx1")
    shared = await slides_server.share_presentation_to_user("pres1", "alice@example.com")
    exported = await slides_server.export_slides_presentation("pres1", export_format="txt")

    assert "Google Slides presentations" in listed_native
    assert "Google Slides search results" in searched_native
    assert "Google Slides Metadata:" in metadata_native
    assert "Google Slides Content: Quarterly Deck" in read_native
    assert "Google Slides presentation created:" in created
    assert "Text slide added to Google Slides presentation:" in added_slide
    assert "Presentation files (include_powerpoint=True" in listed_unified
    assert "Presentation templates in folder 'Documents'" in template_list
    assert "Presentation search results for 'Quarterly'" in searched_unified
    assert "Presentation Metadata:" in metadata_unified
    assert "PowerPoint Content:" in read_pptx
    assert "conversion completed" in converted.lower()
    assert "Presentation share completed:" in shared
    assert "Google Slides export completed:" in exported
