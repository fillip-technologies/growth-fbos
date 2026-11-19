"""
Sortable position keys for cards on a board (fractional indexing): a key that sorts between
two others can always be made without renumbering the rest.

Keys use only 0-9 and a-z, which sort the same way under byte order and the usual database
collations, and never end in '0', so there is always room below a key.
"""
from typing import Optional

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
# Past this length a column is renumbered instead (services/boards.py).
MAX_RANK_LENGTH = 64


def rank_between(before: Optional[str], after: Optional[str]) -> str:
    """A key that sorts after `before` and before `after` (None: no bound on that side)."""
    low = before or ""
    if after is not None and low >= after:
        raise ValueError(f"{low!r} must sort before {after!r}")
    return _midpoint(low, after)


def _midpoint(low: str, high: Optional[str]) -> str:
    if high is not None:
        # Keep the prefix the two share, and find a key between what follows.
        shared = 0
        while shared < len(high) and (low[shared] if shared < len(low) else "0") == high[shared]:
            shared += 1
        if shared:
            return high[:shared] + _midpoint(low[shared:], high[shared:])
    low_digit = DIGITS.index(low[0]) if low else 0
    high_digit = DIGITS.index(high[0]) if high is not None else len(DIGITS)
    if high_digit - low_digit > 1:
        return DIGITS[(low_digit + high_digit) // 2]
    # Neighbouring digits: a longer `high` leaves room under its first digit.
    if high is not None and len(high) > 1:
        return high[0]
    return DIGITS[low_digit] + _midpoint(low[1:], None)


def spread_ranks(count: int) -> list[str]:
    """`count` keys in order, evenly spaced and all the same length, for renumbering a column."""
    width = 1
    while len(DIGITS) ** width <= count:
        width += 1
    return [_base36(i + 1, width) + "i" for i in range(count)]


def _base36(value: int, width: int) -> str:
    digits = []
    while value:
        value, remainder = divmod(value, len(DIGITS))
        digits.append(DIGITS[remainder])
    return "".join(reversed(digits)).rjust(width, "0")
