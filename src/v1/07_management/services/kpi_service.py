"""
Performance: KPI definitions with their sources and thresholds, the measurement ledger, targets
(approved through control), the results the engine derives, period close and restatement, the
scorecard, and corrective actions.

- Measurements are append-only. A correction is a reversal (and optionally a replacement); a
  measurement dated inside a closed period is refused, except through a restatement.
- Recording a measurement recalculates the open periods it falls in, so results stay current; an
  explicit calculation does the same for a whole period and reports refusals instead of skipping them.
- Closing a period recalculates it one last time, freezes each result into a snapshot and refuses
  further change. A restatement is the one way to change a closed period: it records the corrections,
  recalculates with a new `calc_version` and freezes a new snapshot beside the old one.
- "Own records only" on results and targets shows those scoped to the caller and those of goals they own.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    CorrectiveActionNotFoundError,
    DuplicateKPICodeError,
    DuplicateOpenTargetError,
    InvalidStateTransitionError,
    KPIDefinitionNotFoundError,
    KPIFormulaError,
    KPINotAggregableError,
    KPINotFoundError,
    KPINotManualError,
    KPIResultNotFoundError,
    KPISourceNotFoundError,
    KPITargetNotFoundError,
    KPIThresholdNotFoundError,
    MeasurementNotFoundError,
    PeriodClosedError,
    PermissionDeniedError,
    UnknownReferenceError,
    ValidationFailedError,
)
from models.performance import (
    CorrectiveAction,
    GoalKPI,
    KPIDefinition,
    KPIMeasurement,
    KPIPeriodSnapshot,
    KPIResult,
    KPISource,
    KPITarget,
    KPIThreshold,
)
from models.planning import PlanningPeriod, StrategicGoal
from schemas.common import PageResponse
from schemas.kpi import (
    CalculationResponse,
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    CorrectiveActionUpdate,
    KpiDefinitionCreate,
    KpiDefinitionResponse,
    KpiDefinitionUpdate,
    KpiRef,
    KpiRefWithDirection,
    KpiResultResponse,
    KpiScope,
    KpiSourceCreate,
    KpiSourceItem,
    KpiStatusRef,
    KpiTargetCreate,
    KpiTargetResponse,
    KpiTargetRevisionCreate,
    KpiThresholdCreate,
    KpiThresholdResponse,
    ManualMeasurementCreate,
    MeasurementDimensions,
    MeasurementResponse,
    MeasurementReversal,
    MeasurementValue,
    MeasurementWriteResponse,
    RestatementCreate,
    ScorecardCheckIn,
    ScorecardGoal,
    ScorecardKpi,
    ScorecardResponse,
    SnapshotResponse,
)
from schemas.planning import PeriodCloseResponse, PeriodRef
from services import kpi_engine
from services.common import Directory, check_if_match, get_in_org
from services.control_client import ControlClient
from services.identity_client import Actor
from services.pagination import paginate_by_id
from services.planning_service import (
    confidence_band,
    get_fiscal_year,
    get_period,
    latest_check_in,
    period_reference,
    period_response,
)

CLOSED = "closed"
OPEN_TARGET_STATUSES = ("draft", "pending_approval")
TARGET_SUBJECT_TYPE = "management.kpi_target"
TARGET_REQUEST_TYPE = "kpi_target"
# What control's final statuses mean for a target waiting on it.
_TARGET_AFTER_DECISION = {
    "approved": "approved",
    "rejected": "rejected",
    "revision_required": "draft",
    "cancelled": "draft",
    "expired": "draft",
}
# Fields whose change alters how the number is produced: they bump the definition's version.
_LOGIC_FIELDS = {"unit", "direction", "aggregation", "formula", "frequency"}


# --- Lookups ------------------------------------------------------------------


async def get_kpi_by_code(session: AsyncSession, org_id: uuid.UUID, code: str) -> KPIDefinition:
    kpi = (
        await session.execute(select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == code))
    ).scalars().first()
    if kpi is None:
        raise KPIDefinitionNotFoundError(code)
    return kpi


async def kpi_reference(session: AsyncSession, org_id: uuid.UUID, code: str) -> KPIDefinition:
    """A KPI named in a request body: unknown codes are a 422."""
    kpi = (
        await session.execute(select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == code))
    ).scalars().first()
    if kpi is None:
        raise KPINotFoundError(code)
    return kpi


async def _goals_owned_by(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.execute(
                select(StrategicGoal.id).where(StrategicGoal.organization_id == org_id, StrategicGoal.owner_user_id == user_id)
            )
        ).scalars()
    )


# --- Definitions --------------------------------------------------------------


def _source_item(source: KPISource) -> KpiSourceItem:
    return KpiSourceItem(
        id=source.id, source_type=source.source_type, event_type=source.event_type, value_path=source.value_path,
        filter=source.filter, dimensions=source.dimension_map, enabled=source.enabled,
    )


def _threshold_item(threshold: KPIThreshold) -> KpiThresholdResponse:
    return KpiThresholdResponse(
        id=threshold.id, scope_unit_id=threshold.scope_unit_id,
        green_from_pct=float(threshold.green_from_pct), amber_from_pct=float(threshold.amber_from_pct),
    )


async def _definition_response(session: AsyncSession, kpi: KPIDefinition, directory: Directory) -> KpiDefinitionResponse:
    sources = (await session.execute(select(KPISource).where(KPISource.kpi_definition_id == kpi.id))).scalars().all()
    thresholds = (await session.execute(select(KPIThreshold).where(KPIThreshold.kpi_definition_id == kpi.id))).scalars().all()
    return KpiDefinitionResponse(
        id=kpi.id, code=kpi.code, name=kpi.name, unit=kpi.unit, direction=kpi.direction, aggregation=kpi.aggregation,
        formula=kpi.formula, frequency=kpi.frequency, owner=await directory.user(kpi.owner_user_id),
        version_no=kpi.version_no, sources=[_source_item(s) for s in sources],
        thresholds=[_threshold_item(t) for t in thresholds], status=kpi.status,
    )


async def _check_formula(session: AsyncSession, org_id: uuid.UUID, code: str, aggregation: str, formula: Optional[dict]) -> None:
    formula = formula or {}
    if aggregation == "count_distinct" and formula.get("distinct_on") not in kpi_engine.DIMENSIONS:
        raise KPIFormulaError(code, f"count_distinct needs formula.distinct_on, one of {', '.join(kpi_engine.DIMENSIONS)}")
    if aggregation != "ratio":
        return
    for part in ("numerator", "denominator"):
        other = formula.get(part)
        if not isinstance(other, str) or other == code:
            raise KPIFormulaError(code, f"ratio needs formula.{part}, the code of another KPI")
        found = (
            await session.execute(
                select(KPIDefinition.aggregation).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == other)
            )
        ).scalar_one_or_none()
        if found is None:
            raise KPIFormulaError(code, f"formula.{part} names KPI '{other}', which doesn't exist")
        if found != "sum":
            raise KPIFormulaError(code, f"formula.{part} must be a summed KPI; '{other}' is {found}")


async def list_definitions(
    session: AsyncSession, org_id: uuid.UUID, directory: Directory, status: Optional[str], limit: int, cursor: Optional[str]
) -> PageResponse[KpiDefinitionResponse]:
    query = select(KPIDefinition).where(KPIDefinition.organization_id == org_id)
    if status is not None:
        query = query.where(KPIDefinition.status == status)
    rows, page = await paginate_by_id(session, query, KPIDefinition, limit, cursor)
    return PageResponse(data=[await _definition_response(session, row, directory) for row in rows], page=page)


async def create_definition(
    session: AsyncSession, org_id: uuid.UUID, data: KpiDefinitionCreate, directory: Directory
) -> KpiDefinitionResponse:
    exists = await session.execute(
        select(KPIDefinition.id).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == data.code)
    )
    if exists.first():
        raise DuplicateKPICodeError(data.code)
    await _check_formula(session, org_id, data.code, data.aggregation, data.formula)
    kpi = KPIDefinition(organization_id=org_id, version_no=1, status="active", **data.model_dump())
    session.add(kpi)
    await session.flush()
    return await _definition_response(session, kpi, directory)


async def get_definition(session: AsyncSession, org_id: uuid.UUID, code: str, directory: Directory) -> KpiDefinitionResponse:
    return await _definition_response(session, await get_kpi_by_code(session, org_id, code), directory)


async def update_definition(
    session: AsyncSession, org_id: uuid.UUID, code: str, data: KpiDefinitionUpdate, directory: Directory
) -> KpiDefinitionResponse:
    kpi = await get_kpi_by_code(session, org_id, code)
    changes = data.model_dump(exclude_unset=True)
    if "aggregation" in changes or "formula" in changes:
        await _check_formula(session, org_id, kpi.code, changes.get("aggregation", kpi.aggregation), changes.get("formula", kpi.formula))
    logic_changed = any(changes.get(name, getattr(kpi, name)) != getattr(kpi, name) for name in _LOGIC_FIELDS & changes.keys())
    for field_name, value in changes.items():
        setattr(kpi, field_name, value)
    if logic_changed:
        kpi.version_no += 1
    await session.flush()
    return await _definition_response(session, kpi, directory)


async def add_source(
    session: AsyncSession, org_id: uuid.UUID, code: str, data: KpiSourceCreate
) -> KpiSourceItem:
    kpi = await get_kpi_by_code(session, org_id, code)
    values = data.model_dump()
    source = KPISource(kpi_definition_id=kpi.id, dimension_map=values.pop("dimensions"), **values)
    session.add(source)
    await session.flush()
    return _source_item(source)


async def remove_source(session: AsyncSession, org_id: uuid.UUID, code: str, source_id: uuid.UUID) -> None:
    kpi = await get_kpi_by_code(session, org_id, code)
    source = await session.get(KPISource, source_id)
    if source is None or source.kpi_definition_id != kpi.id:
        raise KPISourceNotFoundError(str(source_id))
    await session.delete(source)
    await session.flush()


async def add_threshold(
    session: AsyncSession, org_id: uuid.UUID, code: str, data: KpiThresholdCreate
) -> KpiThresholdResponse:
    kpi = await get_kpi_by_code(session, org_id, code)
    existing = (
        await session.execute(select(KPIThreshold).where(KPIThreshold.kpi_definition_id == kpi.id))
    ).scalars().all()
    if any(row.scope_unit_id == data.scope_unit_id for row in existing):
        raise ValidationFailedError("scope_unit_id", "this KPI already has thresholds for that scope; delete them first")
    threshold = KPIThreshold(kpi_definition_id=kpi.id, **data.model_dump())
    session.add(threshold)
    await session.flush()
    return _threshold_item(threshold)


async def remove_threshold(session: AsyncSession, org_id: uuid.UUID, code: str, threshold_id: uuid.UUID) -> None:
    kpi = await get_kpi_by_code(session, org_id, code)
    threshold = await session.get(KPIThreshold, threshold_id)
    if threshold is None or threshold.kpi_definition_id != kpi.id:
        raise KPIThresholdNotFoundError(str(threshold_id))
    await session.delete(threshold)
    await session.flush()


# --- Results: responses -------------------------------------------------------


class _Refs:
    """KPIs and periods for one response list, each loaded once."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._kpis: dict[uuid.UUID, Optional[KPIDefinition]] = {}
        self._periods: dict[uuid.UUID, Optional[PlanningPeriod]] = {}

    async def kpi(self, kpi_id: uuid.UUID) -> KPIDefinition:
        if kpi_id not in self._kpis:
            self._kpis[kpi_id] = await self.session.get(KPIDefinition, kpi_id)
        return self._kpis[kpi_id]

    async def period(self, period_id: uuid.UUID) -> PlanningPeriod:
        if period_id not in self._periods:
            self._periods[period_id] = await self.session.get(PlanningPeriod, period_id)
        return self._periods[period_id]


