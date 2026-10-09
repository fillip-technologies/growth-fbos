"""
Recurrence rules (RFC 5545 RRULE, read by python-dateutil), in the rule's own time zone: "every
Monday at 09:00" means 09:00 where the rule is kept, in every season.

A series begins at its start (the RRULE's DTSTART), so INTERVAL and COUNT keep their place
however often it is read. An UNTIL may be given in UTC (`...Z`, as RFC 5545 asks) or in the
rule's own time; a date alone runs to the end of that day. Rules repeating more often than
hourly are refused: a task every minute is a mistake, and reading such a series back to its
start would be slow.
"""
from dataclasses import dataclass
from datetime import datetime, time, timezone
import re
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import MINUTELY, SECONDLY, rrule, rrulestr

# An UNTIL with no "Z": the whole value, up to the next part or the end.
_LOCAL_UNTIL = re.compile(r"UNTIL=(\d{8})(?:T(\d{6}))?(?=;|\s*$)")


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _until_in_utc(text: str, zone: ZoneInfo) -> str:
    """An UNTIL in the rule's own time, given in UTC instead (dateutil asks it of a zoned series)."""

    def in_utc(found: re.Match) -> str:
        day = datetime.strptime(found.group(1), "%Y%m%d").date()
        clock = datetime.strptime(found.group(2), "%H%M%S").time() if found.group(2) else time(23, 59, 59)
        moment = datetime.combine(day, clock, tzinfo=zone).astimezone(timezone.utc)
        return f"UNTIL={moment:%Y%m%dT%H%M%S}Z"

    return _LOCAL_UNTIL.sub(in_utc, text)


@dataclass(frozen=True)
class Series:
    rule: rrule
    zone: ZoneInfo

    def _local(self, moment: datetime) -> datetime:
        return _utc(moment).astimezone(self.zone)

    @staticmethod
    def _back(found: Optional[datetime]) -> Optional[datetime]:
        return found.astimezone(timezone.utc) if found is not None else None

    def first_from(self, moment: datetime) -> Optional[datetime]:
        """The first occurrence at or after `moment`."""
        return self._back(self.rule.after(self._local(moment), inc=True))

    def last_until(self, moment: datetime) -> Optional[datetime]:
        """The latest occurrence at or before `moment`."""
        return self._back(self.rule.before(self._local(moment), inc=True))

    def next_after(self, moment: datetime) -> Optional[datetime]:
        """The first occurrence strictly after `moment`."""
        return self._back(self.rule.after(self._local(moment), inc=False))


def series(text: str, start: datetime, timezone_name: str) -> Series:
    """The series a rule describes from `start`; ValueError when the rule or its time zone isn't valid."""
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown time zone {timezone_name!r}") from exc
    dtstart = _utc(start).astimezone(zone).replace(microsecond=0)
    parsed = rrulestr(_until_in_utc(text, zone), dtstart=dtstart)
    if not isinstance(parsed, rrule):
        raise ValueError("Give one RRULE")
    # dateutil keeps the frequency only on this attribute.
    if parsed._freq in (SECONDLY, MINUTELY):
        raise ValueError("Rules may repeat at most hourly")
    return Series(rule=parsed, zone=zone)
