"""
The working calendars delivery's time limits run on, for organizations that count working hours
(the `working_hours` setting): a team follows its own calendar, else the nearest unit's above it,
else the company's (identity decides, /internal/work-calendars). No calendar: the clock.

Kept in memory for a few minutes per organization, so reading tasks doesn't wait on identity.
When identity can't answer, the last copy is used; with none, `of` answers None (unknown): pages
then show clock time, and the alert check leaves the organization for its next run.
"""
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Optional, Protocol
import uuid

from exceptions import WorkingCalendarsUnavailableError
from services.work_calendar import WorkCalendar, calendar_from

logger = logging.getLogger("delivery.calendars")

KEEP_SECONDS = 600


class CalendarSource(Protocol):
    """Identity, through `IdentityClient.work_calendars`."""

    async def work_calendars(self, organization_id: uuid.UUID) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OrgCalendars:
    company: Optional[WorkCalendar] = None
    units: dict[uuid.UUID, Optional[WorkCalendar]] = field(default_factory=dict)

    def for_unit(self, unit_id: Optional[uuid.UUID]) -> Optional[WorkCalendar]:
        """The calendar a unit's work runs on; a unit identity didn't name (new since) follows the company's."""
        if unit_id is None or unit_id not in self.units:
            return self.company
        return self.units[unit_id]


def _org_calendars(raw: dict[str, Any]) -> OrgCalendars:
    calendars = {uuid.UUID(c["id"]): calendar_from(c) for c in raw.get("calendars") or []}

    def named(calendar_id: Optional[str]) -> Optional[WorkCalendar]:
        return calendars.get(uuid.UUID(calendar_id)) if calendar_id else None

    return OrgCalendars(
        company=named(raw.get("company_calendar_id")),
        units={uuid.UUID(unit_id): named(calendar_id) for unit_id, calendar_id in (raw.get("unit_calendars") or {}).items()},
    )


class WorkingCalendars:
    def __init__(self) -> None:
        self._source: Optional[CalendarSource] = None
        self._remembered: dict[uuid.UUID, tuple[float, OrgCalendars]] = {}

    def start(self, source: CalendarSource) -> None:
        self._source = source
        self._remembered.clear()

    def stop(self) -> None:
        self._source = None
        self._remembered.clear()

    async def of(self, organization_id: uuid.UUID) -> Optional[OrgCalendars]:
        """The organization's calendars; None when they are unknown right now."""
        if self._source is None:
            return None
        remembered = self._remembered.get(organization_id)
        if remembered and time.monotonic() - remembered[0] < KEEP_SECONDS:
            return remembered[1]
        try:
            fresh = _org_calendars(await self._source.work_calendars(organization_id))
        except WorkingCalendarsUnavailableError:
            logger.warning("Working calendars of %s not read; %s", organization_id, "using the last copy" if remembered else "none known")
            return remembered[1] if remembered else None
        self._remembered[organization_id] = (time.monotonic(), fresh)
        return fresh


# Started with identity when the service starts (main.py); in tests, by the tests that need it.
working_calendars = WorkingCalendars()
