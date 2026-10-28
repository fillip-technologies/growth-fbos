import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status

import permissions
import services.lifecycle_service as service
from dependencies import CurrentActor, DatabaseSession, OrgId, require_permission
from schemas.lifecycle import (
    AssetCostCreate,
    AssetCostResponse,
    AssetCostSummary,
    AssetDisposalCreate,
    AssetDisposalResponse,
    AssetRelationshipCreate,
    AssetRelationshipResponse,
    AssetRenewalCreate,
    AssetRenewalDecision,
    AssetRenewalResponse,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
)

router = APIRouter(tags=["lifecycle"])

CAN_READ = Depends(require_permission(permissions.ASSET_READ))
CAN_WRITE = Depends(require_permission(permissions.ASSET_WRITE))
CAN_MAINTAIN = Depends(require_permission(permissions.ASSET_MAINTENANCE))
CAN_DISPOSE = Depends(require_permission(permissions.ASSET_DISPOSE))


# --- Maintenance & Repairs ---------------------------------------------------


@router.post(
    "/assets/{asset_id}/maintenance",
    response_model=MaintenanceRecordResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MAINTAIN],
)
async def schedule_maintenance(
    asset_id: uuid.UUID,
    payload: MaintenanceRecordCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> MaintenanceRecordResponse:
    """Log or schedule maintenance, repair, or calibration."""
    res = await service.schedule_or_log_maintenance(session, org_id, asset_id, payload)
    await session.commit()
    return res


@router.patch(
    "/assets/{asset_id}/maintenance/{record_id}",
    response_model=MaintenanceRecordResponse,
    dependencies=[CAN_MAINTAIN],
)
async def complete_maintenance(
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    payload: MaintenanceRecordUpdate,
    session: DatabaseSession,
    org_id: OrgId,
) -> MaintenanceRecordResponse:
    """Mark a maintenance record completed and return the asset back to stock."""
    res = await service.complete_maintenance(session, org_id, asset_id, record_id, payload)
    await session.commit()
    return res


@router.get("/assets/{asset_id}/maintenance", response_model=list[MaintenanceRecordResponse], dependencies=[CAN_READ])
async def list_maintenance(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[MaintenanceRecordResponse]:
    """List all maintenance records for this asset."""
    return await service.list_maintenance(session, org_id, asset_id)


# --- Renewals ----------------------------------------------------------------


@router.post(
    "/assets/{asset_id}/renewals",
    response_model=AssetRenewalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_renewal(
    asset_id: uuid.UUID,
    payload: AssetRenewalCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetRenewalResponse:
    """Log a contract, warranty, or license renewal requirement."""
    res = await service.create_renewal(session, org_id, asset_id, payload)
    await session.commit()
    return res


@router.post(
    "/assets/{asset_id}/renewals/{renewal_id}/decide",
    response_model=AssetRenewalResponse,
    dependencies=[CAN_WRITE],
)
async def decide_renewal(
    asset_id: uuid.UUID,
    renewal_id: uuid.UUID,
    payload: AssetRenewalDecision,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
) -> AssetRenewalResponse:
    """Approve or reject a renewal decision and extend expiry dates."""
    res = await service.decide_renewal(session, org_id, asset_id, renewal_id, payload, actor.user_id)
    await session.commit()
    return res


@router.get("/assets/{asset_id}/renewals", response_model=list[AssetRenewalResponse], dependencies=[CAN_READ])
async def list_renewals(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[AssetRenewalResponse]:
    """List all renewal tracking records for this asset."""
    return await service.list_renewals(session, org_id, asset_id)


# --- Decommissioning & Disposal ----------------------------------------------


@router.post(
    "/assets/{asset_id}/dispose",
    response_model=AssetDisposalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_DISPOSE],
)
async def dispose_asset(
    asset_id: uuid.UUID,
    payload: AssetDisposalCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetDisposalResponse:
    """Decommission and dispose of an asset with data wiping verification."""
    res = await service.dispose_asset(session, org_id, asset_id, payload, if_match)
    await session.commit()
    return res


@router.get("/assets/{asset_id}/disposal", response_model=Optional[AssetDisposalResponse], dependencies=[CAN_READ])
async def get_disposal(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> Optional[AssetDisposalResponse]:
    """Get decommissioning and disposal details for an asset."""
    return await service.get_disposal(session, org_id, asset_id)


# --- Costs & Total Cost of Ownership (TCO) -----------------------------------


@router.post(
    "/assets/{asset_id}/costs",
    response_model=AssetCostResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def add_cost(
    asset_id: uuid.UUID,
    payload: AssetCostCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetCostResponse:
    """Add a cost entry (lease, repair, maintenance, license) to an asset."""
    res = await service.add_cost(session, org_id, asset_id, payload)
    await session.commit()
    return res


@router.get("/assets/{asset_id}/costs", response_model=tuple[list[AssetCostResponse], AssetCostSummary], dependencies=[CAN_READ])
async def get_costs(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> tuple[list[AssetCostResponse], AssetCostSummary]:
    """Retrieve cost ledger and Total Cost of Ownership (TCO) breakdown."""
    return await service.get_costs(session, org_id, asset_id)


# --- Relationships (Bundling & Dependencies) ---------------------------------


@router.post(
    "/assets/{asset_id}/relationships",
    response_model=AssetRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_relationship(
    asset_id: uuid.UUID,
    payload: AssetRelationshipCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetRelationshipResponse:
    """Link a child asset or dependency (parent_of, depends_on, installed_on)."""
    res = await service.create_relationship(session, org_id, asset_id, payload)
    await session.commit()
    return res


@router.get("/assets/{asset_id}/relationships", response_model=list[AssetRelationshipResponse], dependencies=[CAN_READ])
async def list_relationships(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[AssetRelationshipResponse]:
    """List topology relationships for an asset."""
    return await service.list_relationships(session, org_id, asset_id)
