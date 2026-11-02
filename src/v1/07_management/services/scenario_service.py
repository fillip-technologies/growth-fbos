"""
Scenarios, deliberately small (plan Phase G): copy a period's approved company-wide targets as the
baseline, apply one assumption, and compare against the actual results. No driver-based forecast
engine: few organisations automate one, and a what-if table is the right size.
"""

from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InvalidStateTransitionError, ScenarioNotFoundError, ValidationFailedError
from models.performance import KPIDefinition, KPITarget
from models.planning import PlanningPeriod, Scenario, ScenarioValue
from schemas.common import PageResponse
from schemas.planning import PeriodRef
from schemas.scenario import (
    Assumption,
    ScenarioCreate,
    ScenarioResponse,
    ScenarioUpdate,
    ScenarioValueResponse,
    ScenarioValueUpdate,
)
from services import kpi_engine
from services.common import get_in_org
from services.pagination import paginate_by_id
from services.planning_service import period_reference

GLOBAL = "global"


def _apply(assumption: Assumption, baseline: Decimal) -> Decimal:
    change = Decimal(str(assumption.value))
    if assumption.type == "pct_change":
        return baseline * (1 + change / 100)
    return baseline + change


async def _value_response(session: AsyncSession, value: ScenarioValue) -> ScenarioValueResponse:
    kpi = await session.get(KPIDefinition, value.kpi_definition_id)
    baseline, projected = Decimal(value.baseline_value), Decimal(value.scenario_value)
    result = await kpi_engine.find_result(session, kpi.id, value.period_id, GLOBAL)
    return ScenarioValueResponse(
        id=value.id, kpi_code=kpi.code, kpi_name=kpi.name, period_id=value.period_id,
        baseline_value=float(baseline), scenario_value=float(projected), delta=float(projected - baseline),
        delta_pct=float(round((projected - baseline) / abs(baseline) * 100, 2)) if baseline != 0 else None,
        actual_value=float(result.actual_value) if result is not None and result.status != "no_data" else None,
    )


async def _response(session: AsyncSession, scenario: Scenario, with_values: bool = True) -> ScenarioResponse:
    period = await session.get(PlanningPeriod, scenario.base_period_id)
    values = (
        await session.execute(select(ScenarioValue).where(ScenarioValue.scenario_id == scenario.id))
    ).scalars().all() if with_values else []
    return ScenarioResponse(
        id=scenario.id, name=scenario.name, base_period=PeriodRef(id=period.id, name=period.name),
        assumption_type=scenario.assumption_type, status=scenario.status,
        values=sorted([await _value_response(session, v) for v in values], key=lambda v: v.kpi_code),
    )


async def _get(session: AsyncSession, org_id: uuid.UUID, scenario_id: uuid.UUID) -> Scenario:
    return await get_in_org(session, Scenario, scenario_id, org_id, ScenarioNotFoundError(str(scenario_id)))


async def list_scenarios(
    session: AsyncSession, org_id: uuid.UUID, status: Optional[str], limit: int, cursor: Optional[str]
) -> PageResponse[ScenarioResponse]:
    query = select(Scenario).where(Scenario.organization_id == org_id)
    if status is not None:
        query = query.where(Scenario.status == status)
    rows, page = await paginate_by_id(session, query, Scenario, limit, cursor)
    return PageResponse(data=[await _response(session, row, with_values=False) for row in rows], page=page)


async def create_scenario(session: AsyncSession, org_id: uuid.UUID, data: ScenarioCreate) -> ScenarioResponse:
    period = await period_reference(session, org_id, data.base_period_id, field="base_period_id")
    targets = (
        await session.execute(
            select(KPITarget, KPIDefinition).join(KPIDefinition, KPIDefinition.id == KPITarget.kpi_definition_id).where(
                KPITarget.organization_id == org_id, KPITarget.period_id == period.id, KPITarget.status == "approved",
                KPITarget.scope_unit_id.is_(None), KPITarget.scope_vertical_id.is_(None), KPITarget.scope_user_id.is_(None),
            )
        )
    ).all()
    wanted = set(data.assumption.kpi_codes) if data.assumption.kpi_codes else None
    if wanted is not None:
        unknown = wanted - {kpi.code for _, kpi in targets}
        if unknown:
            raise ValidationFailedError(
                "assumption.kpi_codes", f"'{sorted(unknown)[0]}' has no approved company-wide target in this period"
            )
    if not targets:
        raise ValidationFailedError("base_period_id", "the period has no approved company-wide targets to start from")
    scenario = Scenario(
        organization_id=org_id, name=data.name, base_period_id=period.id,
        assumption_type=data.assumption.type, status="draft",
    )
    session.add(scenario)
    await session.flush()
    latest: dict[uuid.UUID, KPITarget] = {}
    for target, _ in targets:
        if target.kpi_definition_id not in latest or target.revision_no > latest[target.kpi_definition_id].revision_no:
            latest[target.kpi_definition_id] = target
    codes = {kpi.id: kpi.code for _, kpi in targets}
    for kpi_id, target in latest.items():
        baseline = Decimal(target.target_value)
        applies = wanted is None or codes[kpi_id] in wanted
        session.add(ScenarioValue(
            scenario_id=scenario.id, kpi_definition_id=kpi_id, period_id=period.id, baseline_value=baseline,
            scenario_value=_apply(data.assumption, baseline) if applies else baseline,
        ))
    await session.flush()
    return await _response(session, scenario)


async def get_scenario(session: AsyncSession, org_id: uuid.UUID, scenario_id: uuid.UUID) -> ScenarioResponse:
    return await _response(session, await _get(session, org_id, scenario_id))


async def update_scenario(session: AsyncSession, org_id: uuid.UUID, scenario_id: uuid.UUID, data: ScenarioUpdate) -> ScenarioResponse:
    scenario = await _get(session, org_id, scenario_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(scenario, field_name, value)
    await session.flush()
    return await _response(session, scenario)


async def update_value(
    session: AsyncSession, org_id: uuid.UUID, scenario_id: uuid.UUID, value_id: uuid.UUID, data: ScenarioValueUpdate
) -> ScenarioResponse:
    scenario = await _get(session, org_id, scenario_id)
    if scenario.status == "archived":
        raise InvalidStateTransitionError("scenario", scenario.status, "change")
    value = await session.get(ScenarioValue, value_id)
    if value is None or value.scenario_id != scenario.id:
        raise ScenarioNotFoundError(str(value_id))
    value.scenario_value = data.scenario_value
    await session.flush()
    return await _response(session, scenario)
