import email
import imaplib
import os
import smtplib
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.text import MIMEText
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("Gmail")


class _ListRecentEmailsInput(BaseModel):
    count: int = Field(default=5, ge=1, le=100, strict=True)


class _ReadEmailInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email_id: str = Field(min_length=1)


class _SummarizeEmailsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    timeframe: Literal["24h", "today", "yesterday", "week"] = "24h"
    label: str = Field(default="inbox", min_length=1)
    count: int = Field(default=10, ge=1, le=100, strict=True)


class _ListUnreadEmailsInput(BaseModel):
    count: int = Field(default=5, ge=1, le=100, strict=True)


class _MarkAsReadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email_id: str = Field(min_length=1)


class _SearchEmailsByLabelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1)
    count: int = Field(default=5, ge=1, le=100, strict=True)


class _SearchEmailsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)


class _SendEmailInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    to_email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(min_length=1)
    body: str = Field(default="")


def _get_credentials() -> tuple[str, str]:
    email_account = os.getenv("GOOGLE_ACCOUNT")
    app_password = os.getenv("GOOGLE_APP_KEY")
    if not email_account or not app_password:
        raise ValueError("GOOGLE_ACCOUNT and GOOGLE_APP_KEY must be set in .env")
    return email_account, app_password


def _get_imap_connection():
    email_account, app_password = _get_credentials()
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_account, app_password)
    return mail


def _decode_str(value: str | None) -> str:
    if value is None:
        return ""
    decoded = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return "".join(decoded)


@mcp.tool()
async def list_recent_emails(count: int = 5) -> str:
    """Lists the subjects and senders of the most recent emails in the inbox."""
    try:
        params = _ListRecentEmailsInput.model_validate({"count": count})
        count = params.count

        mail = _get_imap_connection()
        mail.select("inbox", readonly=True)
        status, response = mail.select("inbox")
        total_messages = int(response[0])

        if total_messages == 0:
            mail.logout()
            return "No emails found."

        start = max(1, total_messages - count + 1)
        end = total_messages
        status, data = mail.fetch(f"{start}:{end}", "(RFC822.HEADER)")

        results = []
        messages_data = [data[i] for i in range(len(data)) if isinstance(data[i], tuple)]
        for i in range(len(messages_data) - 1, -1, -1):
            msg_id_part, msg_content = messages_data[i]
            seq_num = msg_id_part.split()[0].decode()
            msg = email.message_from_bytes(msg_content)
            subject = _decode_str(msg.get("Subject"))
            sender = _decode_str(msg.get("From"))
            date = msg.get("Date")
            results.append(
                f"Seq: {seq_num} | Date: {date} | From: {sender} | Subject: {subject}"
            )

        mail.logout()
        return "\n".join(results)
    except Exception as exc:
        return f"Error listing emails: {str(exc)}"


@mcp.tool()
async def read_email(email_id: str) -> str:
    """Reads the full content of a specific email by its ID."""
    try:
        params = _ReadEmailInput.model_validate({"email_id": email_id})
        email_id = params.email_id

        mail = _get_imap_connection()
        mail.select("inbox")
        status, data = mail.fetch(email_id, "(RFC822)")
        if status != "OK":
            mail.logout()
            return f"Failed to fetch email ID {email_id}"

        msg = email.message_from_bytes(data[0][1])
        subject = _decode_str(msg.get("Subject"))
        sender = _decode_str(msg.get("From"))

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="ignore")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="ignore")

        mail.logout()
        return f"From: {sender}\nSubject: {subject}\n\nContent:\n{body}"
    except Exception as exc:
        return f"Error reading email: {str(exc)}"


@mcp.tool()
async def summarize_emails(timeframe: str = "24h", label: str = "inbox", count: int = 10) -> str:
    """
    Fetches emails from a specific timeframe and label for summarization.
    Args:
        timeframe: '24h', 'today', 'yesterday', or 'week'.
        label: The Gmail label to search in (default: 'inbox').
        count: Maximum number of emails to fetch (default: 10).
    """
    try:
        params = _SummarizeEmailsInput.model_validate(
            {"timeframe": timeframe, "label": label, "count": count}
        )
        timeframe = params.timeframe
        label = params.label
        count = params.count

        mail = _get_imap_connection()
        quoted_label = f'"{label}"'
        status, _ = mail.select(quoted_label, readonly=True)
        if status != "OK":
            mail.logout()
            return f"Label '{label}' not found."

        now = datetime.now()
        if timeframe == "today":
            since_date = now
        elif timeframe == "yesterday":
            since_date = now - timedelta(days=1)
        elif timeframe == "week":
            since_date = now - timedelta(days=7)
        else:
            since_date = now - timedelta(days=1)

        date_str = since_date.strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'SINCE "{date_str}"')
        if status != "OK":
            mail.logout()
            return "Failed to search emails for the given timeframe."

        mail_ids = messages[0].split()
        if not mail_ids:
            mail.logout()
            return f"No emails found in '{label}' for timeframe '{timeframe}'."

        target_ids = mail_ids[-count:][::-1]
        results = []
        for m_id in target_ids:
            status, data = mail.fetch(m_id, "(RFC822.HEADER BODY[TEXT]<0.500>)")
            header_content = ""
            body_snippet = ""
            for part in data:
                if isinstance(part, tuple):
                    if b"HEADER" in part[0]:
                        msg = email.message_from_bytes(part[1])
                        subject = _decode_str(msg.get("Subject"))
                        sender = _decode_str(msg.get("From"))
                        date = msg.get("Date")
                        header_content = f"From: {sender}\nSubject: {subject}\nDate: {date}"
                    else:
                        body_snippet = part[1].decode(errors="ignore").strip()
            results.append(
                f"--- Email ID: {m_id.decode()} ---\n{header_content}\nSnippet: {body_snippet[:200]}..."
            )

        mail.logout()
        return f"Found {len(results)} emails in '{label}' from '{timeframe}':\n\n" + "\n\n".join(
            results
        )
    except Exception as exc:
        return f"Error during fetch for summary: {str(exc)}"


