import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Deliberately loose: the mail server is the real judge, this only catches typing slips.
EMAIL_PATTERN = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
MAX_RECIPIENTS = 50


def _check_addresses(addresses: list[str]) -> list[str]:
    cleaned: list[str] = []
    for address in addresses:
        address = address.strip()
        if not EMAIL_PATTERN.match(address):
            raise ValueError(f"'{address}' is not an email address")
        if address.lower() not in {a.lower() for a in cleaned}:
            cleaned.append(address)
    return cleaned


class EmailAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field("application/octet-stream", max_length=255)
    content_base64: str


class EmailCreate(BaseModel):
    """One email to send now (POST /internal/emails)."""

    model_config = ConfigDict(extra="forbid")

    to: list[str] = Field(..., min_length=1, max_length=MAX_RECIPIENTS)
    cc: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    bcc: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    reply_to: Optional[str] = None
    subject: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1)
    html: Optional[str] = None
    attachments: list[EmailAttachment] = Field(default_factory=list, max_length=20)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _check_addresses(value)

    @field_validator("reply_to")
    @classmethod
    def _reply_to(cls, value: Optional[str]) -> Optional[str]:
        return _check_addresses([value])[0] if value else None


class EmailSender(BaseModel):
    address: Optional[str] = None
    name: str
    enabled: bool


class EmailSent(BaseModel):
    message_id: str
    from_address: str
    from_name: str
    recipients: int
