"""Decimal money helpers. Floats never take part in a tax calculation."""

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Optional, Union

ZERO = Decimal("0")
HUNDRED = Decimal("100")

# ISO 4217 currencies whose minor unit is not two decimal places.
_MINOR_UNITS_EXCEPTIONS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "BHD": 3, "JOD": 3, "KWD": 3, "OMR": 3, "TND": 3}

ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "up": ROUND_UP,
    "down": ROUND_DOWN,
}

Numeric = Union[Decimal, int, float, str]


def to_decimal(value: Optional[Numeric]) -> Decimal:
    """A Decimal from any stored or posted number; floats go through str so 0.1 stays 0.1."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money_quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-_MINOR_UNITS_EXCEPTIONS.get(currency.upper(), 2))


def round_money(amount: Decimal, currency: str, mode: str = "half_up") -> Decimal:
    return amount.quantize(money_quantum(currency), rounding=ROUNDING_MODES[mode])


def round_to_increment(amount: Decimal, increment: Decimal, mode: str = "half_up") -> Decimal:
    """Round to a multiple of `increment` (e.g. the nearest rupee for an invoice's round-off)."""
    steps = (amount / increment).quantize(Decimal(1), rounding=ROUNDING_MODES[mode])
    return steps * increment


def as_float(amount: Decimal) -> float:
    """For the API's Money schema, which still carries floats (and renders them as 2-place strings)."""
    return float(amount)
