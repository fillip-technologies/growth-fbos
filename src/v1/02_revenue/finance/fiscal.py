"""Fiscal and calendar periods, from an organization's fiscal year start (MM-DD)."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


def safe_date(year: int, month: int, day: int) -> date:
    """The date, or the month's last day when it has fewer days (29 February in a common year)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def fiscal_year_start_on(day: date, fiscal_year_start: str) -> date:
    month, start_day = (int(part) for part in fiscal_year_start.split("-"))
    this_year = safe_date(day.year, month, start_day)
    return this_year if day >= this_year else safe_date(day.year - 1, month, start_day)


@dataclass(frozen=True)
class FiscalYear:
    starts: date
    ends: date  # inclusive

    @property
    def label(self) -> str:
        """2026-27 for a year starting in 2026 and ending in 2027; 2026 for a calendar year."""
        if self.starts.year == self.ends.year:
            return str(self.starts.year)
        return f"{self.starts.year}-{str(self.ends.year)[-2:]}"

    @property
    def short_label(self) -> str:
        if self.starts.year == self.ends.year:
            return str(self.starts.year)[-2:]
        return f"{str(self.starts.year)[-2:]}-{str(self.ends.year)[-2:]}"

    def quarter_of(self, day: date) -> int:
        months = (day.year - self.starts.year) * 12 + day.month - self.starts.month
        return months // 3 + 1


def fiscal_year_of(day: date, fiscal_year_start: str) -> FiscalYear:
    starts = fiscal_year_start_on(day, fiscal_year_start)
    next_start = fiscal_year_start_on(safe_date(starts.year + 1, starts.month, starts.day), fiscal_year_start)
    return FiscalYear(starts=starts, ends=next_start - timedelta(days=1))


def day_after_fiscal_year(fiscal_year: FiscalYear, month: int, day: int) -> date:
    """The first given calendar day (e.g. 30 November) after the fiscal year ends."""
    candidate = safe_date(fiscal_year.ends.year, month, day)
    if candidate <= fiscal_year.ends:
        candidate = safe_date(fiscal_year.ends.year + 1, month, day)
    return candidate
