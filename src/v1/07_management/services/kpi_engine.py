"""
The KPI calculator: turns the measurement ledger into `kpi_results`, the derived cache the
scorecard reads (plan §4.2).

For one KPI, period and scope:

1. Measurements in the period that match the scope, net of reversals (a reversal and the row it
   reverses both drop out).
2. Aggregated per the KPI's `aggregation`: sum, avg, min, max; `last` is semi-additive (the latest
   reading of each dimension combination, then summed across them); `count_distinct` counts distinct
   values of `formula.distinct_on`; `ratio` is sum(numerator KPI) / sum(denominator KPI) x scale,
   a ratio of sums and never an average of ratios.
3. Refused rather than guessed (422 KPI_NOT_AGGREGABLE): a period shorter than the KPI's frequency
   (a monthly figure can't be split into weeks), or two `last` readings for the same day and dimensions.
4. The governing target: the approved target for that period and exact scope with the highest
   revision.
5. Achievement honours the direction: actual/target when higher is better, target/actual when lower
   is better; capped at 999.99%. A zero or negative target has no achievement ("not_comparable").
6. RAG from the KPI's thresholds (the scope's unit first, then the KPI's default, else 90/70).
7. Trend against the same scope's result in the previous period of the same type.
8. `inputs_hash` over everything that went in, so recalculating unchanged inputs writes nothing and a
   stale result is detectable.
9. A closed period is frozen: no recalculation, except a restatement, which bumps `calc_version`.

Scope is stored in `kpi_results.scope_key` as "global" or "u<hex>v<hex>p<hex>" (unit, vertical,
user; each part only when set), which fits the column's 100 characters and stays searchable.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import KPIFormulaError, KPINotAggregableError, PeriodClosedError
from models.performance import KPIDefinition, KPIMeasurement, KPIResult, KPITarget, KPIThreshold
from models.planning import PlanningPeriod
from schemas.kpi import KpiScope

# Bump when the calculation itself changes: every result's hash changes with it.
CALC_LOGIC_VERSION = 1

FREQUENCY_MIN_DAYS = {"daily": 1, "weekly": 7, "monthly": 28, "quarterly": 89, "yearly": 365}
DIMENSIONS = ("unit_id", "vertical_id", "user_id", "client_id", "offering_id")
DEFAULT_GREEN, DEFAULT_AMBER = Decimal("90"), Decimal("70")
ACHIEVEMENT_CAP = Decimal("999.99")
VARIANCE_PCT_CAP = Decimal("9999.99")
RAG_STATUSES = frozenset({"green", "amber", "red"})
CLOSED = "closed"

_SCOPE_PARTS = (("u", "unit_id"), ("v", "vertical_id"), ("p", "user_id"))


# --- Scope keys ---------------------------------------------------------------


def scope_key(scope: KpiScope) -> str:
    parts = [f"{letter}{getattr(scope, name).hex}" for letter, name in _SCOPE_PARTS if getattr(scope, name)]
    return "".join(parts) or "global"


def parse_scope_key(key: str) -> KpiScope:
    if key == "global":
        return KpiScope()
    values: dict[str, uuid.UUID] = {}
    position = 0
    while position + 33 <= len(key):
        letter, hex_value = key[position], key[position + 1 : position + 33]
        name = dict(_SCOPE_PARTS).get(letter)
        if name is None:
            break
        try:
            values[name] = uuid.UUID(hex=hex_value)
        except ValueError:
            break
        position += 33
    return KpiScope(**values)


def user_scope_fragment(user_id: uuid.UUID) -> str:
    """What a scope key scoped to `user_id` contains (for "own records only" filters)."""
    return f"p{user_id.hex}"


# --- Pure calculation ---------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    id: uuid.UUID
    measured_on: date
    value: Decimal
    dims: tuple[Optional[uuid.UUID], ...]


@dataclass(frozen=True)
class Computed:
    actual: Optional[Decimal]
    target: Optional[KPITarget]
    achievement_pct: Optional[Decimal]
    variance_abs: Optional[Decimal]
    variance_pct: Optional[Decimal]
    status: str


def as_decimal(value: object) -> Decimal:
    """A stored number as a Decimal: via its text, so a float like 0.1 stays 0.1."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _fixed(value: object, places: int = 4) -> str:
    """The same number always hashes the same, whether it came from the database (7.0000) or a request (7)."""
    return f"{as_decimal(value):.{places}f}"


