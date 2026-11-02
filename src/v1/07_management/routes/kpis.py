import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.kpi_service as service
from dependencies import (
    Control,
    CurrentActor,
    DatabaseSession,
    Names,
    OrgId,
    require_any_permission,
    require_permission,
)
from schemas.common import ListResponse, PageResponse
from schemas.kpi import (
    CalculationRequest,
    CalculationResponse,
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    CorrectiveActionUpdate,
    KpiDefinitionCreate,
    KpiDefinitionResponse,
    KpiDefinitionUpdate,
    KpiResultResponse,
    KpiSourceCreate,
    KpiSourceItem,
    KpiTargetCreate,
    KpiTargetResponse,
    KpiTargetRevisionCreate,
    KpiThresholdCreate,
    KpiThresholdResponse,
    ManualMeasurementCreate,
    MeasurementResponse,
    MeasurementReversal,
    MeasurementWriteResponse,
    RestatementCreate,
    ScorecardResponse,
    SnapshotResponse,
)

router = APIRouter(tags=["performance"])

CAN_READ_KPIS = Depends(require_permission(permissions.KPI_READ))
CAN_MANAGE_KPIS = Depends(require_permission(permissions.KPI_MANAGE))
CAN_MEASURE = Depends(require_permission(permissions.MEASUREMENT_CREATE))
CAN_READ_RESULTS = Depends(require_permission(permissions.RESULT_READ))
CAN_CLOSE_PERIODS = Depends(require_permission(permissions.PERIOD_CLOSE_MANAGE))
CAN_READ_TARGETS = Depends(require_permission(permissions.KPI_TARGET_READ))
CAN_MANAGE_TARGETS = Depends(require_permission(permissions.KPI_TARGET_MANAGE))
CAN_READ_ACTIONS = Depends(require_permission(permissions.CORRECTIVE_ACTION_READ))
CAN_MANAGE_ACTIONS = Depends(require_permission(permissions.CORRECTIVE_ACTION_MANAGE))
# The owner of an action moves it along with read access; the service checks who they are.
CAN_WORK_ACTIONS = Depends(require_any_permission(permissions.CORRECTIVE_ACTION_MANAGE, permissions.CORRECTIVE_ACTION_READ))

Limit = Query(25, ge=1, le=100)


# --- Definitions --------------------------------------------------------------


@router.get("/kpi-definitions", response_model=PageResponse[KpiDefinitionResponse], dependencies=[CAN_READ_KPIS])
async def list_kpi_definitions(
    session: DatabaseSession, org_id: OrgId, names: Names, status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit, cursor: Optional[str] = Query(None),
) -> PageResponse[KpiDefinitionResponse]:
    return await service.list_definitions(session, org_id, names, status_, limit, cursor)


@router.post("/kpi-definitions", response_model=KpiDefinitionResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_KPIS])
async def create_kpi_definition(
    payload: KpiDefinitionCreate, session: DatabaseSession, org_id: OrgId, names: Names
) -> KpiDefinitionResponse:
    kpi = await service.create_definition(session, org_id, payload, names)
    await session.commit()
    return kpi


@router.get("/kpi-definitions/{code}", response_model=KpiDefinitionResponse, dependencies=[CAN_READ_KPIS])
async def get_kpi_definition(code: str, session: DatabaseSession, org_id: OrgId, names: Names) -> KpiDefinitionResponse:
    return await service.get_definition(session, org_id, code, names)


@router.patch("/kpi-definitions/{code}", response_model=KpiDefinitionResponse, dependencies=[CAN_MANAGE_KPIS])
async def update_kpi_definition(
    code: str, payload: KpiDefinitionUpdate, session: DatabaseSession, org_id: OrgId, names: Names
) -> KpiDefinitionResponse:
    """Changing how the number is produced (unit, direction, aggregation, formula, frequency) bumps version_no."""
    kpi = await service.update_definition(session, org_id, code, payload, names)
    await session.commit()
    return kpi


@router.post("/kpi-definitions/{code}/sources", response_model=KpiSourceItem, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_KPIS])
async def add_kpi_source(code: str, payload: KpiSourceCreate, session: DatabaseSession, org_id: OrgId) -> KpiSourceItem:
    source = await service.add_source(session, org_id, code, payload)
    await session.commit()
    return source


