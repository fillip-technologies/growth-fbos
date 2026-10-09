"""Legal deadlines on documents, from `deadline` entries (credit-note limits, ITC reversal dates...)."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from finance.fiscal import day_after_fiscal_year, fiscal_year_of
from finance.tax.config_schema import DeadlineData
from finance.tax.snapshot import ConfigSnapshot


@dataclass(frozen=True)
class Deadline:
    code: str
    description: str
    due_on: date
    severity: str


def deadline_date(deadline: DeadlineData, dates: dict[str, Optional[date]], fiscal_year_start: str) -> Optional[date]:
    rule = deadline.rule
    if rule.type == "after_fy_end":
        anchor = dates.get("tax_point_date") or dates.get("issue_date")
        if anchor is None or rule.month is None or rule.day is None:
            return None
        return day_after_fiscal_year(fiscal_year_of(anchor, fiscal_year_start), rule.month, rule.day)
    anchor = dates.get(rule.field or "")
    if anchor is None or rule.days is None:
        return None
    return anchor + timedelta(days=rule.days)


def deadlines_for(
    snapshot: ConfigSnapshot, regime_code: str, doc_type: str, dates: dict[str, Optional[date]], fiscal_year_start: str
) -> list[Deadline]:
    found: list[Deadline] = []
    for entry in snapshot.entries("deadline"):
        deadline: DeadlineData = entry.data  # type: ignore[assignment]
        if deadline.regime != regime_code or doc_type not in deadline.applies_to:
            continue
        due_on = deadline_date(deadline, dates, fiscal_year_start)
        if due_on is not None:
            found.append(Deadline(entry.code, deadline.description, due_on, deadline.severity))
    return found
