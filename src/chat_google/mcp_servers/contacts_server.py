import asyncio
import importlib.util
import logging
import os
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx
import vobject
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("GoogleContacts")

HTTP_TIMEOUT = httpx.Timeout(timeout=15.0, connect=5.0)
HTTP_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
FETCH_BATCH_SIZE = 20
HTTP2_ENABLED = importlib.util.find_spec("h2") is not None


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("SumopodChat.ContactsServer")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    file_handler = logging.FileHandler("chat_app.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
        )
    )
    logger.addHandler(file_handler)
    return logger


logger = _build_logger()
if not HTTP2_ENABLED:
    logger.warning("h2 is not installed; contacts server will use HTTP/1.1")


def _client_kwargs() -> dict:
    return {
        "follow_redirects": True,
        "timeout": HTTP_TIMEOUT,
        "limits": HTTP_LIMITS,
        "http2": HTTP2_ENABLED,
    }


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


def _extract_links_from_multistatus(xml_text: str, email_account: str) -> tuple[list[str] | None, str | None]:
    try:
        root = ET.fromstring(xml_text)
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


async def _fetch_vcf_links():
    email_account, app_password = _get_credentials()
    auth = (email_account, app_password)
    headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    body = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:">
        <d:prop><d:getetag /></d:prop>
    </d:propfind>"""

    base_url = _contacts_base_url(email_account)
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.request(
            "PROPFIND",
            base_url,
            content=body,
            headers=headers,
            auth=auth,
        )

    if response.status_code not in (200, 207):
        return None, f"Fetch failed: {response.status_code}"

    return _extract_links_from_multistatus(response.text, email_account)


async def _search_vcf_links(query: str):
    email_account, app_password = _get_credentials()
    auth = (email_account, app_password)
    headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    safe_query = xml_escape(query)
    body = f"""<?xml version="1.0" encoding="utf-8" ?>
    <c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
      <d:prop><d:getetag /></d:prop>
      <c:filter>
        <c:prop-filter name="FN">
          <c:text-match collation="i;unicode-casemap" match-type="contains">{safe_query}</c:text-match>
        </c:prop-filter>
      </c:filter>
    </c:addressbook-query>"""

    base_url = _contacts_base_url(email_account)
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.request(
            "REPORT",
            base_url,
            content=body,
            headers=headers,
            auth=auth,
        )

    if response.status_code not in (200, 207):
        return None, f"Search failed: {response.status_code}"

    return _extract_links_from_multistatus(response.text, email_account)


def _parse_vcard_entry(vcard_text: str) -> tuple[str, str, str] | None:
    try:
        vcard = vobject.readOne(vcard_text)
        name_obj = getattr(vcard, "fn", None)
        name = name_obj.value if name_obj else ""
        email_obj = getattr(vcard, "email", None)
        email_value = email_obj.value if email_obj else "No Email"
        tel_obj = getattr(vcard, "tel", None)
        tel_value = tel_obj.value if tel_obj else "No Phone"
        return name, email_value, tel_value
    except Exception:
        return None


async def _fetch_contacts(
    links: list[str],
    auth: tuple[str, str],
    query_lower: str | None = None,
    max_results: int | None = None,
):
    results = []
    total_requests = 0
    request_errors = 0
    started_at = time.perf_counter()
    async with httpx.AsyncClient(**_client_kwargs()) as client:
        for i in range(0, len(links), FETCH_BATCH_SIZE):
            if max_results and len(results) >= max_results:
                break
            chunk = links[i : i + FETCH_BATCH_SIZE]
            chunk_started_at = time.perf_counter()
            responses = await asyncio.gather(
                *[client.get(link, auth=auth) for link in chunk],
                return_exceptions=True,
            )
            logger.debug(
                "Fetched contacts chunk: size=%s duration=%.3fs",
                len(chunk),
                time.perf_counter() - chunk_started_at,
            )
            for resp in responses:
                total_requests += 1
                if max_results and len(results) >= max_results:
                    break
                if isinstance(resp, Exception):
                    request_errors += 1
                    logger.debug("Contact fetch exception: %s", resp)
                    continue
                if resp.status_code != 200:
                    request_errors += 1
                    continue
                entry = _parse_vcard_entry(resp.text)
                if not entry:
                    request_errors += 1
                    continue
                name, email_value, tel_value = entry
                if query_lower and query_lower not in name.lower():
                    continue
                results.append((name, email_value, tel_value))
    logger.debug(
        "Fetch contacts completed: links=%s total_requests=%s errors=%s results=%s duration=%.3fs",
        len(links),
        total_requests,
        request_errors,
        len(results),
        time.perf_counter() - started_at,
    )
    return results


@mcp.tool()
async def list_contacts(limit: int = 10) -> str:
    """Lists names and emails of your Google contacts."""
    try:
        started_at = time.perf_counter()
        params = _ListContactsInput.model_validate({"limit": limit})
        limit = params.limit

        links, err = await _fetch_vcf_links()
        if err:
            logger.warning("list_contacts failed: %s", err)
            return err
        if not links:
            logger.info("list_contacts: no contacts found")
            return "No contacts found."

        email_account, app_password = _get_credentials()
        auth = (email_account, app_password)
        contacts = await _fetch_contacts(links[:limit], auth=auth, max_results=limit)
        lines = [f"- {name or 'Unknown'}: {email_value}" for name, email_value, _ in contacts]
        logger.info(
            "list_contacts completed: requested=%s returned=%s duration=%.3fs",
            limit,
            len(lines),
            time.perf_counter() - started_at,
        )
        return f"Contacts (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        logger.exception("list_contacts unexpected error")
        return f"Error: {str(exc)}"


@mcp.tool()
async def search_contacts(query: str) -> str:
    """Searches for a contact by name."""
    raw_query = query
    started_at = time.perf_counter()
    used_fallback = False
    try:
        params = _SearchContactsInput.model_validate({"query": query})
        query = params.query
        logger.info("search_contacts started: query=%r", query)

        report_started = time.perf_counter()
        links, err = await _search_vcf_links(query)
        logger.debug(
            "search_contacts REPORT completed: links=%s err=%s duration=%.3fs",
            len(links) if links else 0,
            err,
            time.perf_counter() - report_started,
        )
        if err or not links:
            used_fallback = True
            if err:
                logger.warning("search_contacts REPORT failed: query=%r err=%s", query, err)
            fallback_started = time.perf_counter()
            links, err = await _fetch_vcf_links()
            logger.debug(
                "search_contacts fallback PROPFIND completed: links=%s err=%s duration=%.3fs",
                len(links) if links else 0,
                err,
                time.perf_counter() - fallback_started,
            )
            if err:
                logger.error("search_contacts fallback failed: query=%r err=%s", query, err)
                return err
        if not links:
            logger.info("search_contacts: no contacts found query=%r", query)
            return "No contacts found."

        email_account, app_password = _get_credentials()
        auth = (email_account, app_password)
        query_lower = query.lower()
        fetch_started = time.perf_counter()
        contacts = await _fetch_contacts(
            links,
            auth=auth,
            query_lower=query_lower,
            max_results=5,
        )
        fetch_duration = time.perf_counter() - fetch_started
        results = [
            f"Name: {name or 'Unknown'}\nEmail: {email_value}\nPhone: {tel_value}"
            for name, email_value, tel_value in contacts
        ]

        if not results:
            logger.info(
                "search_contacts no match: query=%r links=%s fallback=%s fetch_duration=%.3fs total_duration=%.3fs",
                query,
                len(links),
                used_fallback,
                fetch_duration,
                time.perf_counter() - started_at,
            )
            return f"No match for '{query}'"
        logger.info(
            "search_contacts completed: query=%r results=%s links=%s fallback=%s fetch_duration=%.3fs total_duration=%.3fs",
            query,
            len(results),
            len(links),
            used_fallback,
            fetch_duration,
            time.perf_counter() - started_at,
        )
        return "Search Results:\n\n" + "\n---\n".join(results)
    except Exception as exc:
        logger.exception(
            "search_contacts unexpected error: raw_query=%r total_duration=%.3fs",
            raw_query,
            time.perf_counter() - started_at,
        )
        return f"Error: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
