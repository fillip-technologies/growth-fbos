"""
Registration numbers: each regime names its validator (`registration_validator`) and where the
number spells the jurisdiction (`registration_jurisdiction`). The algorithms live here; which
one a regime uses is configuration.
"""

import re
from typing import Callable, Optional

from finance.errors import TaxConfigError
from finance.tax.config_schema import RegimeData

_GSTIN_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_SHAPE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gstin_check_character(first_fourteen: str) -> str:
    """The GSTIN's 15th character: a mod-36 checksum over the first fourteen."""
    total = 0
    for position, character in enumerate(first_fourteen):
        product = _GSTIN_CHARSET.index(character) * (2 if position % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARSET[(36 - total % 36) % 36]


def _gstin_problem(number: str) -> Optional[str]:
    if not _GSTIN_SHAPE.match(number):
        return "it is not 15 characters shaped like a GSTIN (2 digits, PAN, entity number, Z, check character)"
    if gstin_check_character(number[:14]) != number[14]:
        return "its check character is wrong"
    return None


REGISTRATION_VALIDATORS: dict[str, Callable[[str], Optional[str]]] = {
    "gstin": _gstin_problem,
}


def normalize_registration_no(number: str) -> str:
    return number.strip().upper()


def validate_registration_no(regime_code: str, regime: RegimeData, number: str) -> str:
    normalized = normalize_registration_no(number)
    if not regime.registration_validator:
        return normalized
    validator = REGISTRATION_VALIDATORS.get(regime.registration_validator)
    if validator is None:
        raise TaxConfigError(
            "REGISTRATION_VALIDATOR_UNKNOWN",
            f"Regime {regime_code} asks for the '{regime.registration_validator}' validator, which does not exist.",
        )
    problem = validator(normalized)
    if problem:
        raise TaxConfigError(
            "REGISTRATION_NUMBER_INVALID", f"'{normalized}' is not a valid {regime.name} registration: {problem}."
        )
    return normalized


def jurisdiction_from_registration(regime: RegimeData, number: Optional[str]) -> Optional[str]:
    if not number or regime.registration_jurisdiction is None:
        return None
    where = regime.registration_jurisdiction
    normalized = normalize_registration_no(number)
    if len(normalized) < where.start + where.length:
        return None
    return normalized[where.start : where.start + where.length]
