"""Optimistic concurrency: an update names the version it read (If-Match) and fails if it moved on."""

from typing import Optional

from exceptions import PreconditionRequiredError, VersionConflictError


def check_version(if_match: Optional[str], version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    if int(if_match.strip('"').replace("W/", "")) != version:
        raise VersionConflictError(version)
