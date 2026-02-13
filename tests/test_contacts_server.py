from types import SimpleNamespace

import pytest

from chat_google.mcp_servers import contacts_server


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


@pytest.mark.asyncio
async def test_fetch_vcf_links(monkeypatch):
    sample_xml = """<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response>
        <d:href>/carddav/v1/principals/tester@example.com/lists/default/</d:href>
      </d:response>
      <d:response>
        <d:href>/carddav/v1/principals/tester@example.com/lists/default/1.vcf</d:href>
      </d:response>
      <d:response>
        <d:href>/carddav/v1/principals/tester@example.com/lists/default/2.vcf</d:href>
      </d:response>
    </d:multistatus>"""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, content, headers, auth):
            assert method == "PROPFIND"
            return _Response(status_code=207, text=sample_xml)

    monkeypatch.setattr(contacts_server.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    links, err = await contacts_server._fetch_vcf_links()
    assert err is None
    assert len(links) == 2
    assert links[0].startswith("https://www.googleapis.com")


@pytest.mark.asyncio
async def test_list_contacts(monkeypatch):
    async def fake_fetch_links():
        return ["https://api.test/1.vcf", "https://api.test/2.vcf"], None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, link, auth=None):
            if link.endswith("1.vcf"):
                return _Response(status_code=200, text="CONTACT_1")
            return _Response(status_code=200, text="CONTACT_2")

    def fake_read_one(text):
        if text == "CONTACT_1":
            return SimpleNamespace(
                fn=SimpleNamespace(value="Alice"),
                email=SimpleNamespace(value="alice@example.com"),
            )
        return SimpleNamespace(
            fn=SimpleNamespace(value="Bob"),
            email=SimpleNamespace(value="bob@example.com"),
        )

    monkeypatch.setattr(contacts_server, "_fetch_vcf_links", fake_fetch_links)
    monkeypatch.setattr(contacts_server.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(contacts_server.vobject, "readOne", fake_read_one)
    result = await contacts_server.list_contacts(limit=2)
    assert "Contacts (showing 2)" in result
    assert "Alice" in result
    assert "Bob" in result


@pytest.mark.asyncio
async def test_search_contacts(monkeypatch):
    async def fake_fetch_links():
        return ["https://api.test/1.vcf", "https://api.test/2.vcf"], None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, link, auth=None):
            if link.endswith("1.vcf"):
                return _Response(status_code=200, text="ALICE")
            return _Response(status_code=200, text="CHARLIE")

    def fake_read_one(text):
        if text == "ALICE":
            return SimpleNamespace(
                fn=SimpleNamespace(value="Alice Wonderland"),
                email=SimpleNamespace(value="alice@example.com"),
                tel=SimpleNamespace(value="+621234"),
            )
        return SimpleNamespace(
            fn=SimpleNamespace(value="Charlie"),
            email=SimpleNamespace(value="charlie@example.com"),
            tel=SimpleNamespace(value="+62999"),
        )

    monkeypatch.setattr(contacts_server, "_fetch_vcf_links", fake_fetch_links)
    monkeypatch.setattr(contacts_server.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(contacts_server.vobject, "readOne", fake_read_one)
    result = await contacts_server.search_contacts("alice")
    assert "Search Results" in result
    assert "Alice Wonderland" in result
    assert "alice@example.com" in result


@pytest.mark.asyncio
async def test_search_contacts_no_match(monkeypatch):
    async def fake_fetch_links():
        return ["https://api.test/1.vcf"], None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, link, auth=None):
            return _Response(status_code=200, text="ONLY_BOB")

    def fake_read_one(text):
        return SimpleNamespace(
            fn=SimpleNamespace(value="Bob"),
            email=SimpleNamespace(value="bob@example.com"),
            tel=SimpleNamespace(value="+62000"),
        )

    monkeypatch.setattr(contacts_server, "_fetch_vcf_links", fake_fetch_links)
    monkeypatch.setattr(contacts_server.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(contacts_server.vobject, "readOne", fake_read_one)
    result = await contacts_server.search_contacts("alice")
    assert result == "No match for 'alice'"


@pytest.mark.asyncio
async def test_search_contacts_invalid_query():
    result = await contacts_server.search_contacts("   ")
    assert result.startswith("Error:")
    assert "String should have at least 1 character" in result
