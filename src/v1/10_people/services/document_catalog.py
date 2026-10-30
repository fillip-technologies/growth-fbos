"""
The kinds of document an employee file holds, and how their numbers are checked.

A type with `number_label` carries an ID number (stored encrypted); the others are files only.
Adding a type means adding one entry here.
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional

from exceptions import ValidationFailedError

# Verhoeff checksum tables (Aadhaar numbers end with a check digit).
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(number: str) -> bool:
    check = 0
    for i, digit in enumerate(reversed(number)):
        check = _D[check][_P[i % 8][int(digit)]]
    return check == 0


def _pattern(regex: str, hint: str) -> Callable[[str], Optional[str]]:
    compiled = re.compile(regex)
    return lambda value: None if compiled.fullmatch(value) else hint


def _aadhaar(value: str) -> Optional[str]:
    if not re.fullmatch(r"[2-9][0-9]{11}", value):
        return "Aadhaar must be 12 digits and cannot start with 0 or 1"
    return None if _verhoeff_ok(value) else "Aadhaar number is not valid (check digit does not match)"


@dataclass(frozen=True)
class DocumentType:
    code: str
    label: str
    number_label: Optional[str] = None
    validate: Optional[Callable[[str], Optional[str]]] = None
    has_expiry: bool = False

    @property
    def has_number(self) -> bool:
        return self.number_label is not None


def _compact(value: str) -> str:
    return re.sub(r"[\s-]", "", value).upper()


DOCUMENT_TYPES: dict[str, DocumentType] = {
    t.code: t
    for t in (
        DocumentType("pan", "PAN card", "PAN", _pattern(r"[A-Z]{5}[0-9]{4}[A-Z]", "PAN must look like ABCDE1234F")),
        DocumentType("aadhaar", "Aadhaar card", "Aadhaar number", _aadhaar),
        DocumentType("passport", "Passport", "Passport number", _pattern(r"[A-Z][0-9]{7}", "Passport number must look like A1234567"), has_expiry=True),
        DocumentType("driving_licence", "Driving licence", "Licence number", _pattern(r"[A-Z0-9/]{5,20}", "Licence number must be 5 to 20 letters or digits"), has_expiry=True),
        DocumentType("voter_id", "Voter ID", "EPIC number", _pattern(r"[A-Z]{3}[0-9]{7}", "Voter ID must look like ABC1234567")),
        DocumentType("uan", "PF / UAN", "UAN", _pattern(r"[0-9]{12}", "UAN must be 12 digits")),
        DocumentType("esic_ip", "ESIC insurance", "ESIC IP number", _pattern(r"([0-9]{10}|[0-9]{17})", "ESIC number must be 10 or 17 digits")),
        DocumentType("address_proof", "Address proof"),
        DocumentType("education", "Education certificates"),
        DocumentType("photo", "Photograph"),
        DocumentType("offer_letter", "Signed offer letter"),
        DocumentType("contract", "Employment contract"),
        DocumentType("nda", "NDA"),
        DocumentType("relieving_letter", "Previous relieving letter"),
    )
}

# Onboarding item that is not a document: an employee needs a verified primary bank account.
BANK_ACCOUNT_ITEM = "bank_account"
BANK_ACCOUNT_LABEL = "Bank account"

# Required until a company saves its own list.
DEFAULT_REQUIRED = ("pan", "aadhaar", "address_proof", "offer_letter", "nda", BANK_ACCOUNT_ITEM)
ALL_ITEMS = tuple(DOCUMENT_TYPES) + (BANK_ACCOUNT_ITEM,)


def get_type(code: str) -> DocumentType:
    doc_type = DOCUMENT_TYPES.get(code)
    if doc_type is None:
        raise ValidationFailedError("document_type", f"Unknown document type '{code}'")
    return doc_type


def normalize_number(doc_type: DocumentType, raw: str) -> str:
    """The number as stored (no spaces or dashes, upper case), or a 422 saying what is wrong."""
    if not doc_type.has_number:
        raise ValidationFailedError("document_number", f"{doc_type.label} has no number")
    value = _compact(raw)
    problem = doc_type.validate(value) if doc_type.validate else None
    if problem:
        raise ValidationFailedError("document_number", problem)
    return value


IFSC_RE = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")
ACCOUNT_RE = re.compile(r"[0-9]{9,18}")