def _cap(value: Decimal, cap: Decimal) -> Decimal:
    return max(-cap, min(cap, value)).quantize(Decimal("0.01"))


def aggregate(kpi: KPIDefinition, readings: list[Reading]) -> Optional[Decimal]:
    """The KPI's actual over `readings`; None when there are none."""
    if not readings:
        return None
    values = [reading.value for reading in readings]
    if kpi.aggregation == "sum":
        return sum(values, Decimal(0))
    if kpi.aggregation == "avg":
        return sum(values, Decimal(0)) / len(values)
    if kpi.aggregation == "min":
        return min(values)
    if kpi.aggregation == "max":
        return max(values)
    if kpi.aggregation == "last":
        return _semi_additive_last(kpi, readings)
    if kpi.aggregation == "count_distinct":
        distinct_on = (kpi.formula or {}).get("distinct_on")
        if distinct_on not in DIMENSIONS:
            raise KPIFormulaError(kpi.code, f"count_distinct needs formula.distinct_on, one of {', '.join(DIMENSIONS)}")
        index = DIMENSIONS.index(distinct_on)
        return Decimal(len({reading.dims[index] for reading in readings if reading.dims[index] is not None}))
    raise KPIFormulaError(kpi.code, f"unknown aggregation '{kpi.aggregation}'")


def _semi_additive_last(kpi: KPIDefinition, readings: list[Reading]) -> Decimal:
    """A balance or headcount: each dimension combination's latest reading, summed across combinations."""
    latest: dict[tuple, Reading] = {}
    for reading in readings:
        current = latest.get(reading.dims)
        if current is not None and current.measured_on == reading.measured_on:
            raise KPINotAggregableError(
                kpi.code, f"two readings on {reading.measured_on} for the same dimensions; reverse one of them"
            )
        if current is None or reading.measured_on > current.measured_on:
            latest[reading.dims] = reading
    return sum((reading.value for reading in latest.values()), Decimal(0))


def achievement(direction: str, actual: Decimal, target: Decimal) -> Optional[Decimal]:
    if target <= 0:
        return None
    if direction == "lower_is_better":
        if actual < 0:
            return None
        return ACHIEVEMENT_CAP if actual == 0 else _cap(target / actual * 100, ACHIEVEMENT_CAP)
    return _cap(actual / target * 100, ACHIEVEMENT_CAP)


def rag(achievement_pct: Decimal, green_from: Decimal, amber_from: Decimal) -> str:
    if achievement_pct >= green_from:
        return "green"
    if achievement_pct >= amber_from:
        return "amber"
    return "red"


def compute(
    direction: str, actual: Optional[Decimal], target: Optional[KPITarget], green_from: Decimal, amber_from: Decimal
) -> Computed:
    if actual is None:
        return Computed(None, target, None, None, None, "no_data")
    if target is None:
        return Computed(actual, None, None, None, None, "no_target")
    target_value = as_decimal(target.target_value)
    variance_abs = actual - target_value
    achieved = achievement(direction, actual, target_value)
    if achieved is None:
        return Computed(actual, target, None, variance_abs, None, "not_comparable")
    variance_pct = _cap(variance_abs / abs(target_value) * 100, VARIANCE_PCT_CAP)
    return Computed(actual, target, achieved, variance_abs, variance_pct, rag(achieved, green_from, amber_from))


def trend(direction: str, current: Computed, previous: Optional[KPIResult]) -> str:
    if previous is None or previous.status == "no_data" or current.actual is None:
        return "no_history"
    if current.achievement_pct is not None and previous.status in RAG_STATUSES:
        delta = current.achievement_pct - as_decimal(previous.achievement_pct)
    else:
        delta = current.actual - as_decimal(previous.actual_value)
        if direction == "lower_is_better":
            delta = -delta
    if delta > 0:
        return "improving"
    if delta < 0:
        return "declining"
    return "stable"


# --- Reading the ledger -------------------------------------------------------


def _matches(measurement: KPIMeasurement, scope: KpiScope) -> bool:
    return all(
        getattr(scope, name) is None or getattr(measurement, name) == getattr(scope, name)
        for name in ("unit_id", "vertical_id", "user_id")
    )


