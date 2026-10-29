import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateVendorCodeError,
    VendorAccountNotFoundError,
    VendorNotFoundError,
)
from models.asset import Vendor, VendorAccount
from schemas.common import PageResponse
from schemas.vendors import (
    VendorAccountCreate,
    VendorAccountResponse,
    VendorAccountUpdate,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
)
from services.codes import next_vendor_code
from services.pagination import paginate


# --- Vendors -----------------------------------------------------------------


async def list_vendors(
    session: AsyncSession,
    org_id: uuid.UUID,
    vendor_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> PageResponse[VendorResponse]:
    query = select(Vendor).where(Vendor.organization_id == org_id)
    if vendor_type is not None:
        query = query.where(Vendor.vendor_type == vendor_type)
    if status is not None:
        query = query.where(Vendor.status == status)

    rows, page = await paginate(session, query, Vendor, limit, cursor, order_by=Vendor.name)
    data = [VendorResponse.model_validate(row) for row in rows]
    return PageResponse(data=data, page=page)


async def get_vendor(session: AsyncSession, org_id: uuid.UUID, vendor_id: uuid.UUID) -> VendorResponse:
    res = await session.execute(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.organization_id == org_id)
    )
    v = res.scalars().first()
    if not v:
        raise VendorNotFoundError(str(vendor_id))
    return VendorResponse.model_validate(v)


async def create_vendor(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: VendorCreate,
) -> VendorResponse:
    code = data.code
    if not code:
        code = await next_vendor_code(session, org_id)
    else:
        existing = await session.execute(
            select(Vendor).where(Vendor.organization_id == org_id, Vendor.code == code)
        )
        if existing.scalars().first():
            raise DuplicateVendorCodeError(code)

    vendor = Vendor(
        id=uuid.uuid4(),
        organization_id=org_id,
        code=code,
        name=data.name,
        vendor_type=data.vendor_type,
        gstin=data.gstin,
        status="active",
    )
    session.add(vendor)
    await session.flush()
    return VendorResponse.model_validate(vendor)


async def update_vendor(
    session: AsyncSession,
    org_id: uuid.UUID,
    vendor_id: uuid.UUID,
    data: VendorUpdate,
) -> VendorResponse:
    res = await session.execute(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.organization_id == org_id)
    )
    v = res.scalars().first()
    if not v:
        raise VendorNotFoundError(str(vendor_id))

    if data.name is not None:
        v.name = data.name
    if data.vendor_type is not None:
        v.vendor_type = data.vendor_type
    if data.gstin is not None:
        v.gstin = data.gstin
    if data.status is not None:
        v.status = data.status

    await session.flush()
    return VendorResponse.model_validate(v)


# --- Vendor Accounts ---------------------------------------------------------


async def list_vendor_accounts(
    session: AsyncSession,
    org_id: uuid.UUID,
    vendor_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> PageResponse[VendorAccountResponse]:
    query = (
        select(VendorAccount)
        .join(Vendor, VendorAccount.vendor_id == Vendor.id)
        .where(Vendor.organization_id == org_id)
    )
    if vendor_id is not None:
        query = query.where(VendorAccount.vendor_id == vendor_id)
    if status is not None:
        query = query.where(VendorAccount.status == status)

    rows, page = await paginate(session, query, VendorAccount, limit, cursor, order_by=VendorAccount.account_identifier)
    data = [VendorAccountResponse.model_validate(row) for row in rows]
    return PageResponse(data=data, page=page)


async def get_vendor_account(
    session: AsyncSession,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
) -> VendorAccountResponse:
    query = (
        select(VendorAccount)
        .join(Vendor, VendorAccount.vendor_id == Vendor.id)
        .where(VendorAccount.id == account_id, Vendor.organization_id == org_id)
    )
    res = await session.execute(query)
    va = res.scalars().first()
    if not va:
        raise VendorAccountNotFoundError(str(account_id))
    return VendorAccountResponse.model_validate(va)


async def create_vendor_account(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: VendorAccountCreate,
) -> VendorAccountResponse:
    # Ensure vendor belongs to org
    vendor_res = await session.execute(
        select(Vendor).where(Vendor.id == data.vendor_id, Vendor.organization_id == org_id)
    )
    if not vendor_res.scalars().first():
        raise VendorNotFoundError(str(data.vendor_id))

    va = VendorAccount(
        id=uuid.uuid4(),
        vendor_id=data.vendor_id,
        account_identifier=data.account_identifier,
        owner_user_id=data.owner_user_id,
        billing_email=data.billing_email,
        status="active",
    )
    session.add(va)
    await session.flush()
    return VendorAccountResponse.model_validate(va)


async def update_vendor_account(
    session: AsyncSession,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
    data: VendorAccountUpdate,
) -> VendorAccountResponse:
    query = (
        select(VendorAccount)
        .join(Vendor, VendorAccount.vendor_id == Vendor.id)
        .where(VendorAccount.id == account_id, Vendor.organization_id == org_id)
    )
    res = await session.execute(query)
    va = res.scalars().first()
    if not va:
        raise VendorAccountNotFoundError(str(account_id))

    if data.account_identifier is not None:
        va.account_identifier = data.account_identifier
    if data.owner_user_id is not None:
        va.owner_user_id = data.owner_user_id
    if data.billing_email is not None:
        va.billing_email = data.billing_email
    if data.status is not None:
        va.status = data.status

    await session.flush()
    return VendorAccountResponse.model_validate(va)
