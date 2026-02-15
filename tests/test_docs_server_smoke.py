import pytest
from io import BytesIO
import zipfile

from chat_google.mcp_servers import docs_server


def _build_docx_bytes(text: str = "Hello from docx\nSecond line") -> bytes:
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text.splitlines()[0]}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{text.splitlines()[-1]}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_docs_tools_smoke(monkeypatch):
    async def fake_drive_get(path, params=None):
        if path == "/files" and "mimeType='application/vnd.google-apps.folder'" in (params or {}).get("q", ""):
            return ({"files": [{"id": "folder-docs", "name": "Documents"}]}, None)
        if path == "/files" and "name contains" not in (params or {}).get("q", ""):
            return (
                {
                    "files": [
                        {
                            "id": "doc1",
                            "name": "Notes",
                            "mimeType": docs_server.GOOGLE_DOC_MIME,
                            "modifiedTime": "2026-02-14T08:00:00Z",
                            "webViewLink": "https://docs.google.com/document/d/doc1/edit",
                        },
                        {
                            "id": "w1",
                            "name": "Spec.docx",
                            "mimeType": docs_server.DOCX_MIME,
                            "modifiedTime": "2026-02-13T08:00:00Z",
                            "webViewLink": "https://drive.google.com/file/d/w1/view",
                        }
                    ]
                },
                None,
            )
        if path == "/files" and "name contains" in (params or {}).get("q", ""):
            return (
                {
                    "files": [
                        {
                            "id": "doc1",
                            "name": "Notes",
                            "mimeType": docs_server.GOOGLE_DOC_MIME,
                            "modifiedTime": "2026-02-14T08:00:00Z",
                            "webViewLink": "https://docs.google.com/document/d/doc1/edit",
                        }
                    ]
                },
                None,
            )
        if path == "/files/doc1":
            return (
                {
                    "id": "doc1",
                    "modifiedTime": "2026-02-14T08:00:00Z",
                    "mimeType": docs_server.GOOGLE_DOC_MIME,
                    "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                    "webViewLink": "https://docs.google.com/document/d/doc1/edit",
                    "name": "Notes",
                },
                None,
            )
        if path == "/files/w1":
            return (
                {
                    "id": "w1",
                    "name": "Spec.docx",
                    "mimeType": docs_server.DOCX_MIME,
                    "modifiedTime": "2026-02-13T08:00:00Z",
                    "size": "2345",
                    "webViewLink": "https://drive.google.com/file/d/w1/view",
                    "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                },
                None,
            )
        return {}, None

    async def fake_drive_get_bytes(path, params=None):
        if path == "/files/doc1/export":
            return b"Hello from docs export", None
        if path == "/files/w1" and (params or {}).get("alt") == "media":
            return _build_docx_bytes("Alpha\nBeta"), None
        return b"", None

    async def fake_drive_post_json(path, params=None, json_body=None):
        if path == "/files/doc1/permissions":
            return {"id": "perm1"}, None
        if path == "/files/w1/copy":
            return {"id": "doc-conv", "name": "Spec"}, None
        return {}, None

    async def fake_docs_get(path):
        return (
            {
                "title": "Notes",
                "documentId": "doc1",
                "revisionId": "r1",
                "body": {
                    "content": [
                        {"endIndex": 1},
                        {"paragraph": {"elements": [{"textRun": {"content": "Hello world"}}]}},
                        {"endIndex": 12},
                    ]
                },
            },
            None,
        )

    async def fake_docs_post(path, json_body=None):
        if path == "/documents":
            return {"title": "New Notes", "documentId": "doc-new", "revisionId": "r2"}, None
        if path in {"/documents/doc-new:batchUpdate", "/documents/doc1:batchUpdate"}:
            return {"replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}, None
        return {"replies": []}, None

    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    monkeypatch.setattr(docs_server, "_drive_get_bytes", fake_drive_get_bytes)
    monkeypatch.setattr(docs_server, "_drive_post_json", fake_drive_post_json)
    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    monkeypatch.setattr(docs_server, "_docs_post", fake_docs_post)

    listed = await docs_server.list_docs_documents()
    searched = await docs_server.search_docs_documents("Notes")
    metadata = await docs_server.get_docs_document_metadata("doc1")
    read = await docs_server.read_docs_document("doc1")
    created = await docs_server.create_docs_document("New Notes", initial_content="Intro")
    appended = await docs_server.append_docs_text("doc1", "\nmore")
    replaced = await docs_server.replace_docs_text("doc1", "Hello", "Hi")
    shared = await docs_server.share_docs_to_user("doc1", "alice@example.com")
    exported = await docs_server.export_docs_document("doc1", export_format="txt")
    listed_unified = await docs_server.list_documents(limit=3, include_word=True)
    templates = await docs_server.list_document_templates(limit=3, folder_name="Documents")
    searched_unified = await docs_server.search_documents("Notes", include_word=True)
    metadata_unified = await docs_server.get_document_metadata("w1")
    read_word = await docs_server.read_word_document("w1")
    converted = await docs_server.convert_word_to_google_doc("w1")
    structured = await docs_server.append_docs_structured_content(
        "doc1",
        heading="Agenda",
        bullet_items=["Item A"],
        numbered_items=["Step 1"],
    )
    safe_replaced = await docs_server.replace_docs_text_if_revision(
        "doc1",
        expected_revision_id="r1",
        find_text="Hello",
        replace_text="Hi",
    )

    assert "Google Docs Documents" in listed
    assert "Google Docs search results" in searched
    assert "Google Docs Metadata" in metadata
    assert "Google Docs Content: Notes" in read
    assert "Google Docs document created" in created
    assert "Text appended to Google Docs document" in appended
    assert "Text replacement completed in Google Docs document" in replaced
    assert "Google Docs sharing completed" in shared
    assert "Google Docs export completed" in exported
    assert "Document files (include_word=True" in listed_unified
    assert "Document templates in folder 'Documents'" in templates
    assert "Document search results for 'Notes'" in searched_unified
    assert "Document Metadata:" in metadata_unified
    assert "Word Document Content:" in read_word
    assert "Word to Google Docs conversion completed:" in converted
    assert "Structured content appended to Google Docs document" in structured
    assert "Safe text replacement completed in Google Docs document" in safe_replaced
