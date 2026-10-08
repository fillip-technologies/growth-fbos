"""Optimistic concurrency: a write names, in If-Match, the version it was made against."""
from typing import Optional

from exceptions import PreconditionRequiredError, VersionConflictError


def check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)
