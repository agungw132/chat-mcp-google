# Pseudocode - MCP Contacts Server

Source: `src/chat_google/mcp_servers/contacts_server.py`

## 1) Server initialization

```text
LOAD .env
CREATE FastMCP server named "GoogleContacts"
SET HTTP timeout/limits and batch size constants
DETECT if `h2` package exists:
    HTTP2_ENABLED = True/False
INIT dedicated file logger to chat_app.log
IF HTTP/2 unavailable:
    log warning and continue with HTTP/1.1
```

## 2) Core helpers

### `_get_credentials()`

```text
READ GOOGLE_ACCOUNT and GOOGLE_APP_KEY
IF missing -> raise ValueError
RETURN (email, app_key)
```

### `_contacts_base_url(email)`

```text
RETURN "https://www.googleapis.com/carddav/v1/principals/<email>/lists/default/"
```

### `_extract_links_from_multistatus(xml_text, email_account)`

```text
PARSE XML multistatus response
FOR each DAV response href:
    skip root collection href
    normalize to full https://www.googleapis.com/... url
    append to links
RETURN (links, None)
ON parse failure:
    RETURN (None, "XML Error: ...")
```

### `_fetch_vcf_links()`

```text
SEND PROPFIND request to CardDAV base URL
IF status not 200/207:
    RETURN (None, "Fetch failed: <status>")
RETURN _extract_links_from_multistatus(response_xml)
```

### `_search_vcf_links(query)`

```text
XML-escape query
BUILD CardDAV REPORT addressbook-query on FN contains query
SEND REPORT request
IF status not 200/207:
    RETURN (None, "Search failed: <status>")
RETURN _extract_links_from_multistatus(response_xml)
```

### `_parse_vcard_entry(vcard_text)`

```text
PARSE vCard using vobject
READ fn, email, tel with fallback values
RETURN (name, email, phone)
ON parse failure: return None
```

### `_fetch_contacts(links, auth, query_lower=None, max_results=None)`

```text
INIT result counters and timer
CREATE AsyncClient(http2=HTTP2_ENABLED, timeout, limits)

FOR links in batches (size=FETCH_BATCH_SIZE):
    IF max_results reached: break
    FETCH all links in chunk concurrently (asyncio.gather)
    FOR each response:
        update counters
        skip exceptions/non-200/parse-failures
        parse vCard -> (name,email,phone)
        if query_lower provided and not in name.lower(): skip
        append parsed contact
        stop if max_results reached

LOG stats
RETURN contacts list
```

## 3) Tool pseudocode

## 3.1 `list_contacts(limit=10)`

```text
VALIDATE limit (1..200)
links, err = _fetch_vcf_links()
IF err: log warning + return err
IF no links: return "No contacts found."

auth = credentials
contacts = _fetch_contacts(first limit links, max_results=limit)
FORMAT each line "- <name>: <email>"
LOG duration + count
RETURN "Contacts (showing N):\n..."
ON exception:
    log exception
    return "Error: ..."
```

## 3.2 `search_contacts(query)`

```text
VALIDATE query non-empty
LOG start

TRY CardDAV REPORT search first:
    links, err = _search_vcf_links(query)
IF REPORT failed or links empty:
    mark used_fallback=True
    LOG warning
    fallback to PROPFIND:
        links, err = _fetch_vcf_links()
    IF fallback err: return err

IF no links: return "No contacts found."

auth = credentials
contacts = _fetch_contacts(
    links,
    auth=auth,
    query_lower=query.lower(),
    max_results=5
)

IF no contacts:
    LOG no match details
    RETURN "No match for '<query>'"

FORMAT each result block:
    Name
    Email
    Phone
LOG completion details
RETURN "Search Results:\n\n<joined blocks>"
ON exception:
    log exception with raw_query and duration
    return "Error: ..."
```

## 4) Server runner

```text
def run():
    mcp.run()

if __name__ == "__main__":
    run()
```