async def result_response(result: KPIResult, refs: _Refs) -> KpiResultResponse:
    kpi = await refs.kpi(result.kpi_definition_id)
    period = await refs.period(result.period_id)
    rated = result.status in kpi_engine.RAG_STATUSES
    has_actual = result.status != "no_data"
    has_target = result.target_id is not None
    return KpiResultResponse(
        id=result.id,
        kpi=KpiRefWithDirection(code=kpi.code, name=kpi.name, unit=kpi.unit, direction=kpi.direction),
        period=PeriodRef(id=period.id, name=period.name),
        scope=kpi_engine.parse_scope_key(result.scope_key),
        target_id=result.target_id,
        actual_value=float(result.actual_value) if has_actual else None,
        target_value=float(result.target_value) if has_target else None,
        achievement_pct=float(result.achievement_pct) if rated else None,
        variance_abs=float(result.variance_abs) if has_actual and has_target else None,
        variance_pct=float(result.variance_pct) if rated else None,
        status=result.status,
        trend=result.trend,
        calc_version=result.calc_version,
        inputs_hash=result.inputs_hash,
        calculated_at=result.calculated_at,
        frozen=period.status == CLOSED,
    )


# --- Measurements -------------------------------------------------------------


def _measurement_response(measurement: KPIMeasurement, kpi_code: str, reversed_: bool) -> MeasurementResponse:
    return MeasurementResponse(
        id=measurement.id,
        kpi_code=kpi_code,
        measured_on=measurement.measured_on,
        value=float(measurement.value),
        dimensions=MeasurementDimensions(**{name: getattr(measurement, name) for name in kpi_engine.DIMENSIONS}),
        source_type=measurement.source_type,
        reverses_id=measurement.reverses_id,
        reversed=reversed_,
        entered_by=measurement.entered_by,
    )


