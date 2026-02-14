import pytest

from chat_google.mcp_servers import docs_server


def test_get_access_token_missing(monkeypatch):
    monkeypatch.setattr(docs_server, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(docs_server, "_CACHED_ACCESS_TOKEN", None)
    monkeypatch.setattr(docs_server, "_CACHED_ACCESS_TOKEN_EXPIRES_AT", None)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError):
        docs_server._get_access_token()


def test_get_access_token_uses_refresh_flow(monkeypatch):
    monkeypatch.setattr(docs_server, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(docs_server, "_CACHED_ACCESS_TOKEN", None)
    monkeypatch.setattr(docs_server, "_CACHED_ACCESS_TOKEN_EXPIRES_AT", None)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")

    def fake_refresh_access_token(refresh_token, client_id, client_secret):
        assert refresh_token == "refresh-token"
        assert client_id == "client-id"
        assert client_secret == "client-secret"
        return "refreshed-access-token", 3600

    monkeypatch.setattr(docs_server, "_refresh_access_token", fake_refresh_access_token)
    token = docs_server._get_access_token()
    assert token == "refreshed-access-token"


@pytest.mark.asyncio
async def test_list_docs_documents(monkeypatch):
    async def fake_drive_get(path, params=None):
        assert path == "/files"
        return (
            {
                "files": [
                    {
                        "id": "doc1",
                        "name": "Project Plan",
                        "modifiedTime": "2026-02-14T09:00:00Z",
                        "webViewLink": "https://docs.google.com/document/d/doc1/edit",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    result = await docs_server.list_docs_documents(limit=1)
    assert "Google Docs Documents (showing 1):" in result
    assert "Project Plan" in result
    assert "doc1" in result


@pytest.mark.asyncio
async def test_search_docs_documents_no_results(monkeypatch):
    async def fake_drive_get(path, params=None):
        return {"files": []}, None

    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    result = await docs_server.search_docs_documents("Quarterly")
    assert result == "No Google Docs documents found matching 'Quarterly'"


@pytest.mark.asyncio
async def test_get_docs_document_metadata(monkeypatch):
    async def fake_docs_get(path):
        assert path == "/documents/doc1"
        return {"title": "Project Plan", "documentId": "doc1", "revisionId": "rev-1"}, None

    async def fake_drive_get(path, params=None):
        assert path == "/files/doc1"
        return (
            {
                "modifiedTime": "2026-02-14T09:00:00Z",
                "owners": [{"displayName": "Alice", "emailAddress": "alice@example.com"}],
                "webViewLink": "https://docs.google.com/document/d/doc1/edit",
            },
            None,
        )

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    result = await docs_server.get_docs_document_metadata("doc1")
    assert "Google Docs Metadata:" in result
    assert "Title: Project Plan" in result
    assert "Revision ID: rev-1" in result
    assert "Alice <alice@example.com>" in result


@pytest.mark.asyncio
async def test_read_docs_document_truncated(monkeypatch):
    async def fake_docs_get(path):
        return (
            {
                "title": "Long Doc",
                "body": {
                    "content": [
                        {"paragraph": {"elements": [{"textRun": {"content": "A" * 260}}]}}
                    ]
                },
            },
            None,
        )

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    result = await docs_server.read_docs_document("doc1", max_chars=200)
    assert "Google Docs Content: Long Doc" in result
    assert "[Truncated]" in result


@pytest.mark.asyncio
async def test_create_docs_document_with_initial_content(monkeypatch):
    calls = []

    async def fake_docs_post(path, json_body=None):
        calls.append((path, json_body))
        if path == "/documents":
            return {"title": "New Doc", "documentId": "doc-new", "revisionId": "1"}, None
        if path == "/documents/doc-new:batchUpdate":
            return {"replies": []}, None
        return None, "unexpected"

    monkeypatch.setattr(docs_server, "_docs_post", fake_docs_post)
    result = await docs_server.create_docs_document("New Doc", initial_content="Hello")
    assert "Google Docs document created:" in result
    assert "Document ID: doc-new" in result
    assert calls[0][0] == "/documents"
    assert calls[1][0] == "/documents/doc-new:batchUpdate"


@pytest.mark.asyncio
async def test_append_docs_text(monkeypatch):
    async def fake_docs_get(path):
        return (
            {
                "body": {
                    "content": [
                        {"endIndex": 1},
                        {"endIndex": 10},
                    ]
                }
            },
            None,
        )

    async def fake_docs_post(path, json_body=None):
        assert path == "/documents/doc1:batchUpdate"
        requests = json_body["requests"]
        assert requests[0]["insertText"]["location"]["index"] == 9
        assert requests[0]["insertText"]["text"] == " appended"
        return {"replies": []}, None

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    monkeypatch.setattr(docs_server, "_docs_post", fake_docs_post)
    result = await docs_server.append_docs_text("doc1", " appended")
    assert "Text appended to Google Docs document:" in result
    assert "Inserted At Index: 9" in result


@pytest.mark.asyncio
async def test_replace_docs_text(monkeypatch):
    async def fake_docs_post(path, json_body=None):
        assert path == "/documents/doc1:batchUpdate"
        payload = json_body["requests"][0]["replaceAllText"]
        assert payload["containsText"]["text"] == "old"
        assert payload["replaceText"] == "new"
        return {"replies": [{"replaceAllText": {"occurrencesChanged": 2}}]}, None

    monkeypatch.setattr(docs_server, "_docs_post", fake_docs_post)
    result = await docs_server.replace_docs_text("doc1", "old", "new")
    assert "Text replacement completed in Google Docs document:" in result
    assert "Occurrences Changed: 2" in result


@pytest.mark.asyncio
async def test_read_docs_document_propagates_error(monkeypatch):
    async def fake_docs_get(path):
        return None, "Error: Google Docs API request failed: 403 - forbidden"

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    result = await docs_server.read_docs_document("doc1")
    assert result == "Error: Google Docs API request failed: 403 - forbidden"


@pytest.mark.asyncio
async def test_share_docs_to_user(monkeypatch):
    async def fake_drive_post_json(path, params=None, json_body=None):
        assert path == "/files/doc1/permissions"
        assert json_body["type"] == "user"
        assert json_body["role"] == "reader"
        assert json_body["emailAddress"] == "alice@example.com"
        assert params["sendNotificationEmail"] == "true"
        return {"id": "perm1"}, None

    async def fake_drive_get(path, params=None):
        assert path == "/files/doc1"
        return {"name": "Project Plan", "webViewLink": "https://docs.google.com/document/d/doc1/edit"}, None

    monkeypatch.setattr(docs_server, "_drive_post_json", fake_drive_post_json)
    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    result = await docs_server.share_docs_to_user("doc1", "alice@example.com")
    assert "Google Docs sharing completed:" in result
    assert "Permission ID: perm1" in result


@pytest.mark.asyncio
async def test_export_docs_document_txt(monkeypatch):
    async def fake_drive_get_bytes(path, params=None):
        assert path == "/files/doc1/export"
        assert params["mimeType"] == "text/plain"
        return b"Hello from export", None

    async def fake_drive_get(path, params=None):
        assert path == "/files/doc1"
        return {"name": "Project Plan", "webViewLink": "https://docs.google.com/document/d/doc1/edit"}, None

    monkeypatch.setattr(docs_server, "_drive_get_bytes", fake_drive_get_bytes)
    monkeypatch.setattr(docs_server, "_drive_get", fake_drive_get)
    result = await docs_server.export_docs_document("doc1", export_format="txt", max_chars=200)
    assert "Google Docs export completed:" in result
    assert "Format: txt" in result
    assert "Hello from export" in result


@pytest.mark.asyncio
async def test_append_docs_structured_content(monkeypatch):
    async def fake_docs_get(path):
        assert path == "/documents/doc1"
        return {"body": {"content": [{"endIndex": 1}, {"endIndex": 15}]}}, None

    async def fake_docs_post(path, json_body=None):
        assert path == "/documents/doc1:batchUpdate"
        text = json_body["requests"][0]["insertText"]["text"]
        assert "Agenda" in text
        assert "- Item A" in text
        assert "1. Step 1" in text
        return {"replies": []}, None

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    monkeypatch.setattr(docs_server, "_docs_post", fake_docs_post)
    result = await docs_server.append_docs_structured_content(
        "doc1",
        heading="Agenda",
        bullet_items=["Item A"],
        numbered_items=["Step 1"],
    )
    assert "Structured content appended to Google Docs document:" in result
    assert "Characters Added:" in result


@pytest.mark.asyncio
async def test_replace_docs_text_if_revision_mismatch(monkeypatch):
    async def fake_docs_get(path):
        assert path == "/documents/doc1"
        return {"revisionId": "rev-current"}, None

    monkeypatch.setattr(docs_server, "_docs_get", fake_docs_get)
    result = await docs_server.replace_docs_text_if_revision(
        "doc1",
        expected_revision_id="rev-expected",
        find_text="old",
        replace_text="new",
    )
    assert "Revision mismatch. No changes applied." in result
    assert "Current Revision ID: rev-current" in result