async def net_readings(
    session: AsyncSession, kpi_id: uuid.UUID, start: date, end: date, scope: KpiScope
) -> list[Reading]:
    """The KPI's measurements in [start, end] matching `scope`, net of reversals."""
    rows = (
        await session.execute(
            select(KPIMeasurement).where(
                KPIMeasurement.kpi_definition_id == kpi_id,
                KPIMeasurement.measured_on >= start,
                KPIMeasurement.measured_on <= end,
            )
        )
    ).scalars().all()
    reversed_ids = {row.reverses_id for row in rows if row.reverses_id is not None}
    # A reversal may sit in a later period than what it reverses; look those up too.
    late_reversals = (
        await session.execute(
            select(KPIMeasurement.reverses_id).where(
                KPIMeasurement.reverses_id.in_([row.id for row in rows]),
            )
        )
    ).scalars().all() if rows else []
    reversed_ids.update(late_reversals)
    return [
        Reading(row.id, row.measured_on, as_decimal(row.value), tuple(getattr(row, name) for name in DIMENSIONS))
        for row in rows
        if row.reverses_id is None and row.id not in reversed_ids and _matches(row, scope)
    ]


async def _kpi_by_code(session: AsyncSession, org_id: uuid.UUID, code: object, owner: KPIDefinition, part: str) -> KPIDefinition:
    if not isinstance(code, str) or code == owner.code:
        raise KPIFormulaError(owner.code, f"ratio needs formula.{part}, the code of another KPI")
    kpi = (
        await session.execute(select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == code))
    ).scalars().first()
    if kpi is None:
        raise KPIFormulaError(owner.code, f"formula.{part} names KPI '{code}', which doesn't exist")
    return kpi


async def actual_for(
    session: AsyncSession, kpi: KPIDefinition, period: PlanningPeriod, scope: KpiScope
) -> tuple[Optional[Decimal], list[Reading]]:
    """The actual and the readings it came from."""
    if kpi.aggregation != "ratio":
        readings = await net_readings(session, kpi.id, period.start_date, period.end_date, scope)
        return aggregate(kpi, readings), readings
    formula = kpi.formula or {}
    numerator = await _kpi_by_code(session, kpi.organization_id, formula.get("numerator"), kpi, "numerator")
    denominator = await _kpi_by_code(session, kpi.organization_id, formula.get("denominator"), kpi, "denominator")
    try:
        scale = Decimal(str(formula.get("scale", 1)))
    except InvalidOperation as exc:
        raise KPIFormulaError(kpi.code, "formula.scale must be a number") from exc
    top = await net_readings(session, numerator.id, period.start_date, period.end_date, scope)
    bottom = await net_readings(session, denominator.id, period.start_date, period.end_date, scope)
    denominator_sum = sum((reading.value for reading in bottom), Decimal(0))
    if (not top and not bottom) or denominator_sum == 0:
        return None, top + bottom
    return sum((reading.value for reading in top), Decimal(0)) / denominator_sum * scale, top + bottom


async def governing_target(
    session: AsyncSession, kpi_id: uuid.UUID, period_id: uuid.UUID, scope: KpiScope
) -> Optional[KPITarget]:
    query = select(KPITarget).where(
        KPITarget.kpi_definition_id == kpi_id,
        KPITarget.period_id == period_id,
        KPITarget.status == "approved",
    )
    for name, column in (("unit_id", KPITarget.scope_unit_id), ("vertical_id", KPITarget.scope_vertical_id), ("user_id", KPITarget.scope_user_id)):
        value = getattr(scope, name)
        query = query.where(column == value if value is not None else column.is_(None))
    query = query.order_by(KPITarget.revision_no.desc()).limit(1)
    return (await session.execute(query)).scalars().first()


async def thresholds_for(session: AsyncSession, kpi_id: uuid.UUID, unit_id: Optional[uuid.UUID]) -> tuple[Decimal, Decimal]:
    rows = (await session.execute(select(KPIThreshold).where(KPIThreshold.kpi_definition_id == kpi_id))).scalars().all()
    chosen = next((row for row in rows if unit_id is not None and row.scope_unit_id == unit_id), None)
    chosen = chosen or next((row for row in rows if row.scope_unit_id is None), None)
    if chosen is None:
        return DEFAULT_GREEN, DEFAULT_AMBER
    return as_decimal(chosen.green_from_pct), as_decimal(chosen.amber_from_pct)