async def _check_day_open(session: AsyncSession, org_id: uuid.UUID, day: date) -> None:
    closed = (
        await session.execute(
            select(PlanningPeriod).where(
                PlanningPeriod.organization_id == org_id,
                PlanningPeriod.status == CLOSED,
                PlanningPeriod.start_date <= day,
                PlanningPeriod.end_date >= day,
            ).limit(1)
        )
    ).scalars().first()
    if closed is not None:
        raise PeriodClosedError(closed.name)


def _new_measurement(kpi: KPIDefinition, value: MeasurementValue, user_id: uuid.UUID, **extra) -> KPIMeasurement:
    return KPIMeasurement(
        id=uuid.uuid4(),
        kpi_definition_id=kpi.id,
        organization_id=kpi.organization_id,
        measured_on=value.measured_on,
        value=value.value,
        source_type="manual",
        entered_by=user_id,
        **value.dimensions.model_dump(),
        **extra,
    )


async def _check_manual(session: AsyncSession, kpi: KPIDefinition) -> None:
    if kpi.aggregation == "ratio":
        raise KPINotManualError()
    fed = await session.execute(
        select(KPISource.id).where(
            KPISource.kpi_definition_id == kpi.id, KPISource.source_type != "manual", KPISource.enabled.is_(True)
        ).limit(1)
    )
    if fed.first():
        raise KPINotManualError()


async def _dependents(session: AsyncSession, kpi: KPIDefinition) -> list[KPIDefinition]:
    """Ratio KPIs computed from this one."""
    ratios = (
        await session.execute(
            select(KPIDefinition).where(KPIDefinition.organization_id == kpi.organization_id, KPIDefinition.aggregation == "ratio")
        )
    ).scalars().all()
    return [ratio for ratio in ratios if kpi.code in {(ratio.formula or {}).get("numerator"), (ratio.formula or {}).get("denominator")}]


async def _scopes_to_refresh(session: AsyncSession, kpi_id: uuid.UUID, period_id: uuid.UUID) -> set[str]:
    keys = set(
        (await session.execute(select(KPIResult.scope_key).where(KPIResult.kpi_definition_id == kpi_id, KPIResult.period_id == period_id))).scalars()
    )
    targets = (
        await session.execute(
            select(KPITarget).where(KPITarget.kpi_definition_id == kpi_id, KPITarget.period_id == period_id, KPITarget.status == "approved")
        )
    ).scalars().all()
    keys.update(kpi_engine.scope_key(_target_scope(target)) for target in targets)
    keys.add("global")
    return keys


async def _refresh_quietly(session: AsyncSession, kpi: KPIDefinition, period: PlanningPeriod, keys: Iterable[str]) -> int:
    """Recalculate what can be; a period this KPI can't be calculated for is simply left alone."""
    changed = 0
    for key in keys:
        try:
            calculation = await kpi_engine.calculate(session, kpi, period, kpi_engine.parse_scope_key(key))
        except (KPINotAggregableError, KPIFormulaError, PeriodClosedError):
            continue
        changed += calculation.changed
    return changed


async def _refresh_after_measurement(session: AsyncSession, kpi: KPIDefinition, day: date) -> int:
    periods = (
        await session.execute(
            select(PlanningPeriod).where(
                PlanningPeriod.organization_id == kpi.organization_id,
                PlanningPeriod.status != CLOSED,
                PlanningPeriod.start_date <= day,
                PlanningPeriod.end_date >= day,
            )
        )
    ).scalars().all()
    changed = 0
    for affected in [kpi, *await _dependents(session, kpi)]:
        for period in periods:
            changed += await _refresh_quietly(session, affected, period, await _scopes_to_refresh(session, affected.id, period.id))
    return changed


async def record_measurement(
    session: AsyncSession, actor: Actor, data: ManualMeasurementCreate
) -> MeasurementWriteResponse:
    kpi = await kpi_reference(session, actor.organization_id, data.kpi_code)
    await _check_manual(session, kpi)
    await _check_day_open(session, actor.organization_id, data.measured_on)
    measurement = _new_measurement(kpi, data, actor.user_id)
    session.add(measurement)
    await session.flush()
    recalculated = await _refresh_after_measurement(session, kpi, data.measured_on)
    return MeasurementWriteResponse(
        measurement=_measurement_response(measurement, kpi.code, False), recalculated_results=recalculated
    )


