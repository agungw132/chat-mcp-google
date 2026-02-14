import pytest

from chat_google.mcp_servers import docs_server


@pytest.mark.asyncio
async def test_docs_tools_smoke(monkeypatch):
    async def fake_drive_get(path, params=None):
        if path == "/files" and "name contains" not in (params or {}).get("q", ""):
            return (
                {
                    "files": [
                        {
                            "id": "doc1",
                            "name": "Notes",
                            "modifiedTime": "2026-02-14T08:00:00Z",
                            "webViewLink": "https://docs.google.com/document/d/doc1/edit",
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
                    "modifiedTime": "2026-02-14T08:00:00Z",
                    "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                    "webViewLink": "https://docs.google.com/document/d/doc1/edit",
                    "name": "Notes",
                },
                None,
            )
        return {}, None

    async def fake_drive_get_bytes(path, params=None):
        if path == "/files/doc1/export":
            return b"Hello from docs export", None
        return b"", None

    async def fake_drive_post_json(path, params=None, json_body=None):
        if path == "/files/doc1/permissions":
            return {"id": "perm1"}, None
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
    assert "Structured content appended to Google Docs document" in structured
    assert "Safe text replacement completed in Google Docs document" in safe_replaced
