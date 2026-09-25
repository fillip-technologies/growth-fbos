import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

import services.asset_service as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.assets import (
    AssetAssignmentCreate,
    AssetCreate,
    AssetResponse,
    AssetReturn,
    CredentialReveal,
    CredentialSecretResponse,
)
from schemas.common import PageResponse

router = APIRouter(tags=["assets"])


# --- Assets ------------------------------------------------------------------


@router.get("/assets", response_model=PageResponse[AssetResponse])
async def list_assets(
    session: DatabaseSession,
    org_id: OrgId,
    type_code: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    expiring_within_days: Optional[int] = Query(None),
    owner_unit_id: Optional[uuid.UUID] = Query(None),
    custodian_user_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[AssetResponse]:
    """List assets."""
    return await service.list_assets(
        session, org_id, type_code, status_, expiring_within_days, owner_unit_id, custodian_user_id, limit, cursor
    )


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def register_asset(
    payload: AssetCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> AssetResponse:
    """Register an asset."""
    asset = await service.register_asset(session, org_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> AssetResponse:
    """Get an asset."""
    asset = await service.get_asset(session, org_id, asset_id)
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.post(
    "/assets/{asset_id}/assignments",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_asset(
    asset_id: uuid.UUID,
    payload: AssetAssignmentCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Assign an asset."""
    asset = await service.assign_asset(session, org_id, asset_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


@router.post("/assets/{asset_id}/return", response_model=AssetResponse)
async def return_asset(
    asset_id: uuid.UUID,
    payload: AssetReturn,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssetResponse:
    """Return an assigned asset."""
    asset = await service.return_asset(session, org_id, asset_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{asset.version}"'
    return asset


# --- Credentials -------------------------------------------------------------


@router.post("/credentials/{credential_id}/reveal", response_model=CredentialSecretResponse)
async def reveal_credential(
    credential_id: uuid.UUID,
    payload: CredentialReveal,
    session: DatabaseSession,
    org_id: OrgId,
    x_mfa_code: Optional[str] = Header(None, alias="X-MFA-Code"),
) -> CredentialSecretResponse:
    """Reveal a stored credential."""
    return await service.reveal_credential(session, org_id, credential_id, payload)
