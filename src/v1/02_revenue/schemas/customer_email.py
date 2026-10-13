"""Emailing a record (a quotation, a contract) and files chosen from it to the customer."""

import re
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Deliberately loose: the mail server is the real judge, this only catches typing slips.
EMAIL_PATTERN = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def _clean_addresses(addresses: list[str]) -> list[str]:
    cleaned: list[str] = []
    for address in (a.strip() for a in addresses):
        if not EMAIL_PATTERN.match(address):
            raise ValueError(f"'{address}' is not an email address")
        if address.lower() not in {a.lower() for a in cleaned}:
            cleaned.append(address)
    return cleaned


class CustomerEmailCreate(BaseModel):
    """POST /<records>/{id}/emails: the record and the files chosen from it, to the customer."""

    model_config = ConfigDict(extra="forbid")

    to: list[str] = Field(..., min_length=1, max_length=50)
    cc: list[str] = Field(default_factory=list, max_length=50)
    bcc: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=20000)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _clean_addresses(value)


class EmailSenderInfo(BaseModel):
    address: Optional[str] = None
    name: str = ""
    enabled: bool = False


class EmailContact(BaseModel):
    name: str
    email: str
    designation: Optional[str] = None
    is_primary: bool = False


class CustomerEmailDraft(BaseModel):
    """What the send-by-email form starts from."""

    sender: EmailSenderInfo
    contacts: list[EmailContact]
    to: list[str]
    subject: str
    message: str
    # Emailing a draft or approved quotation also marks it sent (and freezes it).
    marks_sent: bool = False
    emailable: bool


class EmailedFile(BaseModel):
    document_id: uuid.UUID
    file_name: str
    size_bytes: int


class CustomerEmailSent(BaseModel):
    from_address: str
    from_name: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    attachments: list[EmailedFile]