async def _reversible(session: AsyncSession, org_id: uuid.UUID, measurement_id: uuid.UUID) -> KPIMeasurement:
    original = await get_in_org(session, KPIMeasurement, measurement_id, org_id, MeasurementNotFoundError(str(measurement_id)))
    if original.reverses_id is not None:
        raise ValidationFailedError("measurement_id", "a reversal can't itself be reversed")
    already = await session.execute(select(KPIMeasurement.id).where(KPIMeasurement.reverses_id == original.id).limit(1))
    if already.first():
        raise InvalidStateTransitionError("measurement", "reversed", "reverse")
    return original


def _reversal_of(original: KPIMeasurement, user_id: uuid.UUID) -> KPIMeasurement:
    return KPIMeasurement(
        id=uuid.uuid4(), kpi_definition_id=original.kpi_definition_id, organization_id=original.organization_id,
        reverses_id=original.id, measured_on=original.measured_on, value=original.value,
        **{name: getattr(original, name) for name in kpi_engine.DIMENSIONS},
        source_type="reversal", entered_by=user_id,
    )


async def reverse_measurement(
    session: AsyncSession, actor: Actor, measurement_id: uuid.UUID, data: MeasurementReversal
) -> MeasurementWriteResponse:
    """Reverse a measurement (only whoever entered it, or someone who manages KPIs), optionally replacing it."""
    original = await _reversible(session, actor.organization_id, measurement_id)
    if original.entered_by != actor.user_id and not actor.has(permissions.KPI_MANAGE):
        raise PermissionDeniedError(permissions.KPI_MANAGE, "Only whoever entered a measurement reverses it.")
    await _check_day_open(session, actor.organization_id, original.measured_on)
    kpi = await session.get(KPIDefinition, original.kpi_definition_id)
    reversal = _reversal_of(original, actor.user_id)
    session.add(reversal)
    replacement = None
    if data.replacement_value is not None:
        replacement = KPIMeasurement(
            id=uuid.uuid4(), kpi_definition_id=kpi.id, organization_id=kpi.organization_id,
            measured_on=original.measured_on, value=data.replacement_value,
            **{name: getattr(original, name) for name in kpi_engine.DIMENSIONS},
            source_type="manual", entered_by=actor.user_id,
        )
        session.add(replacement)
    await session.flush()
    recalculated = await _refresh_after_measurement(session, kpi, original.measured_on)
    return MeasurementWriteResponse(
        measurement=_measurement_response(replacement or original, kpi.code, replacement is None),
        reversal=_measurement_response(reversal, kpi.code, False),
        recalculated_results=recalculated,
    )