async def previous_result(
    session: AsyncSession, kpi_id: uuid.UUID, period: PlanningPeriod, key: str
) -> Optional[KPIResult]:
    previous_period = (
        await session.execute(
            select(PlanningPeriod)
            .where(
                PlanningPeriod.organization_id == period.organization_id,
                PlanningPeriod.period_type == period.period_type,
                PlanningPeriod.end_date < period.start_date,
            )
            .order_by(PlanningPeriod.end_date.desc())
            .limit(1)
        )
    ).scalars().first()
    if previous_period is None:
        return None
    return await find_result(session, kpi_id, previous_period.id, key)


async def find_result(session: AsyncSession, kpi_id: uuid.UUID, period_id: uuid.UUID, key: str) -> Optional[KPIResult]:
    return (
        await session.execute(
            select(KPIResult).where(
                KPIResult.kpi_definition_id == kpi_id, KPIResult.period_id == period_id, KPIResult.scope_key == key
            )
        )
    ).scalars().first()


def check_grain(kpi: KPIDefinition, period: PlanningPeriod) -> None:
    days = (period.end_date - period.start_date).days + 1
    minimum = FREQUENCY_MIN_DAYS.get(kpi.frequency, 1)
    if days < minimum:
        raise KPINotAggregableError(
            kpi.code, f"it is measured {kpi.frequency}, and '{period.name}' is only {days} day(s) long"
        )


def _inputs_hash(
    kpi: KPIDefinition,
    readings: list[Reading],
    target: Optional[KPITarget],
    thresholds: tuple[Decimal, Decimal],
    previous: Optional[KPIResult],
    key: str,
) -> str:
    payload = {
        "logic": CALC_LOGIC_VERSION,
        "kpi": [str(kpi.id), kpi.version_no, kpi.aggregation, kpi.direction, kpi.formula],
        "scope": key,
        "readings": sorted([str(r.id), _fixed(r.value), r.measured_on.isoformat()] for r in readings),
        "target": [str(target.id), _fixed(target.target_value)] if target else None,
        "thresholds": [_fixed(value, 2) for value in thresholds],
        "previous": [previous.status, _fixed(previous.actual_value), _fixed(previous.achievement_pct, 2)] if previous else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Calculation:
    result: KPIResult
    changed: bool
    readings: list[Reading]


async def calculate(
    session: AsyncSession,
    kpi: KPIDefinition,
    period: PlanningPeriod,
    scope: KpiScope,
    *,
    restatement: bool = False,
) -> Calculation:
    """Recalculate one result. Raises when the period is closed (unless restating) or the number would be wrong."""
    if period.status == CLOSED and not restatement:
        raise PeriodClosedError(period.name)
    check_grain(kpi, period)
    key = scope_key(scope)
    actual, readings = await actual_for(session, kpi, period, scope)
    target = await governing_target(session, kpi.id, period.id, scope)
    thresholds = await thresholds_for(session, kpi.id, scope.unit_id)
    previous = await previous_result(session, kpi.id, period, key)
    inputs_hash = _inputs_hash(kpi, readings, target, thresholds, previous, key)

    existing = await find_result(session, kpi.id, period.id, key)
    if existing is not None and existing.inputs_hash == inputs_hash and not restatement:
        return Calculation(existing, False, readings)

    computed = compute(kpi.direction, actual, target, *thresholds)
    result = existing or KPIResult(
        id=uuid.uuid4(), kpi_definition_id=kpi.id, organization_id=kpi.organization_id, period_id=period.id,
        scope_key=key, calc_version=1,
    )
    result.target_id = target.id if target else None
    result.actual_value = computed.actual if computed.actual is not None else 0
    result.target_value = as_decimal(target.target_value) if target else 0
    result.achievement_pct = computed.achievement_pct if computed.achievement_pct is not None else 0
    result.variance_abs = computed.variance_abs if computed.variance_abs is not None else 0
    result.variance_pct = computed.variance_pct if computed.variance_pct is not None else 0
    result.status = computed.status
    result.trend = trend(kpi.direction, computed, previous)
    result.inputs_hash = inputs_hash
    result.calculated_at = datetime.now(timezone.utc)
    if restatement and existing is not None:
        result.calc_version = existing.calc_version + 1
    if existing is None:
        session.add(result)
    await session.flush()
    return Calculation(result, True, readings)
