"""Effective periods: [effective_from, effective_to), open-ended when effective_to is None."""

from datetime import date
from itertools import groupby
from typing import Iterable, Optional

Period = tuple[str, str, date, Optional[date]]  # kind, code, effective_from, effective_to


def periods_overlap(first_start: date, first_end: Optional[date], second_start: date, second_end: Optional[date]) -> bool:
    first_before_second = first_end is not None and first_end <= second_start
    second_before_first = second_end is not None and second_end <= first_start
    return not (first_before_second or second_before_first)


def find_overlaps(periods: Iterable[Period]) -> list[tuple[str, str]]:
    """(kind, code) pairs that have two entries in effect on the same day."""
    clashes: list[tuple[str, str]] = []
    ordered = sorted(periods, key=lambda period: (period[0], period[1], period[2]))
    for (kind, code), group in groupby(ordered, key=lambda period: (period[0], period[1])):
        spans = [(start, end) for _, _, start, end in group]
        if any(periods_overlap(*earlier, *later) for earlier, later in zip(spans, spans[1:])):
            clashes.append((kind, code))
    return clashes