async def list_measurements(
    session: AsyncSession,
    actor: Actor,
    kpi_code: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[MeasurementResponse]:
    query = select(KPIMeasurement).where(KPIMeasurement.organization_id == actor.organization_id)
    if kpi_code is not None:
        kpi = await get_kpi_by_code(session, actor.organization_id, kpi_code)
        query = query.where(KPIMeasurement.kpi_definition_id == kpi.id)
    if from_date is not None:
        query = query.where(KPIMeasurement.measured_on >= from_date)
    if to_date is not None:
        query = query.where(KPIMeasurement.measured_on <= to_date)
    if actor.only_own(permissions.RESULT_READ):
        query = query.where(KPIMeasurement.user_id == actor.user_id)
    rows, page = await paginate_by_id(session, query, KPIMeasurement, limit, cursor)
    reversed_ids = set(
        (await session.execute(select(KPIMeasurement.reverses_id).where(KPIMeasurement.reverses_id.in_([r.id for r in rows])))).scalars()
    ) if rows else set()
    refs = _Refs(session)
    data = [_measurement_response(row, (await refs.kpi(row.kpi_definition_id)).code, row.id in reversed_ids) for row in rows]
    return PageResponse(data=data, page=page)


# --- Targets ------------------------------------------------------------------


def _target_scope(target: KPITarget) -> KpiScope:
    return KpiScope(unit_id=target.scope_unit_id, vertical_id=target.scope_vertical_id, user_id=target.scope_user_id)


async def _target_response(target: KPITarget, refs: _Refs) -> KpiTargetResponse:
    kpi = await refs.kpi(target.kpi_definition_id)
    period = await refs.period(target.period_id)
    return KpiTargetResponse(
        id=target.id,
        kpi=KpiRef(code=kpi.code, name=kpi.name, unit=kpi.unit),
        period=PeriodRef(id=period.id, name=period.name),
        scope=_target_scope(target),
        goal_id=target.goal_id,
        target_value=float(target.target_value),
        stretch_value=float(target.stretch_value) if target.stretch_value is not None else None,
        revision_no=target.revision_no,
        supersedes_id=target.supersedes_id,
        status=target.status,
        approval_request_id=target.approval_request_id,
        approved_at=target.approved_at,
        version=target.version,
    )


def _same_scope(scope: KpiScope):
    conditions = []
    for name, column in (("unit_id", KPITarget.scope_unit_id), ("vertical_id", KPITarget.scope_vertical_id), ("user_id", KPITarget.scope_user_id)):
        value = getattr(scope, name)
        conditions.append(column == value if value is not None else column.is_(None))
    return conditions


async def _check_no_open_target(session: AsyncSession, kpi_id: uuid.UUID, period_id: uuid.UUID, scope: KpiScope) -> None:
    open_target = await session.execute(
        select(KPITarget.id).where(
            KPITarget.kpi_definition_id == kpi_id, KPITarget.period_id == period_id,
            KPITarget.status.in_(OPEN_TARGET_STATUSES), *_same_scope(scope),
        ).limit(1)
    )
    if open_target.first():
        raise DuplicateOpenTargetError()


async def _target_in_view(session: AsyncSession, actor: Actor, target_id: uuid.UUID) -> KPITarget:
    target = await get_in_org(session, KPITarget, target_id, actor.organization_id, KPITargetNotFoundError(str(target_id)))
    if actor.only_own(permissions.KPI_TARGET_READ):
        owned_goals = await _goals_owned_by(session, actor.organization_id, actor.user_id)
        if target.scope_user_id != actor.user_id and target.goal_id not in owned_goals:
            raise KPITargetNotFoundError(str(target_id))
    return target


async def list_targets(
    session: AsyncSession,
    actor: Actor,
    period_id: Optional[uuid.UUID],
    kpi_code: Optional[str],
    status: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[KpiTargetResponse]:
    query = select(KPITarget).where(KPITarget.organization_id == actor.organization_id)
    if period_id is not None:
        query = query.where(KPITarget.period_id == period_id)
    if status is not None:
        query = query.where(KPITarget.status == status)
    if kpi_code is not None:
        kpi = await get_kpi_by_code(session, actor.organization_id, kpi_code)
        query = query.where(KPITarget.kpi_definition_id == kpi.id)
    if actor.only_own(permissions.KPI_TARGET_READ):
        owned_goals = await _goals_owned_by(session, actor.organization_id, actor.user_id)
        query = query.where(or_(KPITarget.scope_user_id == actor.user_id, KPITarget.goal_id.in_(owned_goals)))
    rows, page = await paginate_by_id(session, query, KPITarget, limit, cursor)
    refs = _Refs(session)
    return PageResponse(data=[await _target_response(row, refs) for row in rows], page=page)


async def create_target(session: AsyncSession, org_id: uuid.UUID, data: KpiTargetCreate) -> KpiTargetResponse:
    kpi = await kpi_reference(session, org_id, data.kpi_code)
    period = await period_reference(session, org_id, data.period_id)
    if period.status == CLOSED:
        raise PeriodClosedError(period.name)
    if data.goal_id is not None:
        goal = await session.get(StrategicGoal, data.goal_id)
        if goal is None or goal.organization_id != org_id:
            raise UnknownReferenceError("STRATEGIC_GOAL_NOT_FOUND", "goal_id", "Goal not found.")
    await _check_no_open_target(session, kpi.id, period.id, data.scope)
    target = KPITarget(
        organization_id=org_id, kpi_definition_id=kpi.id, period_id=period.id, goal_id=data.goal_id,
        scope_unit_id=data.scope.unit_id, scope_vertical_id=data.scope.vertical_id, scope_user_id=data.scope.user_id,
        target_value=data.target_value, stretch_value=data.stretch_value, revision_no=1, status="draft", version=1,
    )
    session.add(target)
    await session.flush()
    return await _target_response(target, _Refs(session))


async def _apply_decision(session: AsyncSession, target: KPITarget, control_status: str) -> None:
    new_status = _TARGET_AFTER_DECISION.get(control_status)
    if new_status is None or target.status != "pending_approval":
        return
    target.status = new_status
    target.version += 1
    if new_status != "approved":
        if new_status == "draft":
            target.approval_request_id = None
        await session.flush()
        return
    target.approved_at = datetime.now(timezone.utc)
    earlier = (
        await session.execute(
            select(KPITarget).where(
                KPITarget.kpi_definition_id == target.kpi_definition_id, KPITarget.period_id == target.period_id,
                KPITarget.status == "approved", KPITarget.id != target.id, *_same_scope(_target_scope(target)),
            )
        )
    ).scalars().all()
    for older in earlier:
        older.status = "superseded"
    await session.flush()
    kpi = await session.get(KPIDefinition, target.kpi_definition_id)
    period = await session.get(PlanningPeriod, target.period_id)
    await _refresh_quietly(session, kpi, period, [kpi_engine.scope_key(_target_scope(target))])


async def get_target(session: AsyncSession, actor: Actor, control: ControlClient, target_id: uuid.UUID) -> KpiTargetResponse:
    """The target; one waiting on control picks up control's decision when the caller may see it."""
    target = await _target_in_view(session, actor, target_id)
    if target.status == "pending_approval" and target.approval_request_id is not None:
        state = await control.request_state(actor, target.approval_request_id)
        if state is not None:
            await _apply_decision(session, target, state.status)
    return await _target_response(target, _Refs(session))


async def update_target(
    session: AsyncSession, org_id: uuid.UUID, target_id: uuid.UUID, data: KpiTargetRevisionCreate, if_match: Optional[str]
) -> KpiTargetResponse:
    target = await get_in_org(session, KPITarget, target_id, org_id, KPITargetNotFoundError(str(target_id)))
    check_if_match(if_match, target.version)
    if target.status != "draft":
        raise InvalidStateTransitionError("target", target.status, "edit")
    target.target_value, target.stretch_value = data.target_value, data.stretch_value
    target.version += 1
    await session.flush()
    return await _target_response(target, _Refs(session))


async def submit_target(
    session: AsyncSession, actor: Actor, control: ControlClient, target_id: uuid.UUID, if_match: Optional[str]
) -> KpiTargetResponse:
    target = await get_in_org(session, KPITarget, target_id, actor.organization_id, KPITargetNotFoundError(str(target_id)))
    check_if_match(if_match, target.version)
    if target.status != "draft":
        raise InvalidStateTransitionError("target", target.status, "submit")
    refs = _Refs(session)
    kpi, period = await refs.kpi(target.kpi_definition_id), await refs.period(target.period_id)
    if period.status == CLOSED:
        raise PeriodClosedError(period.name)
    state = await control.raise_request(
        actor,
        subject_type=TARGET_SUBJECT_TYPE,
        subject_id=target.id,
        subject_version=str(target.version),
        request_type=TARGET_REQUEST_TYPE,
        title=f"Target for {kpi.name} in {period.name}: {float(target.target_value):g}",
        context={
            "kpi_code": kpi.code,
            "period": period.name,
            "target_value": float(target.target_value),
            "stretch_value": float(target.stretch_value) if target.stretch_value is not None else None,
            "revision_no": target.revision_no,
            "scope": _target_scope(target).model_dump(mode="json"),
        },
    )
    target.status = "pending_approval"
    target.approval_request_id = state.id
    target.version += 1
    await session.flush()
    await _apply_decision(session, target, state.status)
    return await _target_response(target, refs)


async def revise_target(
    session: AsyncSession, org_id: uuid.UUID, target_id: uuid.UUID, data: KpiTargetRevisionCreate
) -> KpiTargetResponse:
    """A new draft revision of an approved (or rejected) target; it governs once approved."""
    source = await get_in_org(session, KPITarget, target_id, org_id, KPITargetNotFoundError(str(target_id)))
    if source.status not in ("approved", "rejected"):
        raise InvalidStateTransitionError("target", source.status, "revise")
    period = await session.get(PlanningPeriod, source.period_id)
    if period.status == CLOSED:
        raise PeriodClosedError(period.name)
    await _check_no_open_target(session, source.kpi_definition_id, source.period_id, _target_scope(source))
    revision = KPITarget(
        organization_id=org_id, kpi_definition_id=source.kpi_definition_id, period_id=source.period_id,
        goal_id=source.goal_id, supersedes_id=source.id, scope_unit_id=source.scope_unit_id,
        scope_vertical_id=source.scope_vertical_id, scope_user_id=source.scope_user_id,
        target_value=data.target_value, stretch_value=data.stretch_value,
        revision_no=source.revision_no + 1, status="draft", version=1,
    )
    session.add(revision)
    await session.flush()
    return await _target_response(revision, _Refs(session))


# --- Results ------------------------------------------------------------------


async def _result_filter_for(session: AsyncSession, actor: Actor):
    """None when the caller sees every result; else the condition limiting them to their own."""
    if not actor.only_own(permissions.RESULT_READ):
        return None
    goal_ids = await _goals_owned_by(session, actor.organization_id, actor.user_id)
    owned_kpis = select(GoalKPI.kpi_definition_id).where(GoalKPI.goal_id.in_(goal_ids)) if goal_ids else None
    mine = KPIResult.scope_key.contains(kpi_engine.user_scope_fragment(actor.user_id))
    return or_(mine, KPIResult.kpi_definition_id.in_(owned_kpis)) if owned_kpis is not None else mine


async def list_results(
    session: AsyncSession,
    actor: Actor,
    period_id: uuid.UUID,
    kpi_code: Optional[str],
    unit_id: Optional[uuid.UUID],
    vertical_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    status: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[KpiResultResponse]:
    query = select(KPIResult).where(KPIResult.organization_id == actor.organization_id, KPIResult.period_id == period_id)
    if status is not None:
        query = query.where(KPIResult.status == status)
    if kpi_code is not None:
        kpi = await get_kpi_by_code(session, actor.organization_id, kpi_code)
        query = query.where(KPIResult.kpi_definition_id == kpi.id)
    for letter, value in (("u", unit_id), ("v", vertical_id), ("p", user_id)):
        if value is not None:
            query = query.where(KPIResult.scope_key.contains(f"{letter}{value.hex}"))
    own_filter = await _result_filter_for(session, actor)
    if own_filter is not None:
        query = query.where(own_filter)
    rows, page = await paginate_by_id(session, query, KPIResult, limit, cursor)
    refs = _Refs(session)
    return PageResponse(data=[await result_response(row, refs) for row in rows], page=page)


async def _result_in_view(session: AsyncSession, actor: Actor, result_id: uuid.UUID) -> KPIResult:
    query = select(KPIResult).where(KPIResult.id == result_id, KPIResult.organization_id == actor.organization_id)
    own_filter = await _result_filter_for(session, actor)
    if own_filter is not None:
        query = query.where(own_filter)
    result = (await session.execute(query)).scalars().first()
    if result is None:
        raise KPIResultNotFoundError(str(result_id))
    return result


async def get_result(session: AsyncSession, actor: Actor, result_id: uuid.UUID) -> KpiResultResponse:
    return await result_response(await _result_in_view(session, actor, result_id), _Refs(session))


async def calculate_period(
    session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID, kpi_code: Optional[str]
) -> CalculationResponse:
    """Recalculate a period (or one KPI in it). Refusals are errors here: the caller asked for this number."""
    period = await period_reference(session, org_id, period_id)
    if period.status == CLOSED:
        raise PeriodClosedError(period.name)
    kpis = [await kpi_reference(session, org_id, kpi_code)] if kpi_code else await _kpis_for_period(session, period)
    calculated = unchanged = 0
    results: list[KPIResult] = []
    for kpi in kpis:
        for key in sorted(await _scopes_to_refresh(session, kpi.id, period.id)):
            calculation = await kpi_engine.calculate(session, kpi, period, kpi_engine.parse_scope_key(key))
            calculated += calculation.changed
            unchanged += not calculation.changed
            results.append(calculation.result)
    refs = _Refs(session)
    return CalculationResponse(
        calculated=calculated, unchanged=unchanged, results=[await result_response(r, refs) for r in results]
    )


async def _kpis_for_period(session: AsyncSession, period: PlanningPeriod) -> list[KPIDefinition]:
    """Active KPIs with a target, a result or a measurement in the period."""
    measured = select(KPIMeasurement.kpi_definition_id).where(
        KPIMeasurement.organization_id == period.organization_id,
        KPIMeasurement.measured_on >= period.start_date,
        KPIMeasurement.measured_on <= period.end_date,
    )
    targeted = select(KPITarget.kpi_definition_id).where(KPITarget.period_id == period.id)
    resulted = select(KPIResult.kpi_definition_id).where(KPIResult.period_id == period.id)
    rows = (
        await session.execute(
            select(KPIDefinition).where(
                KPIDefinition.organization_id == period.organization_id,
                KPIDefinition.status == "active",
                or_(KPIDefinition.id.in_(measured), KPIDefinition.id.in_(targeted), KPIDefinition.id.in_(resulted),
                    KPIDefinition.aggregation == "ratio"),
            ).order_by(KPIDefinition.code)
        )
    ).scalars().all()
    return list(rows)


def _snapshot_payload(result: KPIResult, response: KpiResultResponse, measurement_ids: list[str], reason: str) -> dict:
    return {
        "reason": reason,
        "calc_version": result.calc_version,
        "result": response.model_dump(mode="json"),
        "measurement_ids": sorted(measurement_ids),
    }


async def _freeze(session: AsyncSession, period: PlanningPeriod) -> int:
    """Recalculate a period one last time and freeze every result into a snapshot."""
    for kpi in await _kpis_for_period(session, period):
        await _refresh_quietly(session, kpi, period, await _scopes_to_refresh(session, kpi.id, period.id))
    results = (await session.execute(select(KPIResult).where(KPIResult.period_id == period.id))).scalars().all()
    refs = _Refs(session)
    for result in results:
        kpi = await refs.kpi(result.kpi_definition_id)
        try:
            _, readings = await kpi_engine.actual_for(session, kpi, period, kpi_engine.parse_scope_key(result.scope_key))
        except (KPINotAggregableError, KPIFormulaError):
            readings = []  # the frozen result is what was last calculated; its inputs can't be listed
        response = await result_response(result, refs)
        session.add(KPIPeriodSnapshot(
            kpi_result_id=result.id,
            payload=_snapshot_payload(result, response, [str(r.id) for r in readings], "period_close"),
        ))
    period.status = CLOSED
    await session.flush()
    return len(results)


async def _close_with_children(session: AsyncSession, period: PlanningPeriod) -> int:
    children = (
        await session.execute(
            select(PlanningPeriod).where(PlanningPeriod.parent_period_id == period.id, PlanningPeriod.status != CLOSED)
        )
    ).scalars().all()
    frozen = 0
    for child in children:
        frozen += await _close_with_children(session, child)
    return frozen + await _freeze(session, period)


async def close_period(session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID) -> PeriodCloseResponse:
    """Close a period (and the periods inside it): results are recalculated, frozen and no longer change."""
    period = await get_period(session, org_id, period_id)
    if period.status == CLOSED:
        raise InvalidStateTransitionError("period", period.status, "close")
    frozen = await _close_with_children(session, period)
    return PeriodCloseResponse(period=period_response(period), results_frozen=frozen)


async def close_fiscal_year(session: AsyncSession, org_id: uuid.UUID, year_id: uuid.UUID) -> int:
    year = await get_fiscal_year(session, org_id, year_id)
    if year.status == CLOSED:
        raise InvalidStateTransitionError("fiscal year", year.status, "close")
    top_level = (
        await session.execute(
            select(PlanningPeriod).where(
                PlanningPeriod.fiscal_year_id == year.id, PlanningPeriod.parent_period_id.is_(None), PlanningPeriod.status != CLOSED
            )
        )
    ).scalars().all()
    frozen = 0
    for period in top_level:
        frozen += await _close_with_children(session, period)
    year.status = CLOSED
    await session.flush()
    return frozen


async def restate_result(
    session: AsyncSession, actor: Actor, result_id: uuid.UUID, data: RestatementCreate
) -> KpiResultResponse:
    """Correct a closed period's result: record the corrections, recalculate as a new calc_version, freeze it anew."""
    result = await get_in_org(session, KPIResult, result_id, actor.organization_id, KPIResultNotFoundError(str(result_id)))
    period = await session.get(PlanningPeriod, result.period_id)
    if period.status != CLOSED:
        raise InvalidStateTransitionError("period", period.status, "restate a result of")
    if not data.reverse_measurement_ids and not data.new_measurements:
        raise ValidationFailedError("new_measurements", "a restatement needs at least one correction")
    kpi = await session.get(KPIDefinition, result.kpi_definition_id)
    if kpi.aggregation == "ratio":
        raise KPINotManualError()
    in_period = lambda day: period.start_date <= day <= period.end_date  # noqa: E731
    for measurement_id in data.reverse_measurement_ids:
        original = await _reversible(session, actor.organization_id, measurement_id)
        if original.kpi_definition_id != kpi.id or not in_period(original.measured_on):
            raise ValidationFailedError("reverse_measurement_ids", f"{measurement_id} isn't a measurement of this result")
        session.add(_reversal_of(original, actor.user_id))
    for value in data.new_measurements:
        if not in_period(value.measured_on):
            raise ValidationFailedError("new_measurements", f"{value.measured_on} is outside {period.name}")
        session.add(_new_measurement(kpi, value, actor.user_id))
    await session.flush()
    calculation = await kpi_engine.calculate(
        session, kpi, period, kpi_engine.parse_scope_key(result.scope_key), restatement=True
    )
    refs = _Refs(session)
    response = await result_response(calculation.result, refs)
    session.add(KPIPeriodSnapshot(
        kpi_result_id=calculation.result.id,
        payload=_snapshot_payload(calculation.result, response, [str(r.id) for r in calculation.readings], data.reason),
    ))
    await session.flush()
    return response


async def list_snapshots(session: AsyncSession, actor: Actor, result_id: uuid.UUID) -> list[SnapshotResponse]:
    result = await _result_in_view(session, actor, result_id)
    rows = (
        await session.execute(
            select(KPIPeriodSnapshot).where(KPIPeriodSnapshot.kpi_result_id == result.id).order_by(KPIPeriodSnapshot.frozen_at)
        )
    ).scalars().all()
    return [SnapshotResponse(id=row.id, kpi_result_id=row.kpi_result_id, frozen_at=row.frozen_at, payload=row.payload) for row in rows]


# --- Scorecard ----------------------------------------------------------------


@dataclass(frozen=True)
class _Weighted:
    weight: float
    achievement_pct: float


def _goal_score(items: list[_Weighted]) -> Optional[float]:
    total_weight = sum(item.weight for item in items)
    if not items or total_weight == 0:
        return None
    return round(sum(item.weight * item.achievement_pct for item in items) / total_weight, 2)


def active_goals_in(org_id: uuid.UUID, period: PlanningPeriod):
    """Active goals the period falls in: without a period of their own, or with one covering it."""
    period_of_goal = select(PlanningPeriod.id).where(
        PlanningPeriod.organization_id == org_id,
        PlanningPeriod.start_date <= period.start_date,
        PlanningPeriod.end_date >= period.end_date,
    )
    return select(StrategicGoal).where(
        StrategicGoal.organization_id == org_id,
        StrategicGoal.status == "active",
        or_(StrategicGoal.period_id.is_(None), StrategicGoal.period_id.in_(period_of_goal)),
    )


async def scorecard(session: AsyncSession, actor: Actor, period_id: uuid.UUID, directory: Directory) -> ScorecardResponse:
    """Each active goal the period falls in: its KPIs' results for the goal's scope, its weighted score, and the owner's latest check-in."""
    period = await period_reference(session, actor.organization_id, period_id)
    query = active_goals_in(actor.organization_id, period)
    if actor.only_own(permissions.RESULT_READ):
        query = query.where(StrategicGoal.owner_user_id == actor.user_id)
    goals = (await session.execute(query.order_by(StrategicGoal.code))).scalars().all()
    refs = _Refs(session)
    rows: list[ScorecardGoal] = []
    for goal in goals:
        key = kpi_engine.scope_key(KpiScope(unit_id=goal.scope_unit_id, vertical_id=goal.scope_vertical_id))
        links = (
            await session.execute(
                select(GoalKPI, KPIDefinition).join(KPIDefinition, KPIDefinition.id == GoalKPI.kpi_definition_id)
                .where(GoalKPI.goal_id == goal.id).order_by(KPIDefinition.code)
            )
        ).all()
        kpis, weighted = [], []
        for link, kpi in links:
            found = await kpi_engine.find_result(session, kpi.id, period.id, key)
            response = await result_response(found, refs) if found else None
            if response is not None and response.achievement_pct is not None:
                weighted.append(_Weighted(float(link.weight), response.achievement_pct))
            kpis.append(ScorecardKpi(kpi_code=kpi.code, name=kpi.name, weight=float(link.weight), result=response))
        score = _goal_score(weighted)
        computed = kpi_engine.rag(Decimal(str(score)), kpi_engine.DEFAULT_GREEN, kpi_engine.DEFAULT_AMBER) if score is not None else None
        check_in = await latest_check_in(session, goal_id=goal.id)
        rows.append(ScorecardGoal(
            goal_id=goal.id, code=goal.code, name=goal.name, owner=await directory.user(goal.owner_user_id),
            score_pct=score, computed_rag=computed,
            check_in=ScorecardCheckIn(
                confidence=float(check_in.confidence), confidence_band=confidence_band(float(check_in.confidence)),
                rag=check_in.rag, narrative=check_in.narrative, created_at=check_in.created_at,
            ) if check_in else None,
            disagreement=bool(check_in and computed and check_in.rag != computed),
            kpis=kpis,
        ))
    return ScorecardResponse(period=PeriodRef(id=period.id, name=period.name), goals=rows)


# --- Corrective actions -------------------------------------------------------


async def _action_response(action: CorrectiveAction, directory: Directory, refs: _Refs) -> CorrectiveActionResponse:
    result = await refs.session.get(KPIResult, action.kpi_result_id)
    kpi = await refs.kpi(result.kpi_definition_id)
    return CorrectiveActionResponse(
        id=action.id, title=action.title, kpi=KpiStatusRef(code=kpi.code, status=result.status),
        kpi_result_id=result.id, period_id=result.period_id, owner=await directory.user(action.owner_user_id),
        due_date=action.due_date, task_id=action.task_id, status=action.status, closure_note=action.closure_note,
    )


async def list_corrective_actions(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    status: Optional[str],
    owner_user_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[CorrectiveActionResponse]:
    query = select(CorrectiveAction).where(CorrectiveAction.organization_id == org_id)
    if status is not None:
        query = query.where(CorrectiveAction.status == status)
    if owner_user_id is not None:
        query = query.where(CorrectiveAction.owner_user_id == owner_user_id)
    rows, page = await paginate_by_id(session, query, CorrectiveAction, limit, cursor)
    refs = _Refs(session)
    return PageResponse(data=[await _action_response(row, directory, refs) for row in rows], page=page)


async def create_corrective_action(
    session: AsyncSession, org_id: uuid.UUID, data: CorrectiveActionCreate, directory: Directory
) -> CorrectiveActionResponse:
    """An action against a calculated result: never against a number made up for the occasion."""
    kpi = await kpi_reference(session, org_id, data.kpi_code)
    period = await period_reference(session, org_id, data.period_id)
    result = await kpi_engine.find_result(session, kpi.id, period.id, kpi_engine.scope_key(data.scope))
    if result is None:
        raise UnknownReferenceError(
            "KPI_RESULT_NOT_FOUND", "kpi_code",
            f"'{kpi.code}' has no result for {period.name} in that scope yet; calculate it first.",
        )
    action = CorrectiveAction(
        kpi_result_id=result.id, organization_id=org_id, title=data.title, owner_user_id=data.owner_user_id,
        due_date=data.due_date, task_id=data.task_id, status="open",
    )
    session.add(action)
    await session.flush()
    return await _action_response(action, directory, _Refs(session))


async def update_corrective_action(
    session: AsyncSession, actor: Actor, action_id: uuid.UUID, data: CorrectiveActionUpdate, directory: Directory
) -> CorrectiveActionResponse:
    """Its owner moves it along (status, closure note, linked task); reassigning or rescheduling needs manage."""
    action = await get_in_org(session, CorrectiveAction, action_id, actor.organization_id, CorrectiveActionNotFoundError(str(action_id)))
    changes = data.model_dump(exclude_unset=True)
    if not actor.has(permissions.CORRECTIVE_ACTION_MANAGE):
        if action.owner_user_id != actor.user_id or not changes.keys() <= {"status", "closure_note", "task_id"}:
            raise PermissionDeniedError(
                permissions.CORRECTIVE_ACTION_MANAGE, "Only the owner updates this action's progress; other changes need manage."
            )
    if action.status in ("done", "cancelled"):
        raise InvalidStateTransitionError("corrective action", action.status, "change")
    if changes.get("status") == "done" and not (changes.get("closure_note") or action.closure_note):
        raise ValidationFailedError("closure_note", "say what was done before closing the action")
    for field_name, value in changes.items():
        setattr(action, field_name, value)
    await session.flush()
    return await _action_response(action, directory, _Refs(session))