@router.delete("/kpi-definitions/{code}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE_KPIS])
async def remove_kpi_source(code: str, source_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await service.remove_source(session, org_id, code, source_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/kpi-definitions/{code}/thresholds", response_model=KpiThresholdResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_KPIS],
)
async def add_kpi_threshold(code: str, payload: KpiThresholdCreate, session: DatabaseSession, org_id: OrgId) -> KpiThresholdResponse:
    """Green and amber as achievement percentages, for the KPI or for one unit; the colour then follows mechanically."""
    threshold = await service.add_threshold(session, org_id, code, payload)
    await session.commit()
    return threshold


@router.delete("/kpi-definitions/{code}/thresholds/{threshold_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE_KPIS])
async def remove_kpi_threshold(code: str, threshold_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await service.remove_threshold(session, org_id, code, threshold_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Measurements -------------------------------------------------------------


@router.get("/measurements", response_model=PageResponse[MeasurementResponse], dependencies=[CAN_READ_RESULTS])
async def list_measurements(
    session: DatabaseSession,
    actor: CurrentActor,
    kpi_code: Optional[str] = Query(None),
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[MeasurementResponse]:
    return await service.list_measurements(session, actor, kpi_code, from_, to, limit, cursor)


@router.post("/measurements", response_model=MeasurementWriteResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MEASURE])
async def record_measurement(payload: ManualMeasurementCreate, session: DatabaseSession, actor: CurrentActor) -> MeasurementWriteResponse:
    """Record a manual measurement; the open periods it falls in are recalculated."""
    written = await service.record_measurement(session, actor, payload)
    await session.commit()
    return written


@router.post(
    "/measurements/{measurement_id}/reversal", response_model=MeasurementWriteResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MEASURE],
)
async def reverse_measurement(
    measurement_id: uuid.UUID, payload: MeasurementReversal, session: DatabaseSession, actor: CurrentActor
) -> MeasurementWriteResponse:
    """Measurements are never edited: a correction reverses one, optionally with a replacement value."""
    written = await service.reverse_measurement(session, actor, measurement_id, payload)
    await session.commit()
    return written


# --- Targets ------------------------------------------------------------------


@router.get("/kpi-targets", response_model=PageResponse[KpiTargetResponse], dependencies=[CAN_READ_TARGETS])
async def list_kpi_targets(
    session: DatabaseSession,
    actor: CurrentActor,
    period_id: Optional[uuid.UUID] = Query(None),
    kpi_code: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[KpiTargetResponse]:
    return await service.list_targets(session, actor, period_id, kpi_code, status_, limit, cursor)


@router.post("/kpi-targets", response_model=KpiTargetResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_TARGETS])
async def create_kpi_target(payload: KpiTargetCreate, session: DatabaseSession, org_id: OrgId) -> KpiTargetResponse:
    """Create a KPI target (draft)."""
    target = await service.create_target(session, org_id, payload)
    await session.commit()
    return target


@router.get("/kpi-targets/{target_id}", response_model=KpiTargetResponse, dependencies=[CAN_READ_TARGETS])
async def get_kpi_target(target_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, control: Control) -> KpiTargetResponse:
    """The target; one waiting for approval picks up control's decision."""
    target = await service.get_target(session, actor, control, target_id)
    await session.commit()
    return target


@router.patch("/kpi-targets/{target_id}", response_model=KpiTargetResponse, dependencies=[CAN_MANAGE_TARGETS])
async def update_kpi_target(
    target_id: uuid.UUID, payload: KpiTargetRevisionCreate, session: DatabaseSession, org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> KpiTargetResponse:
    """Change a draft target's values."""
    target = await service.update_target(session, org_id, target_id, payload, if_match)
    await session.commit()
    return target


@router.post("/kpi-targets/{target_id}/submit", response_model=KpiTargetResponse, dependencies=[CAN_MANAGE_TARGETS])
async def submit_kpi_target(
    target_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, control: Control,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> KpiTargetResponse:
    """Submit a draft target for approval: raises a control approval request."""
    target = await service.submit_target(session, actor, control, target_id, if_match)
    await session.commit()
    return target


@router.post("/kpi-targets/{target_id}/revisions", response_model=KpiTargetResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_TARGETS])
async def revise_kpi_target(
    target_id: uuid.UUID, payload: KpiTargetRevisionCreate, session: DatabaseSession, org_id: OrgId
) -> KpiTargetResponse:
    """A new draft revision of an approved target; the approved one governs until the revision is approved."""
    target = await service.revise_target(session, org_id, target_id, payload)
    await session.commit()
    return target


# --- Results ------------------------------------------------------------------


@router.get("/kpi-results", response_model=PageResponse[KpiResultResponse], dependencies=[CAN_READ_RESULTS])
async def list_kpi_results(
    session: DatabaseSession,
    actor: CurrentActor,
    period_id: uuid.UUID = Query(...),
    kpi_code: Optional[str] = Query(None),
    unit_id: Optional[uuid.UUID] = Query(None),
    vertical_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[KpiResultResponse]:
    """KPI results (target vs actual)."""
    return await service.list_results(session, actor, period_id, kpi_code, unit_id, vertical_id, user_id, status_, limit, cursor)


@router.post("/kpi-results/calculations", response_model=CalculationResponse, dependencies=[CAN_MANAGE_KPIS])
async def calculate_kpi_results(payload: CalculationRequest, session: DatabaseSession, org_id: OrgId) -> CalculationResponse:
    """Recalculate a period's results (or one KPI's). Unchanged inputs write nothing."""
    calculation = await service.calculate_period(session, org_id, payload.period_id, payload.kpi_code)
    await session.commit()
    return calculation


@router.get("/kpi-results/{result_id}", response_model=KpiResultResponse, dependencies=[CAN_READ_RESULTS])
async def get_kpi_result(result_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> KpiResultResponse:
    return await service.get_result(session, actor, result_id)


@router.get("/kpi-results/{result_id}/snapshots", response_model=ListResponse[SnapshotResponse], dependencies=[CAN_READ_RESULTS])
async def list_kpi_result_snapshots(result_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> ListResponse[SnapshotResponse]:
    """What the result was frozen as at period close, and at each restatement."""
    return ListResponse(data=await service.list_snapshots(session, actor, result_id))


@router.post("/kpi-results/{result_id}/restatements", response_model=KpiResultResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_CLOSE_PERIODS])
async def restate_kpi_result(
    result_id: uuid.UUID, payload: RestatementCreate, session: DatabaseSession, actor: CurrentActor
) -> KpiResultResponse:
    """Correct a closed period's result: a new calc_version and a new snapshot; the old snapshot stays."""
    result = await service.restate_result(session, actor, result_id, payload)
    await session.commit()
    return result


@router.get("/scorecard", response_model=ScorecardResponse, dependencies=[CAN_READ_RESULTS])
async def get_scorecard(
    session: DatabaseSession, actor: CurrentActor, names: Names, period_id: uuid.UUID = Query(...)
) -> ScorecardResponse:
    """Goals with their KPIs' achievement next to the owner's latest confidence."""
    return await service.scorecard(session, actor, period_id, names)


# --- Corrective actions -------------------------------------------------------


@router.get("/corrective-actions", response_model=PageResponse[CorrectiveActionResponse], dependencies=[CAN_READ_ACTIONS])
async def list_corrective_actions(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    status_: Optional[str] = Query(None, alias="status"),
    owner_user_id: Optional[uuid.UUID] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[CorrectiveActionResponse]:
    return await service.list_corrective_actions(session, org_id, names, status_, owner_user_id, limit, cursor)


@router.post("/corrective-actions", response_model=CorrectiveActionResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_ACTIONS])
async def create_corrective_action(
    payload: CorrectiveActionCreate, session: DatabaseSession, org_id: OrgId, names: Names
) -> CorrectiveActionResponse:
    """A corrective action against a calculated result, with an owner and a due date."""
    action = await service.create_corrective_action(session, org_id, payload, names)
    await session.commit()
    return action


@router.patch("/corrective-actions/{action_id}", response_model=CorrectiveActionResponse, dependencies=[CAN_WORK_ACTIONS])
async def update_corrective_action(
    action_id: uuid.UUID, payload: CorrectiveActionUpdate, session: DatabaseSession, actor: CurrentActor, names: Names
) -> CorrectiveActionResponse:
    action = await service.update_corrective_action(session, actor, action_id, payload, names)
    await session.commit()
    return action
