"""
Working time from a working calendar (identity's: weekly hours in a time zone, and holidays): how
many working minutes lie between two moments, and when a number of working minutes runs out.

`weekly_hours` is {"mon": [["09:00", "18:00"], ...], ...}: a missing or empty day is a day off,
and several ranges leave the gaps between them (a lunch break) out. A holiday is a day off; a
half-day holiday keeps the first half of that day's working time. A calendar without any working
time can't run a clock, so it isn't used: time then runs around the clock.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# How far a clock may look ahead or back, in days: a limit further out is out of reach.
_MAX_DAYS = 3 * 366

Ranges = tuple[tuple[int, int], ...]  # working ranges of a day, as minutes after midnight


def _minutes(clock: str) -> Optional[int]:
    hours, _, minutes = str(clock).partition(":")
    if not (hours.isdigit() and minutes.isdigit()):
        return None
    total = int(hours) * 60 + int(minutes)
    return total if 0 <= total <= 24 * 60 else None


def _day(ranges: Any) -> Ranges:
    parsed = []
    for pair in ranges if isinstance(ranges, list) else []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        start, end = _minutes(pair[0]), _minutes(pair[1])
        if start is not None and end is not None and end > start:
            parsed.append((start, end))
    return tuple(sorted(parsed))


def _first_half(ranges: Ranges) -> Ranges:
    """The first half of a day's working time: what a half-day holiday leaves."""
    keep = sum(end - start for start, end in ranges) / 2
    kept = []
    for start, end in ranges:
        if keep <= 0:
            break
        kept.append((start, start + min(end - start, keep)))
        keep -= end - start
    return tuple(kept)


@dataclass(frozen=True)
class WorkCalendar:
    zone: ZoneInfo
    weekly: tuple[Ranges, ...]  # Monday first
    holidays: dict[date, bool]  # day -> whether it is only a half day off

    def _open(self, day: date) -> list[tuple[datetime, datetime]]:
        ranges = self.weekly[day.weekday()]
        half_day = self.holidays.get(day)
        if half_day is False:
            return []
        if half_day:
            ranges = _first_half(ranges)
        midnight = datetime.combine(day, time(0), tzinfo=self.zone)
        return [(midnight + timedelta(minutes=start), midnight + timedelta(minutes=end)) for start, end in ranges]

    def minutes_between(self, start: datetime, end: datetime) -> float:
        """Working minutes from `start` to `end` (none when `end` isn't later)."""
        if end <= start:
            return 0.0
        day = start.astimezone(self.zone).date()
        last = min(end.astimezone(self.zone).date(), day + timedelta(days=_MAX_DAYS))
        total = 0.0
        while day <= last:
            for opens, closes in self._open(day):
                overlap = (min(closes, end) - max(opens, start)).total_seconds()
                if overlap > 0:
                    total += overlap / 60
            day += timedelta(days=1)
        return total

    def add_minutes(self, start: datetime, minutes: float) -> datetime:
        """When `minutes` of working time from `start` have passed."""
        remaining = minutes
        if remaining <= 0:
            return start
        day = start.astimezone(self.zone).date()
        for _ in range(_MAX_DAYS):
            for opens, closes in self._open(day):
                begin = max(opens, start)
                available = (closes - begin).total_seconds() / 60
                if available <= 0:
                    continue
                if available >= remaining:
                    return (begin + timedelta(minutes=remaining)).astimezone(timezone.utc)
                remaining -= available
            day += timedelta(days=1)
        return start + timedelta(days=_MAX_DAYS)


def calendar_from(data: dict) -> Optional[WorkCalendar]:
    """A calendar as identity describes it; None when it has no working time or an unknown time zone."""
    try:
        zone = ZoneInfo(str(data.get("timezone") or ""))
    except (ZoneInfoNotFoundError, ValueError):
        return None
    hours = data.get("weekly_hours") or {}
    weekly = tuple(_day(hours.get(key)) for key in DAY_KEYS)
    if not any(weekly):
        return None
    holidays = {}
    for holiday in data.get("holidays") or []:
        try:
            holidays[date.fromisoformat(str(holiday["date"]))] = bool(holiday.get("is_half_day"))
        except (KeyError, ValueError):
            continue
    return WorkCalendar(zone=zone, weekly=weekly, holidays=holidays)