@mcp.tool()
async def list_unread_emails(count: int = 5) -> str:
    """Lists the most recent unread emails in the inbox."""
    try:
        params = _ListUnreadEmailsInput.model_validate({"count": count})
        count = params.count

        mail = _get_imap_connection()
        mail.select("inbox", readonly=True)

        since_date = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'UNSEEN SINCE "{since_date}"')
        if status != "OK":
            mail.logout()
            return "Failed to search unread emails."

        mail_ids = messages[0].split()
        if not mail_ids:
            mail.logout()
            return "No unread emails found in the last 30 days."

        recent_ids = mail_ids[-count:][::-1]
        results = []
        for m_id in recent_ids:
            status, data = mail.fetch(m_id, "(RFC822.HEADER)")
            msg = email.message_from_bytes(data[0][1])
            subject = _decode_str(msg.get("Subject"))
            sender = _decode_str(msg.get("From"))
            date = msg.get("Date")
            results.append(
                f"ID: {m_id.decode()} | Date: {date} | From: {sender} | Subject: {subject}"
            )

        mail.logout()
        return "Unread Emails (last 30 days):\n" + "\n".join(results)
    except Exception as exc:
        return f"Error listing unread emails: {str(exc)}"


@mcp.tool()
async def mark_as_read(email_id: str) -> str:
    """Marks a specific email as read (seen)."""
    try:
        params = _MarkAsReadInput.model_validate({"email_id": email_id})
        email_id = params.email_id

        mail = _get_imap_connection()
        mail.select("inbox")
        status, response = mail.store(email_id, "+FLAGS", "\\Seen")
        mail.logout()
        if status == "OK":
            return f"Email {email_id} has been marked as read."
        return f"Failed to mark email {email_id} as read."
    except Exception as exc:
        return f"Error marking email as read: {str(exc)}"


@mcp.tool()
async def list_labels() -> str:
    """Lists all available Gmail labels (folders)."""
    try:
        mail = _get_imap_connection()
        status, labels = mail.list()
        mail.logout()
        if status != "OK":
            return "Failed to list labels."
        return "\n".join(label.decode() for label in labels)
    except Exception as exc:
        return f"Error listing labels: {str(exc)}"


@mcp.tool()
async def search_emails_by_label(label: str, count: int = 5) -> str:
    """Lists recent emails from a specific label (folder)."""
    try:
        params = _SearchEmailsByLabelInput.model_validate({"label": label, "count": count})
        label = params.label
        count = params.count

        mail = _get_imap_connection()
        quoted_label = f'"{label}"'
        status, response = mail.select(quoted_label, readonly=True)
        if status != "OK":
            mail.logout()
            return f"Label '{label}' not found or inaccessible."

        total_messages = int(response[0])
        if total_messages == 0:
            mail.logout()
            return f"No emails found in label '{label}'."

        start = max(1, total_messages - count + 1)
        end = total_messages
        status, data = mail.fetch(f"{start}:{end}", "(RFC822.HEADER)")
        messages_data = [data[i] for i in range(len(data)) if isinstance(data[i], tuple)]

        results = []
        for i in range(len(messages_data) - 1, -1, -1):
            msg_id_part, msg_content = messages_data[i]
            seq_num = msg_id_part.split()[0].decode()
            msg = email.message_from_bytes(msg_content)
            subject = _decode_str(msg.get("Subject"))
            sender = _decode_str(msg.get("From"))
            results.append(f"Seq: {seq_num} | From: {sender} | Subject: {subject}")

        mail.logout()
        return f"Recent emails in '{label}':\n" + "\n".join(results)
    except Exception as exc:
        return f"Error searching label '{label}': {str(exc)}"


@mcp.tool()
async def search_emails(query: str) -> str:
    """Searches for emails containing a specific keyword in subject or body."""
    try:
        params = _SearchEmailsInput.model_validate({"query": query})
        query = params.query

        mail = _get_imap_connection()
        mail.select("inbox")
        status, messages = mail.search(None, f'TEXT "{query}"')
        if status != "OK":
            mail.logout()
            return "Search failed."

        mail_ids = messages[0].split()
        if not mail_ids:
            mail.logout()
            return f"No emails found matching '{query}'"

        results = []
        for m_id in mail_ids[-10:][::-1]:
            status, data = mail.fetch(m_id, "(RFC822.HEADER)")
            msg = email.message_from_bytes(data[0][1])
            subject = _decode_str(msg.get("Subject"))
            sender = _decode_str(msg.get("From"))
            results.append(f"ID: {m_id.decode()} | From: {sender} | Subject: {subject}")

        mail.logout()
        return "\n".join(results)
    except Exception as exc:
        return f"Error searching emails: {str(exc)}"


@mcp.tool()
async def send_email(to_email: str, subject: str, body: str) -> str:
    """Sends a plain text email to a specified recipient."""
    try:
        params = _SendEmailInput.model_validate(
            {"to_email": to_email, "subject": subject, "body": body}
        )
        to_email = params.to_email
        subject = params.subject
        body = params.body

        email_account, app_password = _get_credentials()
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = email_account
        msg["To"] = to_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_account, app_password)
            server.send_message(msg)

        return f"Email successfully sent to {to_email}"
    except Exception as exc:
        return f"Error sending email: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
