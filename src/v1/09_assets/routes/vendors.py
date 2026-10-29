import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

import permissions
import services.vendor_service as service
from dependencies import DatabaseSession, OrgId, require_permission
from schemas.common import PageResponse
from schemas.vendors import (
    VendorAccountCreate,
    VendorAccountResponse,
    VendorAccountUpdate,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
)

router = APIRouter(tags=["vendors"])

CAN_READ = Depends(require_permission(permissions.ASSET_READ))
CAN_MANAGE_SETUP = Depends(require_permission(permissions.SETUP_MANAGE))


# --- Vendors -----------------------------------------------------------------


@router.get("/vendors", response_model=PageResponse[VendorResponse], dependencies=[CAN_READ])
async def list_vendors(
    session: DatabaseSession,
    org_id: OrgId,
    vendor_type: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[VendorResponse]:
    """List vendors."""
    return await service.list_vendors(session, org_id, vendor_type, status_, limit, cursor)


@router.post(
    "/vendors",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_SETUP],
)
async def create_vendor(
    payload: VendorCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorResponse:
    """Create a vendor."""
    v = await service.create_vendor(session, org_id, payload)
    await session.commit()
    return v


@router.get("/vendors/{vendor_id}", response_model=VendorResponse, dependencies=[CAN_READ])
async def get_vendor(
    vendor_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorResponse:
    """Get a vendor."""
    return await service.get_vendor(session, org_id, vendor_id)


@router.patch("/vendors/{vendor_id}", response_model=VendorResponse, dependencies=[CAN_MANAGE_SETUP])
async def update_vendor(
    vendor_id: uuid.UUID,
    payload: VendorUpdate,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorResponse:
    """Update a vendor."""
    v = await service.update_vendor(session, org_id, vendor_id, payload)
    await session.commit()
    return v


# --- Vendor Accounts ---------------------------------------------------------


@router.get("/vendor-accounts", response_model=PageResponse[VendorAccountResponse], dependencies=[CAN_READ])
async def list_vendor_accounts(
    session: DatabaseSession,
    org_id: OrgId,
    vendor_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[VendorAccountResponse]:
    """List vendor accounts."""
    return await service.list_vendor_accounts(session, org_id, vendor_id, status_, limit, cursor)


@router.post(
    "/vendor-accounts",
    response_model=VendorAccountResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_SETUP],
)
async def create_vendor_account(
    payload: VendorAccountCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorAccountResponse:
    """Create a vendor account."""
    va = await service.create_vendor_account(session, org_id, payload)
    await session.commit()
    return va


@router.get("/vendor-accounts/{account_id}", response_model=VendorAccountResponse, dependencies=[CAN_READ])
async def get_vendor_account(
    account_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorAccountResponse:
    """Get a vendor account."""
    return await service.get_vendor_account(session, org_id, account_id)


@router.patch("/vendor-accounts/{account_id}", response_model=VendorAccountResponse, dependencies=[CAN_MANAGE_SETUP])
async def update_vendor_account(
    account_id: uuid.UUID,
    payload: VendorAccountUpdate,
    session: DatabaseSession,
    org_id: OrgId,
) -> VendorAccountResponse:
    """Update a vendor account."""
    va = await service.update_vendor_account(session, org_id, account_id, payload)
    await session.commit()
    return va
