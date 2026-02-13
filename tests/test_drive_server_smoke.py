import pytest

from chat_google.mcp_servers import drive_server


@pytest.mark.asyncio
async def test_drive_tools_smoke(monkeypatch):
    async def fake_request_json(path, params=None):
        if path == "/files":
            if params and "sharedWithMe=true" in params.get("q", ""):
                return (
                    {
                        "files": [
                            {
                                "id": "shared-1",
                                "name": "shared.txt",
                                "mimeType": "text/plain",
                                "modifiedTime": "2026-02-13T12:00:00Z",
                                "size": "42",
                                "webViewLink": "https://drive.google.com/file/d/shared-1/view",
                            }
                        ]
                    },
                    None,
                )
            return (
                {
                    "files": [
                        {
                            "id": "file-1",
                            "name": "alpha.txt",
                            "mimeType": "text/plain",
                            "modifiedTime": "2026-02-13T10:00:00Z",
                            "size": "12",
                            "webViewLink": "https://drive.google.com/file/d/file-1/view",
                        }
                    ]
                },
                None,
            )
        if path.startswith("/files/"):
            return (
                {
                    "id": "file-1",
                    "name": "alpha.txt",
                    "mimeType": "text/plain",
                    "size": "12",
                    "createdTime": "2026-01-01T00:00:00Z",
                    "modifiedTime": "2026-02-13T10:00:00Z",
                    "webViewLink": "https://drive.google.com/file/d/file-1/view",
                    "owners": [{"displayName": "Tester", "emailAddress": "tester@example.com"}],
                    "parents": ["root"],
                    "shared": True,
                    "trashed": False,
                },
                None,
            )
        return {}, None

    async def fake_post_json(path, params=None, json_body=None):
        if path == "/files":
            if json_body.get("mimeType") == "application/vnd.google-apps.folder":
                return (
                    {
                        "id": "folder-1",
                        "name": json_body.get("name", "folder"),
                        "mimeType": "application/vnd.google-apps.folder",
                        "webViewLink": "https://drive.google.com/drive/folders/folder-1",
                    },
                    None,
                )
            return (
                {
                    "id": "file-2",
                    "name": json_body.get("name", "file.txt"),
                    "mimeType": "text/plain",
                    "webViewLink": "https://drive.google.com/file/d/file-2/view",
                },
                None,
            )
        if "/permissions" in path and json_body.get("type") == "user":
            return (
                {
                    "id": "perm-user",
                    "type": "user",
                    "role": json_body.get("role", "reader"),
                    "emailAddress": json_body.get("emailAddress", "user@example.com"),
                    "expirationTime": json_body.get("expirationTime", "2026-02-20T10:00:00Z"),
                },
                None,
            )
        if "/permissions" in path and json_body.get("type") == "anyone":
            return (
                {
                    "id": "perm-public",
                    "type": "anyone",
                    "role": json_body.get("role", "reader"),
                    "allowFileDiscovery": json_body.get("allowFileDiscovery", False),
                },
                None,
            )
        return {}, None

    async def fake_patch_json(path, params=None, json_body=None):
        return (
            {
                "id": "file-1",
                "name": "alpha.txt",
                "mimeType": "text/plain",
                "parents": [params.get("addParents", "new-parent")],
                "webViewLink": "https://drive.google.com/file/d/file-1/view",
            },
            None,
        )

    async def fake_request_bytes(path, params=None):
        return b"alpha content", None

    async def fake_upload_file_media(file_id, content, content_type="text/plain; charset=utf-8"):
        return None

    monkeypatch.setattr(drive_server, "_request_json", fake_request_json)
    monkeypatch.setattr(drive_server, "_post_json", fake_post_json)
    monkeypatch.setattr(drive_server, "_patch_json", fake_patch_json)
    monkeypatch.setattr(drive_server, "_request_bytes", fake_request_bytes)
    monkeypatch.setattr(drive_server, "_upload_file_media", fake_upload_file_media)

    list_res = await drive_server.list_drive_files(limit=5)
    search_res = await drive_server.search_drive_files("alpha", limit=5)
    meta_res = await drive_server.get_drive_file_metadata("file-1")
    read_res = await drive_server.read_drive_text_file("file-1", max_chars=200)
    shared_res = await drive_server.list_shared_with_me(limit=5)
    folder_res = await drive_server.create_drive_folder("Team")
    upload_res = await drive_server.upload_text_file("notes.txt", "hello")
    move_res = await drive_server.move_drive_file("file-1", "new-parent")
    share_res = await drive_server.create_drive_shared_link_to_user("file-1", "user@example.com")
    public_res = await drive_server.create_drive_public_link("file-1")

    assert "Drive Files" in list_res
    assert "Search Results" in search_res
    assert "File Metadata" in meta_res
    assert "File Content" in read_res
    assert "Shared Files" in shared_res
    assert "Folder created" in folder_res
    assert "File uploaded" in upload_res
    assert "Drive item moved" in move_res
    assert "Drive shared link created for user" in share_res
    assert "Drive public link created" in public_res
