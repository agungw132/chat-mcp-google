from email.message import EmailMessage

import pytest

from chat_google.mcp_servers import gmail_server


def _header_bytes(subject: str, sender: str, date: str = "Fri, 01 Jan 2026 10:00:00 +0000"):
    return (
        f"Subject: {subject}\r\n"
        f"From: {sender}\r\n"
        f"Date: {date}\r\n\r\n"
    ).encode()


def _full_email_bytes(subject: str, sender: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "tester@example.com"
    msg.set_content(body)
    return msg.as_bytes()


@pytest.mark.asyncio
async def test_list_recent_emails(monkeypatch):
    class FakeMail:
        def select(self, mailbox, readonly=False):
            return "OK", [b"2"]

        def fetch(self, sequence, fields):
            assert sequence == "1:2"
            return "OK", [
                (b"1 (RFC822.HEADER)", _header_bytes("Old", "old@example.com")),
                (b"2 (RFC822.HEADER)", _header_bytes("New", "new@example.com")),
                b")",
            ]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.list_recent_emails(count=2)
    assert "Subject: New" in result
    assert "Subject: Old" in result
    assert "Seq: 2" in result


@pytest.mark.asyncio
async def test_read_email(monkeypatch):
    class FakeMail:
        def select(self, mailbox):
            return "OK", [b""]

        def fetch(self, email_id, fields):
            assert email_id == "10"
            payload = _full_email_bytes("Hello", "alice@example.com", "Body content")
            return "OK", [(b"10 (RFC822)", payload)]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.read_email("10")
    assert "Subject: Hello" in result
    assert "From: alice@example.com" in result
    assert "Body content" in result


@pytest.mark.asyncio
async def test_summarize_emails(monkeypatch):
    class FakeMail:
        def select(self, mailbox, readonly=False):
            return "OK", [b""]

        def search(self, charset, query):
            assert "SINCE" in query
            return "OK", [b"11 22"]

        def fetch(self, email_id, fields):
            header = _header_bytes(f"Subject {email_id.decode()}", "sender@example.com")
            snippet = b"This is a snippet from the email body."
            return "OK", [
                (b"22 (RFC822.HEADER)", header),
                (b"22 (BODY[TEXT]<0>)", snippet),
            ]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.summarize_emails(timeframe="24h", label="inbox", count=2)
    assert "Found 2 emails" in result
    assert "Email ID: 22" in result
    assert "Snippet:" in result


@pytest.mark.asyncio
async def test_list_unread_emails(monkeypatch):
    class FakeMail:
        def select(self, mailbox, readonly=False):
            return "OK", [b""]

        def search(self, charset, query):
            return "OK", [b"31 32"]

        def fetch(self, email_id, fields):
            return "OK", [(b"", _header_bytes("Unread", "noreply@example.com"))]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.list_unread_emails(count=1)
    assert "Unread Emails" in result
    assert "ID: 32" in result


@pytest.mark.asyncio
async def test_mark_as_read(monkeypatch):
    class FakeMail:
        def select(self, mailbox):
            return "OK", [b""]

        def store(self, email_id, op, flag):
            assert email_id == "77"
            assert op == "+FLAGS"
            assert flag == "\\Seen"
            return "OK", [b""]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.mark_as_read("77")
    assert "has been marked as read" in result


@pytest.mark.asyncio
async def test_list_labels(monkeypatch):
    class FakeMail:
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Work"']

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.list_labels()
    assert "INBOX" in result
    assert "Work" in result


@pytest.mark.asyncio
async def test_search_emails_by_label(monkeypatch):
    class FakeMail:
        def select(self, mailbox, readonly=False):
            assert mailbox == '"Work"'
            return "OK", [b"1"]

        def fetch(self, sequence, fields):
            return "OK", [(b"1 (RFC822.HEADER)", _header_bytes("Project Update", "pm@example.com"))]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.search_emails_by_label("Work", count=5)
    assert "Recent emails in 'Work'" in result
    assert "Project Update" in result


@pytest.mark.asyncio
async def test_search_emails(monkeypatch):
    class FakeMail:
        def select(self, mailbox):
            return "OK", [b""]

        def search(self, charset, query):
            assert 'TEXT "sumopod"' in query
            return "OK", [b"9 10"]

        def fetch(self, email_id, fields):
            return "OK", [(b"", _header_bytes("Match", "bot@example.com"))]

        def logout(self):
            return None

    monkeypatch.setattr(gmail_server, "_get_imap_connection", lambda: FakeMail())
    result = await gmail_server.search_emails("sumopod")
    assert "ID: 10" in result
    assert "Subject: Match" in result


@pytest.mark.asyncio
async def test_send_email(monkeypatch):
    calls = {"login": None, "to": None, "subject": None, "body": None}

    class FakeSMTP:
        def __init__(self, host, port):
            assert host == "smtp.gmail.com"
            assert port == 465

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, message):
            calls["to"] = message["To"]
            calls["subject"] = message["Subject"]
            calls["body"] = message.get_payload()

    monkeypatch.setattr(gmail_server.smtplib, "SMTP_SSL", FakeSMTP)
    result = await gmail_server.send_email("dest@example.com", "Hi", "Hello there")
    assert "successfully sent" in result
    assert calls["login"] == ("tester@example.com", "app-password")
    assert calls["to"] == "dest@example.com"
    assert calls["subject"] == "Hi"
    assert "Hello there" in calls["body"]


@pytest.mark.asyncio
async def test_list_recent_emails_invalid_count(monkeypatch):
    monkeypatch.setattr(
        gmail_server,
        "_get_imap_connection",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = await gmail_server.list_recent_emails(count=0)
    assert result.startswith("Error listing emails:")
    assert "greater than or equal to 1" in result
