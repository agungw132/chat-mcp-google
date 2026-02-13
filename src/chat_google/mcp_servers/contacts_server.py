import os
import xml.etree.ElementTree as ET

import httpx
import vobject
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("GoogleContacts")


class _ListContactsInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=200, strict=True)


class _SearchContactsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)


def _get_credentials() -> tuple[str, str]:
    email_account = os.getenv("GOOGLE_ACCOUNT")
    app_password = os.getenv("GOOGLE_APP_KEY")
    if not email_account or not app_password:
        raise ValueError("GOOGLE_ACCOUNT and GOOGLE_APP_KEY must be set in .env")
    return email_account, app_password


def _contacts_base_url(email_account: str) -> str:
    return f"https://www.googleapis.com/carddav/v1/principals/{email_account}/lists/default/"


async def _fetch_vcf_links():
    email_account, app_password = _get_credentials()
    auth = (email_account, app_password)
    headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    body = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:">
        <d:prop><d:getetag /></d:prop>
    </d:propfind>"""

    base_url = _contacts_base_url(email_account)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.request(
            "PROPFIND",
            base_url,
            content=body,
            headers=headers,
            auth=auth,
        )

    if response.status_code not in (200, 207):
        return None, f"Fetch failed: {response.status_code}"

    try:
        root = ET.fromstring(response.text)
        ns = {"d": "DAV:"}
        links = []
        root_path = f"/carddav/v1/principals/{email_account}/lists/default/"
        for resource in root.findall(".//d:response", ns):
            href_node = resource.find("d:href", ns)
            if href_node is None:
                continue
            href = href_node.text
            if href == root_path or href == root_path[:-1]:
                continue
            full_url = (
                href
                if href.startswith("http")
                else f"https://www.googleapis.com{href}"
            )
            links.append(full_url)
        return links, None
    except Exception as exc:
        return None, f"XML Error: {str(exc)}"


@mcp.tool()
async def list_contacts(limit: int = 10) -> str:
    """Lists names and emails of your Google contacts."""
    try:
        params = _ListContactsInput.model_validate({"limit": limit})
        limit = params.limit

        links, err = await _fetch_vcf_links()
        if err:
            return err
        if not links:
            return "No contacts found."

        email_account, app_password = _get_credentials()
        auth = (email_account, app_password)
        results = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for link in links[:limit]:
                resp = await client.get(link, auth=auth)
                if resp.status_code != 200:
                    continue
                try:
                    vcard = vobject.readOne(resp.text)
                    name = getattr(vcard, "fn", None)
                    name_text = name.value if name else "Unknown"
                    email_value = getattr(vcard, "email", None)
                    email_text = email_value.value if email_value else "No Email"
                    results.append(f"- {name_text}: {email_text}")
                except Exception:
                    continue

        return f"Contacts (showing {len(results)}):\n" + "\n".join(results)
    except Exception as exc:
        return f"Error: {str(exc)}"


@mcp.tool()
async def search_contacts(query: str) -> str:
    """Searches for a contact by name."""
    try:
        params = _SearchContactsInput.model_validate({"query": query})
        query = params.query

        links, err = await _fetch_vcf_links()
        if err:
            return err
        if not links:
            return "No contacts found."

        email_account, app_password = _get_credentials()
        auth = (email_account, app_password)
        query_lower = query.lower()
        results = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for link in links:
                resp = await client.get(link, auth=auth)
                if resp.status_code != 200:
                    continue
                try:
                    vcard = vobject.readOne(resp.text)
                    name_obj = getattr(vcard, "fn", None)
                    name = name_obj.value if name_obj else ""
                    if query_lower not in name.lower():
                        continue
                    email_value = getattr(vcard, "email", None)
                    email_text = email_value.value if email_value else "No Email"
                    tel_value = getattr(vcard, "tel", None)
                    tel_text = tel_value.value if tel_value else "No Phone"
                    results.append(f"Name: {name}\nEmail: {email_text}\nPhone: {tel_text}")
                    if len(results) >= 5:
                        break
                except Exception:
                    continue

        if not results:
            return f"No match for '{query}'"
        return "Search Results:\n\n" + "\n---\n".join(results)
    except Exception as exc:
        return f"Error: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
