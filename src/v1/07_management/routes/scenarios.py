import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

import permissions
import services.scenario_service as service
from dependencies import DatabaseSession, OrgId, require_permission
from schemas.common import PageResponse
from schemas.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate, ScenarioValueUpdate

router = APIRouter(tags=["scenarios"])

CAN_READ = Depends(require_permission(permissions.SCENARIO_READ))
CAN_MANAGE = Depends(require_permission(permissions.SCENARIO_MANAGE))


@router.get("/scenarios", response_model=PageResponse[ScenarioResponse], dependencies=[CAN_READ])
async def list_scenarios(
    session: DatabaseSession,
    org_id: OrgId,
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[ScenarioResponse]:
    return await service.list_scenarios(session, org_id, status_, limit, cursor)


@router.post("/scenarios", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_scenario(payload: ScenarioCreate, session: DatabaseSession, org_id: OrgId) -> ScenarioResponse:
    """Copy a period's approved company-wide targets as the baseline and apply one assumption."""
    scenario = await service.create_scenario(session, org_id, payload)
    await session.commit()
    return scenario


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse, dependencies=[CAN_READ])
async def get_scenario(scenario_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ScenarioResponse:
    return await service.get_scenario(session, org_id, scenario_id)


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioResponse, dependencies=[CAN_MANAGE])
async def update_scenario(scenario_id: uuid.UUID, payload: ScenarioUpdate, session: DatabaseSession, org_id: OrgId) -> ScenarioResponse:
    scenario = await service.update_scenario(session, org_id, scenario_id, payload)
    await session.commit()
    return scenario


@router.patch("/scenarios/{scenario_id}/values/{value_id}", response_model=ScenarioResponse, dependencies=[CAN_MANAGE])
async def update_scenario_value(
    scenario_id: uuid.UUID, value_id: uuid.UUID, payload: ScenarioValueUpdate, session: DatabaseSession, org_id: OrgId
) -> ScenarioResponse:
    scenario = await service.update_value(session, org_id, scenario_id, value_id, payload)
    await session.commit()
    return scenario
