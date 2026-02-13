# Pseudocode - MCP Gmail Server

Source: `src/chat_google/mcp_servers/gmail_server.py`

## 1) Server initialization

```text
LOAD .env
CREATE FastMCP server named "Gmail"
DEFINE pydantic input models for all tool parameters
```

## 2) Core helpers

### `_get_credentials()`

```text
READ GOOGLE_ACCOUNT and GOOGLE_APP_KEY from env
IF any missing -> raise ValueError
RETURN (email_account, app_password)
```

### `_get_imap_connection()`

```text
creds = _get_credentials()
mail = IMAP4_SSL("imap.gmail.com")
mail.login(creds)
RETURN mail
```

### `_decode_str(value)`

```text
IF value is None: return ""
DECODE MIME-encoded header chunks using decode_header
JOIN decoded parts and return
```

### `_build_ics_invite(...)`

```text
PARSE start_time "YYYY-MM-DD HH:MM"
CALCULATE end_time = start + duration_minutes
GENERATE uid + dtstamp UTC
ESCAPE text fields (summary, description, location, attendee cn)
BUILD VCALENDAR string with METHOD:REQUEST and single VEVENT
RETURN ICS content
```

## 3) Tool pseudocode

## 3.1 `list_recent_emails(count=5)`

```text
VALIDATE count (1..100)
mail = _get_imap_connection()
SELECT inbox
GET total_messages
IF total_messages == 0: logout and return "No emails found."

FETCH RFC822.HEADER range for latest N emails
FOR each message in reverse (newest first):
    parse message bytes
    decode Subject and From
    read Date
    append "Seq|Date|From|Subject"

logout
RETURN joined lines
ON exception: return "Error listing emails: ..."
```

## 3.2 `read_email(email_id)`

```text
VALIDATE email_id non-empty
mail = _get_imap_connection()
SELECT inbox
FETCH RFC822 for email_id
IF fetch not OK: logout + return failure message

PARSE full message
decode Subject and From
EXTRACT body:
    if multipart -> first text/plain non-attachment
    else direct payload

logout
RETURN "From/Subject/Content"
ON exception: return "Error reading email: ..."
```

## 3.3 `summarize_emails(timeframe="24h", label="inbox", count=10)`

```text
VALIDATE timeframe/label/count
mail = _get_imap_connection()
SELECT given label (readonly)
IF label not found: logout + return message

COMPUTE since_date by timeframe:
    today -> now
    yesterday -> now -1 day
    week -> now -7 days
    default(24h) -> now -1 day

SEARCH label with SINCE date
IF search failed: logout + return error
IF no ids: logout + return "No emails found ..."

TAKE latest count ids (newest first)
FOR each id:
    FETCH "(RFC822.HEADER BODY[TEXT]<0.500>)"
    build header summary + first body snippet
    append formatted block

logout
RETURN list with count and snippets
ON exception: return "Error during fetch for summary: ..."
```

## 3.4 `list_unread_emails(count=5)`

```text
VALIDATE count
mail = _get_imap_connection()
SELECT inbox readonly
since_date = now - 30 days
SEARCH "UNSEEN SINCE <date>"
IF failed: logout + return error
IF no ids: logout + return no unread message

FOR latest count unread ids:
    FETCH RFC822.HEADER
    parse date/from/subject
    append formatted line

logout
RETURN "Unread Emails ..." + lines
ON exception: return "Error listing unread emails: ..."
```

## 3.5 `mark_as_read(email_id)`

```text
VALIDATE email_id
mail = _get_imap_connection()
SELECT inbox
STORE email_id +FLAGS \Seen
logout
IF status OK: return success
ELSE return failure
ON exception: return "Error marking email as read: ..."
```

## 3.6 `list_labels()`

```text
mail = _get_imap_connection()
status, labels = mail.list()
logout
IF status not OK: return error
RETURN decoded labels joined by newline
ON exception: return "Error listing labels: ..."
```

## 3.7 `search_emails_by_label(label, count=5)`

```text
VALIDATE label/count
mail = _get_imap_connection()
SELECT quoted label readonly
IF not OK: logout + return label inaccessible

GET total messages in label
IF 0: logout + return no emails in label

FETCH latest count headers
FOR each result reverse (newest first):
    parse subject/from
    append "Seq|From|Subject"

logout
RETURN "Recent emails in <label>:\n..."
ON exception: return "Error searching label ...: ..."
```

## 3.8 `search_emails(query)`

```text
VALIDATE query non-empty
mail = _get_imap_connection()
SELECT inbox
SEARCH TEXT "<query>"
IF failed: logout + return "Search failed."
IF no ids: logout + return "No emails found matching ..."

FOR up to latest 10 ids reverse:
    FETCH header
    parse from/subject
    append line

logout
RETURN lines
ON exception: return "Error searching emails: ..."
```

## 3.9 `send_email(to_email, subject, body)`

```text
VALIDATE recipient email + subject + body
READ sender creds via _get_credentials()
BUILD MIMEText body
SET Subject/From/To headers

OPEN SMTP_SSL("smtp.gmail.com",465)
LOGIN sender account
SEND message

RETURN success text
ON exception: return "Error sending email: ..."
```

## 3.10 `send_calendar_invite_email(...)`

```text
VALIDATE recipient, subject, event fields, start_time format input string
READ sender creds
ics_content = _build_ics_invite(...)

CREATE EmailMessage
SET Subject/From/To
SET "Content-Class" = calendarmessage
SET plain text body
ADD alternative part:
    subtype="calendar"
    charset="utf-8"
    params={"method":"REQUEST"}
    payload = ics_content

OPEN SMTP_SSL and login
SEND message
RETURN success text
ON exception: return "Error sending calendar invitation email: ..."
```

## 4) Server runner

```text
def run():
    mcp.run()

if __name__ == "__main__":
    run()
```
