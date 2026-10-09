"""
How a contract's payment terms become billing schedule lines.

One strategy per `trigger_type` (advance, date, milestone, on_completion, monthly). Adding a new
way of billing (usage-based, say) is adding a strategy here; everything else about schedules
stays the same. Amounts are before tax: the invoice drafted from a line adds the tax.

A line's `due_date` is when it becomes billable. A term's `due_offset_days` is not used here: it
is how long the customer has to pay, so it sets the drafted invoice's due date instead.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Callable, Optional
import uuid

from finance.errors import TaxConfigError
from finance.fiscal import safe_date
from finance.money import HUNDRED, ZERO, round_money

FULL_SHARE = HUNDRED


@dataclass(frozen=True)
class ContractFacts:
    start_date: date
    end_date: Optional[date]
    basis_amount: Decimal  # value before tax that percentages are taken of
    currency: str


@dataclass(frozen=True)
class TermFacts:
    id: Optional[uuid.UUID]
    seq: int
    trigger_type: str
    milestone_code: Optional[str] = None
    percent: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    due_offset_days: Optional[int] = None
    end_date: Optional[date] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class PlannedLine:
    seq: int
    milestone_type: str
    due_date: Optional[date]
    amount: Decimal
    percent: Optional[Decimal]
    description: str
    milestone_code: Optional[str] = None
    payment_term_id: Optional[uuid.UUID] = None


def _amount(contract: ContractFacts, term: TermFacts, share: Decimal = Decimal(1)) -> Decimal:
    if term.amount is not None:
        return round_money(term.amount * share, contract.currency)
    if term.percent is None:
        raise TaxConfigError(
            "PAYMENT_TERM_AMOUNT_MISSING", f"Payment term {term.seq} has neither an amount nor a percentage."
        )
    return round_money(contract.basis_amount * term.percent / HUNDRED * share, contract.currency)


def _single(contract: ContractFacts, term: TermFacts, due: Optional[date], label: str) -> list[PlannedLine]:
    return [PlannedLine(
        seq=term.seq, milestone_type=term.trigger_type, due_date=due, amount=_amount(contract, term),
        percent=term.percent, description=term.description or label, milestone_code=term.milestone_code,
        payment_term_id=term.id,
    )]


def plan_advance(contract: ContractFacts, term: TermFacts) -> list[PlannedLine]:
    return _single(contract, term, contract.start_date, "Advance")


def plan_date(contract: ContractFacts, term: TermFacts) -> list[PlannedLine]:
    return _single(contract, term, term.end_date or contract.start_date, "Instalment")


def plan_milestone(contract: ContractFacts, term: TermFacts) -> list[PlannedLine]:
    # Billable once the milestone is marked reached; it has no date of its own.
    return _single(contract, term, None, f"Milestone {term.milestone_code}" if term.milestone_code else "Milestone")


def plan_on_completion(contract: ContractFacts, term: TermFacts) -> list[PlannedLine]:
    return _single(contract, term, contract.end_date, "On completion")


def _months_between(start: date, end: date) -> list[date]:
    months, step = [], 0
    while True:
        total = start.month - 1 + step
        day = safe_date(start.year + total // 12, total % 12 + 1, start.day)
        if day > end:
            return months
        months.append(day)
        step += 1


def plan_monthly(contract: ContractFacts, term: TermFacts) -> list[PlannedLine]:
    end = term.end_date or contract.end_date
    if end is None:
        raise TaxConfigError("SCHEDULE_NEEDS_END_DATE", "Monthly billing needs the contract (or the term) to have an end date.")
    months = _months_between(contract.start_date, end)
    if not months:
        return []
    # A fixed amount is billed every month; a percentage of the contract is spread across the months.
    per_month = term.amount if term.amount is not None else None
    lines = []
    if per_month is not None:
        amounts = [round_money(per_month, contract.currency)] * len(months)
    else:
        total = _amount(contract, term)
        base = round_money(total / len(months), contract.currency)
        amounts = [base] * (len(months) - 1) + [total - base * (len(months) - 1)]
    for month_start, amount in zip(months, amounts):
        lines.append(PlannedLine(
            seq=term.seq, milestone_type="monthly", due_date=month_start, amount=amount,
            percent=None, description=term.description or f"Monthly — {month_start.strftime('%b %Y')}",
            milestone_code=term.milestone_code, payment_term_id=term.id,
        ))
    return lines


ScheduleStrategy = Callable[[ContractFacts, TermFacts], list[PlannedLine]]

STRATEGIES: dict[str, ScheduleStrategy] = {
    "advance": plan_advance,
    "date": plan_date,
    "milestone": plan_milestone,
    "on_completion": plan_on_completion,
    "monthly": plan_monthly,
}


def plan_schedule(contract: ContractFacts, terms: list[TermFacts], upfront: bool) -> list[PlannedLine]:
    """Every line the contract will be billed in, in order. Upfront (or no terms): one line for everything."""
    if upfront or not terms:
        whole = TermFacts(id=None, seq=1, trigger_type="advance", percent=FULL_SHARE, description="Full contract value")
        return [replace(line, seq=1) for line in plan_advance(contract, whole)]

    planned: list[PlannedLine] = []
    for term in sorted(terms, key=lambda item: item.seq):
        strategy = STRATEGIES.get(term.trigger_type)
        if strategy is None:
            raise TaxConfigError(
                "SCHEDULE_TRIGGER_UNKNOWN", f"Payment term {term.seq} uses '{term.trigger_type}', which has no billing strategy.",
                meta={"known": sorted(STRATEGIES)},
            )
        planned.extend(strategy(contract, term))

    # Percentages adding up to 100% must bill exactly the contract value: the last line takes the rounding.
    percent_lines = [index for index, line in enumerate(planned) if line.percent is not None]
    if percent_lines and sum((planned[index].percent or ZERO) for index in percent_lines) == FULL_SHARE:
        difference = contract.basis_amount - sum((planned[index].amount for index in percent_lines), ZERO)
        last = percent_lines[-1]
        planned[last] = replace(planned[last], amount=planned[last].amount + difference)
    return [replace(line, seq=position) for position, line in enumerate(planned, start=1)]
