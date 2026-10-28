import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.asset_service as service
from dependencies import CurrentActor, DatabaseSession, OrgId, UserId, require_permission
from schemas.assets import (
    AssetAssignmentCreate,
    AssetAssignmentResponse,
    AssetCreate,
    AssetResponse,
    AssetReturn,
    AssetTransferCreate,
    AssetUpdate,
    CredentialReveal,
    CredentialSecretResponse,
)
from schemas.common import PageResponse

router = APIRouter(tags=["assets"])

CAN_READ = Depends(require_permission(permissions.ASSET_READ))
CAN_WRITE = Depends(require_permission(permissions.ASSET_WRITE))
CAN_ASSIGN = Depends(require_permission(permissions.ASSET_ASSIGN))
CAN_REVEAL = Depends(require_permission(permissions.CREDENTIAL_REVEAL))


# --- Assets ------------------------------------------------------------------


@router.get("/assets", response_model=PageResponse[AssetResponse], dependencies=[CAN_READ])
async def list_assets(
    session: DatabaseSession,
    org_id: OrgId,
    type_code: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    owner_unit_id: Optional[uuid.UUID] = Query(None),
    custodian_user_id: Optional[uuid.UUID] = Query(None),
    expiring_within_days: Optional[int] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[AssetResponse]:
    """List assets with flexible multi-axis filtering."""
    return await service.list_assets(
        session,
        org_id,
        type_code,
        status_,
        owner_unit_id,
        custodian_user_id,
        expiring_within_days,
        limit,
        cursor,
    )


@router.post(
    "/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def register_asset(
    payload: AssetCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> AssetResponse:
    """Register a new asset with auto-generated tag."""
    asset = await service.register_asset(session, org_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.get("/assets/clearance/employee/{user_id}", response_model=list[AssetResponse], dependencies=[CAN_READ])
async def get_employee_clearance(
    user_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[AssetResponse]:
    """Return all active assets held by employee for offboarding clearance."""
    return await service.get_employee_clearance(session, org_id, user_id)


@router.get("/assets/{asset_id}", response_model=AssetResponse, dependencies=[CAN_READ])
async def get_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> AssetResponse:
    """Get an asset by ID."""
    asset = await service.get_asset(session, org_id, asset_id)
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.patch("/assets/{asset_id}", response_model=AssetResponse, dependencies=[CAN_WRITE])
async def update_asset(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Update asset specifications with optimistic concurrency locking."""
    asset = await service.update_asset(session, org_id, asset_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


# --- Custody & Handover Operations -------------------------------------------


@router.post(
    "/assets/{asset_id}/assignments",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_ASSIGN],
)
async def assign_asset(
    asset_id: uuid.UUID,
    payload: AssetAssignmentCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Assign an asset to an Employee, Department, Branch, or Project."""
    asset = await service.assign_asset(session, org_id, asset_id, payload, actor.user_id, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.post("/assets/{asset_id}/transfer", response_model=AssetResponse, dependencies=[CAN_ASSIGN])
async def transfer_asset(
    asset_id: uuid.UUID,
    payload: AssetTransferCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Directly transfer asset custody to a new employee, department, or branch."""
    asset = await service.transfer_asset(session, org_id, asset_id, payload, actor.user_id, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.post("/assets/{asset_id}/return", response_model=AssetResponse, dependencies=[CAN_ASSIGN])
async def return_asset(
    asset_id: uuid.UUID,
    payload: AssetReturn,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Return an assigned asset back to stock."""
    asset = await service.return_asset(session, org_id, asset_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.get("/assets/{asset_id}/history", response_model=list[AssetAssignmentResponse], dependencies=[CAN_READ])
async def get_asset_history(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[AssetAssignmentResponse]:
    """Retrieve full chronological custody and handover audit history."""
    return await service.get_asset_history(session, org_id, asset_id)


# --- Credentials -------------------------------------------------------------


@router.post("/credentials/{credential_id}/reveal", response_model=CredentialSecretResponse, dependencies=[CAN_REVEAL])
async def reveal_credential(
    credential_id: uuid.UUID,
    payload: CredentialReveal,
    session: DatabaseSession,
    org_id: OrgId,
) -> CredentialSecretResponse:
    """Reveal a stored credential."""
    return await service.reveal_credential(session, org_id, credential_id, payload)
