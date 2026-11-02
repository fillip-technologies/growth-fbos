"""Small helpers every management service module uses."""

from datetime import date
import logging
from typing import Iterable, Optional, TypeVar
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ManagementServiceError,
    PreconditionRequiredError,
    ValidationFailedError,
    VersionConflictError,
)
from schemas.common import UnitRef, UserRef
from services.identity_client import IdentityClient

logger = logging.getLogger("management.service")

ModelT = TypeVar("ModelT")


def check_if_match(if_match: Optional[str], current_version: int) -> None:
    """Optimistic concurrency: the caller must send the version they last saw."""
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip().removeprefix("W/").strip('"')
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


def check_date_range(start: date, end: date, *, start_field: str = "start_date", end_field: str = "end_date") -> None:
    if end < start:
        raise ValidationFailedError(end_field, f"must be on or after {start_field}")


async def get_in_org(
    session: AsyncSession, model: type[ModelT], record_id: uuid.UUID, org_id: uuid.UUID, error: ManagementServiceError
) -> ModelT:
    """The record, when it exists and belongs to the organization; anyone else's is not found."""
    record = await session.get(model, record_id)
    if record is None or getattr(record, "organization_id") != org_id:
        raise error
    return record


def as_float(value: Optional[object]) -> Optional[float]:
    return float(value) if value is not None else None


class Directory:
    """
    Names of people and units for one request, looked up in identity once. A name is a courtesy:
    when identity can't answer, references go out with the id and no name rather than failing the read.
    """

    def __init__(self, identity: IdentityClient, organization_id: uuid.UUID) -> None:
        self._identity = identity
        self._organization_id = organization_id
        self._people: Optional[dict[uuid.UUID, str]] = None
        self._units: dict[uuid.UUID, Optional[str]] = {}

    async def user(self, user_id: Optional[uuid.UUID]) -> Optional[UserRef]:
        if user_id is None:
            return None
        if self._people is None:
            try:
                self._people = await self._identity.people_names(self._organization_id)
            except ManagementServiceError as exc:
                logger.info("People names unavailable: %s", exc.detail)
                self._people = {}
        return UserRef(id=user_id, name=self._people.get(user_id))

    async def users(self, user_ids: Iterable[Optional[uuid.UUID]]) -> dict[uuid.UUID, UserRef]:
        refs = {}
        for user_id in user_ids:
            ref = await self.user(user_id)
            if ref is not None:
                refs[ref.id] = ref
        return refs

    async def unit(self, unit_id: Optional[uuid.UUID]) -> Optional[UnitRef]:
        if unit_id is None:
            return None
        if unit_id not in self._units:
            try:
                self._units[unit_id] = await self._identity.unit_name(self._organization_id, unit_id)
            except ManagementServiceError as exc:
                logger.info("Unit name unavailable: %s", exc.detail)
                self._units[unit_id] = None
        return UnitRef(id=unit_id, name=self._units[unit_id])
