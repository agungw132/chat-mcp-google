import pytest

from chat_google.mcp_servers import drive_server


@pytest.mark.asyncio
async def test_list_drive_files(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/files"
        assert params["pageSize"] == 2
        return (
            {
                "files": [
                    {
                        "id": "f1",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-02-13T10:00:00Z",
                        "size": "120",
                        "webViewLink": "https://drive.google.com/file/d/f1/view",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.list_drive_files(limit=2)
    assert "Drive Files (showing 1)" in result
    assert "notes.txt" in result
    assert "ID: f1" in result


@pytest.mark.asyncio
async def test_list_drive_files_filters(monkeypatch):
    captured = {}

    async def fake_request_json(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"files": []}, None

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.list_drive_files(
        limit=5,
        folder_id="folder-1",
        mime_type="text/plain",
    )
    assert result == "No files found."
    assert captured["path"] == "/files"
    assert "'folder-1' in parents" in captured["params"]["q"]
    assert "mimeType='text/plain'" in captured["params"]["q"]


@pytest.mark.asyncio
async def test_search_drive_files(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/files"
        assert "name contains 'report'" in params["q"]
        return (
            {
                "files": [
                    {
                        "id": "r1",
                        "name": "monthly-report.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-02-13T11:00:00Z",
                        "size": "256",
                        "webViewLink": "https://drive.google.com/file/d/r1/view",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.search_drive_files("report", limit=3)
    assert "Search Results for 'report'" in result
    assert "monthly-report.txt" in result


@pytest.mark.asyncio
async def test_search_drive_files_no_match(monkeypatch):
    async def fake_request_json(path, params=None):
        return {"files": []}, None

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.search_drive_files("unknown")
    assert result == "No files found matching 'unknown'"


@pytest.mark.asyncio
async def test_get_drive_file_metadata(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/files/file-123"
        return (
            {
                "id": "file-123",
                "name": "team-plan.txt",
                "mimeType": "text/plain",
                "size": "1024",
                "createdTime": "2026-01-01T01:00:00Z",
                "modifiedTime": "2026-02-01T02:00:00Z",
                "webViewLink": "https://drive.google.com/file/d/file-123/view",
                "owners": [{"displayName": "Tester", "emailAddress": "tester@example.com"}],
                "parents": ["parent-1"],
                "shared": True,
                "trashed": False,
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.get_drive_file_metadata("file-123")
    assert "File Metadata:" in result
    assert "Name: team-plan.txt" in result
    assert "Owners: Tester <tester@example.com>" in result


@pytest.mark.asyncio
async def test_read_drive_text_file(monkeypatch):
    async def fake_request_json(path, params=None):
        return (
            {
                "id": "f-text",
                "name": "notes.txt",
                "mimeType": "text/plain",
                "size": "20",
            },
            None,
        )

    async def fake_request_bytes(path, params=None):
        assert params["alt"] == "media"
        return b"Hello from Drive", None

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    monkeypatch.setattr(drive_server, "_request_bytes", fake_request_bytes)
    result = await drive_server.read_drive_text_file("f-text", max_chars=200)
    assert "File Content: notes.txt" in result
    assert "Hello from Drive" in result


@pytest.mark.asyncio
async def test_read_drive_text_file_reject_workspace_doc(monkeypatch):
    async def fake_request_json(path, params=None):
        return (
            {
                "id": "doc-1",
                "name": "Doc",
                "mimeType": "application/vnd.google-apps.document",
                "size": "0",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.read_drive_text_file("doc-1", max_chars=200)
    assert "Unsupported file type for this MCP phase" in result


@pytest.mark.asyncio
async def test_read_drive_text_file_reject_non_text(monkeypatch):
    async def fake_request_json(path, params=None):
        return (
            {
                "id": "img-1",
                "name": "photo.png",
                "mimeType": "image/png",
                "size": "12",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.read_drive_text_file("img-1", max_chars=200)
    assert result == "Unsupported non-text file type: image/png"


@pytest.mark.asyncio
async def test_read_drive_text_file_truncated(monkeypatch):
    async def fake_request_json(path, params=None):
        return (
            {
                "id": "big-1",
                "name": "big.txt",
                "mimeType": "text/plain",
                "size": "99999",
            },
            None,
        )

    async def fake_request_bytes(path, params=None):
        return (b"a" * 500), None

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    monkeypatch.setattr(drive_server, "_request_bytes", fake_request_bytes)
    result = await drive_server.read_drive_text_file("big-1", max_chars=200)
    assert "File Content: big.txt" in result
    assert "[Truncated]" in result


@pytest.mark.asyncio
async def test_list_shared_with_me(monkeypatch):
    async def fake_request_json(path, params=None):
        assert "sharedWithMe=true" in params["q"]
        return (
            {
                "files": [
                    {
                        "id": "s1",
                        "name": "shared-note.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-02-13T12:00:00Z",
                        "size": "90",
                        "webViewLink": "https://drive.google.com/file/d/s1/view",
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.list_shared_with_me(limit=1)
    assert "Shared Files (showing 1)" in result
    assert "shared-note.txt" in result


@pytest.mark.asyncio
async def test_drive_validation_error_limit():
    result = await drive_server.list_drive_files(limit=0)
    assert result.startswith("Error listing drive files:")
    assert "greater than or equal to 1" in result


def test_get_access_token_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    drive_server._CACHED_ACCESS_TOKEN = None
    drive_server._CACHED_ACCESS_TOKEN_EXPIRES_AT = None
    with pytest.raises(ValueError):
        drive_server._get_access_token()


def test_get_access_token_static_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "static-token")
    monkeypatch.delenv("GOOGLE_DRIVE_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    drive_server._CACHED_ACCESS_TOKEN = None
    drive_server._CACHED_ACCESS_TOKEN_EXPIRES_AT = None
    assert drive_server._get_access_token() == "static-token"


def test_get_access_token_refresh_success_and_cache(monkeypatch):
    calls = {"count": 0}

    def fake_refresh_access_token(refresh_token, client_id, client_secret):
        calls["count"] += 1
        assert refresh_token == "refresh-1"
        assert client_id == "client-id-1"
        assert client_secret == "client-secret-1"
        return "fresh-token-1", 3600

    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-1")
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "old-token")
    monkeypatch.setattr(drive_server, "_refresh_access_token", fake_refresh_access_token)
    drive_server._CACHED_ACCESS_TOKEN = None
    drive_server._CACHED_ACCESS_TOKEN_EXPIRES_AT = None

    token_1 = drive_server._get_access_token()
    token_2 = drive_server._get_access_token()

    assert token_1 == "fresh-token-1"
    assert token_2 == "fresh-token-1"
    assert calls["count"] == 1


def test_get_access_token_refresh_failure_falls_back_to_static(monkeypatch):
    def fake_refresh_access_token(refresh_token, client_id, client_secret):
        raise ValueError("invalid_grant")

    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret-1")
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "static-fallback-token")
    monkeypatch.setattr(drive_server, "_refresh_access_token", fake_refresh_access_token)
    drive_server._CACHED_ACCESS_TOKEN = None
    drive_server._CACHED_ACCESS_TOKEN_EXPIRES_AT = None

    assert drive_server._get_access_token() == "static-fallback-token"


def test_get_access_token_incomplete_refresh_config(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id-1")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    drive_server._CACHED_ACCESS_TOKEN = None
    drive_server._CACHED_ACCESS_TOKEN_EXPIRES_AT = None

    with pytest.raises(ValueError) as exc_info:
        drive_server._get_access_token()
    assert "Incomplete Drive OAuth refresh configuration" in str(exc_info.value)
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_drive_folder(monkeypatch):
    async def fake_post_json(path, params=None, json_body=None):
        assert path == "/files"
        assert json_body["mimeType"] == "application/vnd.google-apps.folder"
        assert json_body["name"] == "Project Docs"
        assert json_body["parents"] == ["parent-1"]
        return (
            {
                "id": "folder-1",
                "name": "Project Docs",
                "mimeType": "application/vnd.google-apps.folder",
                "webViewLink": "https://drive.google.com/drive/folders/folder-1",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    result = await drive_server.create_drive_folder("Project Docs", parent_id="parent-1")
    assert "Folder created:" in result
    assert "ID: folder-1" in result


@pytest.mark.asyncio
async def test_upload_text_file(monkeypatch):
    async def fake_post_json(path, params=None, json_body=None):
        assert path == "/files"
        return (
            {
                "id": "file-123",
                "name": "notes.txt",
                "mimeType": "text/plain",
                "webViewLink": "https://drive.google.com/file/d/file-123/view",
            },
            None,
        )

    async def fake_upload_media(file_id, content, content_type="text/plain; charset=utf-8"):
        assert file_id == "file-123"
        assert b"hello world" in content
        return None

    async def fake_request_json(path, params=None):
        return (
            {
                "id": "file-123",
                "name": "notes.txt",
                "mimeType": "text/plain",
                "size": "11",
                "webViewLink": "https://drive.google.com/file/d/file-123/view",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    monkeypatch.setattr(drive_server, "_upload_file_media", fake_upload_media)
    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)

    result = await drive_server.upload_text_file("notes.txt", "hello world", parent_id="parent-1")
    assert "File uploaded:" in result
    assert "Size: 11" in result


@pytest.mark.asyncio
async def test_move_drive_file(monkeypatch):
    calls = {"patch_params": None}

    async def fake_request_json(path, params=None):
        assert path == "/files/file-1"
        return (
            {
                "id": "file-1",
                "name": "doc.txt",
                "mimeType": "text/plain",
                "parents": ["old-parent"],
                "webViewLink": "https://drive.google.com/file/d/file-1/view",
            },
            None,
        )

    async def fake_patch_json(path, params=None, json_body=None):
        calls["patch_params"] = params
        return (
            {
                "id": "file-1",
                "name": "doc.txt",
                "mimeType": "text/plain",
                "parents": ["new-parent"],
                "webViewLink": "https://drive.google.com/file/d/file-1/view",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    monkeypatch.setattr(drive_server, "_patch_json", fake_patch_json)

    result = await drive_server.move_drive_file("file-1", "new-parent")
    assert "Drive item moved:" in result
    assert "New Parents: new-parent" in result
    assert calls["patch_params"]["addParents"] == "new-parent"
    assert calls["patch_params"]["removeParents"] == "old-parent"


@pytest.mark.asyncio
async def test_create_drive_shared_link_to_user_default_expiry(monkeypatch):
    captured = {"payload": None, "params": None}

    async def fake_post_json(path, params=None, json_body=None):
        captured["payload"] = json_body
        captured["params"] = params
        return (
            {
                "id": "perm-1",
                "type": "user",
                "role": "reader",
                "emailAddress": "user@example.com",
                "expirationTime": "2026-02-20T10:00:00Z",
            },
            None,
        )

    async def fake_request_json(path, params=None):
        return (
            {
                "id": "item-1",
                "name": "doc.txt",
                "mimeType": "text/plain",
                "webViewLink": "https://drive.google.com/file/d/item-1/view",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.create_drive_shared_link_to_user("item-1", "user@example.com")

    assert "Drive shared link created for user:" in result
    assert "Permission ID: perm-1" in result
    assert captured["payload"]["type"] == "user"
    assert captured["payload"]["role"] == "reader"
    assert captured["payload"]["expirationTime"].endswith("Z")
    assert captured["params"]["sendNotificationEmail"] == "true"


@pytest.mark.asyncio
async def test_create_drive_shared_link_to_user_invalid_role():
    result = await drive_server.create_drive_shared_link_to_user(
        item_id="item-1",
        user_email="user@example.com",
        role="owner",
    )
    assert "Invalid role" in result


@pytest.mark.asyncio
async def test_create_drive_shared_link_to_user_fallback_without_expiration(monkeypatch):
    calls = {"count": 0, "payloads": []}

    async def fake_post_json(path, params=None, json_body=None):
        calls["count"] += 1
        calls["payloads"].append(json_body)
        if calls["count"] == 1:
            return None, (
                "Error: Drive API request failed: 403 (cannotSetExpiration) - "
                "Expiration dates cannot be set on this item."
            )
        return (
            {
                "id": "perm-2",
                "type": "user",
                "role": "reader",
                "emailAddress": "user@example.com",
            },
            None,
        )

    async def fake_request_json(path, params=None):
        return (
            {
                "id": "item-2",
                "name": "no-expiry-file.pdf",
                "mimeType": "application/pdf",
                "webViewLink": "https://drive.google.com/file/d/item-2/view",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    result = await drive_server.create_drive_shared_link_to_user("item-2", "user@example.com")

    assert calls["count"] == 2
    assert "expirationTime" in calls["payloads"][0]
    assert "expirationTime" not in calls["payloads"][1]
    assert "Drive shared link created for user:" in result
    assert "Permission ID: perm-2" in result
    assert "Note: This item does not support expiration." in result


@pytest.mark.asyncio
async def test_create_drive_public_link_for_folder(monkeypatch):
    async def fake_post_json(path, params=None, json_body=None):
        assert json_body["type"] == "anyone"
        assert json_body["allowFileDiscovery"] is False
        return (
            {
                "id": "perm-public",
                "type": "anyone",
                "role": "reader",
                "allowFileDiscovery": False,
            },
            None,
        )

    async def fake_request_json(path, params=None):
        return (
            {
                "id": "folder-1",
                "name": "Shared Folder",
                "mimeType": "application/vnd.google-apps.folder",
                "webViewLink": "https://drive.google.com/drive/folders/folder-1",
            },
            None,
        )

    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)

    result = await drive_server.create_drive_public_link("folder-1")
    assert "Drive public link created:" in result
    assert "Shared Folder" in result
    assert "does not support expiration" in result


@pytest.mark.asyncio
async def test_create_drive_public_link_invalid_role():
    result = await drive_server.create_drive_public_link(
        item_id="item-1",
        role="owner",
    )
    assert "Invalid role" in result
