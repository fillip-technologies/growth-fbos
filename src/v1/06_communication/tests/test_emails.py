import base64
from email.message import EmailMessage
import smtplib

import pytest

from config import settings
import services.mail_service as mail_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> list[tuple[EmailMessage, list[str]]]:
    """Mail set up and the SMTP call captured instead of made."""
    monkeypatch.setattr(settings, "mail_host", "smtp.test")
    monkeypatch.setattr(settings, "mail_from_address", "sales@acme.test")
    monkeypatch.setattr(settings, "mail_from_name", "Acme Sales")
    sent: list[tuple[EmailMessage, list[str]]] = []
    monkeypatch.setattr(mail_service, "_deliver", lambda msg, recipients: sent.append((msg, recipients)))
    return sent


def _email(**overrides) -> dict:
    body = {
        "to": ["buyer@client.test"],
        "cc": ["boss@client.test"],
        "bcc": ["archive@acme.test"],
        "subject": "Quotation Q-1",
        "text": "Please find the quotation attached.",
        "attachments": [
            {"file_name": "quote.pdf", "mime_type": "application/pdf", "content_base64": base64.b64encode(b"%PDF").decode()}
        ],
    }
    return {**body, **overrides}


async def test_sender_reports_from_address(async_client, smtp):
    response = await async_client.get("/internal/email-sender")
    assert response.status_code == 200
    assert response.json() == {"address": "sales@acme.test", "name": "Acme Sales", "enabled": True}


async def test_sends_with_attachment_and_keeps_bcc_out_of_headers(async_client, smtp):
    response = await async_client.post("/internal/emails", json=_email())

    assert response.status_code == 201, response.text
    assert response.json()["recipients"] == 3
    msg, recipients = smtp[0]
    assert recipients == ["buyer@client.test", "boss@client.test", "archive@acme.test"]
    assert msg["To"] == "buyer@client.test"
    assert msg["Cc"] == "boss@client.test"
    assert msg["Bcc"] is None
    assert "sales@acme.test" in msg["From"]
    attachment = next(msg.iter_attachments())
    assert attachment.get_filename() == "quote.pdf"
    assert attachment.get_content() == b"%PDF"


async def test_bad_address_is_refused(async_client, smtp):
    response = await async_client.post("/internal/emails", json=_email(to=["not-an-email"]))
    assert response.status_code == 422
    assert smtp == []


async def test_not_configured(async_client, monkeypatch):
    monkeypatch.setattr(settings, "mail_host", "")
    response = await async_client.post("/internal/emails", json=_email())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MAIL_NOT_CONFIGURED"


async def test_mail_server_refusal_is_reported(async_client, smtp, monkeypatch):
    def refuse(msg, recipients):
        raise smtplib.SMTPRecipientsRefused({"buyer@client.test": (550, b"no such user")})

    monkeypatch.setattr(mail_service, "_deliver", refuse)
    response = await async_client.post("/internal/emails", json=_email())
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "MAIL_SEND_FAILED"
