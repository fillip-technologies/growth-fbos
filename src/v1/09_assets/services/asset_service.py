"""Business logic for the Assets service.

Simplifications:
- asset_tag is auto-generated as {TYPE_PREFIX}-{seq} where prefix is the first
  3 chars of the type code uppercased. A production implementation would use a
  proper sequence table.
- Credential reveal returns a placeholder value; a real implementation would
  call a secrets manager (Vault, AWS Secrets Manager, etc.) via secret_ref.
- If-Match / ETag concurrency is enforced: version must match.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssetAlreadyAssignedError,
    AssetNotFoundError,
    AssetTypeNotFoundError,
    CredentialNotFoundError,
    InvalidStateTransitionError,
    PreconditionRequiredError,
    VendorAccountNotFoundError,
    VersionConflictError,
)
from models.asset import Asset, AssetAssignment, AssetCategory, AssetType, Credential, Vendor, VendorAccount
from schemas.assets import (
    AssetAssignmentCreate,
    AssetCreate,
    AssetResponse,
    AssetReturn,
    CredentialReveal,
    CredentialSecretResponse,
)
from schemas.common import CustodianRef, PageResponse, TypeRef, UnitRef, VendorAccountRef
from services.pagination import paginate_by_id


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------


async def _build_asset_response(session: AsyncSession, asset: Asset) -> AssetResponse:
    asset_type = await session.get(AssetType, asset.asset_type_id)
    type_ref = TypeRef(
        code=asset_type.code if asset_type else "",
        name=asset_type.name if asset_type else "",
        family=asset_type.family if asset_type else "digital",
    )

    owner_unit = UnitRef(id=asset.owner_unit_id, name="Org Unit") if asset.owner_unit_id else None

    # Active assignment → custodian
    custodian = None
    if asset.custodian_user_id:
        custodian = CustodianRef(id=asset.custodian_user_id, name="Custodian")

    # Vendor account
    vendor_account_ref = None
    if asset.vendor_account_id:
        va = await session.get(VendorAccount, asset.vendor_account_id)
        if va:
            vendor = await session.get(Vendor, va.vendor_id)
            vendor_account_ref = VendorAccountRef(
                id=va.id,
                vendor=vendor.name if vendor else "",
                account=va.account_identifier,
            )

    return AssetResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        type=type_ref,
        status=asset.status,
        criticality=asset.criticality,
        owner_unit=owner_unit,
        custodian=custodian,
        vendor_account=vendor_account_ref,
        expires_at=asset.expires_at,
        renewal_due_on=asset.renewal_due_on,
        auto_renew=asset.auto_renew,
        attributes=asset.attributes or {},
        version=asset.version,
    )


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


async def _get_asset(session: AsyncSession, org_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    res = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.organization_id == org_id)
    )
    asset = res.scalars().first()
    if not asset:
        raise AssetNotFoundError(str(asset_id))
    return asset


async def _generate_asset_tag(session: AsyncSession, org_id: uuid.UUID, type_code: str) -> str:
    prefix = type_code[:3].upper()
    res = await session.execute(select(Asset).where(Asset.organization_id == org_id))
    count = len(res.scalars().all())
    return f"{prefix}-{count + 1:04d}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _asset_type_by_code(org_id: uuid.UUID, type_code: str) -> Select:
    # Asset types carry no organization_id; they belong to a tenant through their category.
    return (
        select(AssetType)
        .join(AssetCategory, AssetType.category_id == AssetCategory.id)
        .where(AssetCategory.organization_id == org_id, AssetType.code == type_code)
    )


async def list_assets(
    session: AsyncSession,
    org_id: uuid.UUID,
    type_code: Optional[str],
    status: Optional[str],
    expiring_within_days: Optional[int],
    owner_unit_id: Optional[uuid.UUID],
    custodian_user_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[AssetResponse]:
    query = select(Asset).where(Asset.organization_id == org_id)
    if type_code is not None:
        type_res = await session.execute(_asset_type_by_code(org_id, type_code))
        at = type_res.scalars().first()
        if at:
            query = query.where(Asset.asset_type_id == at.id)
    if status is not None:
        query = query.where(Asset.status == status)
    if owner_unit_id is not None:
        query = query.where(Asset.owner_unit_id == owner_unit_id)
    if custodian_user_id is not None:
        query = query.where(Asset.custodian_user_id == custodian_user_id)
    if expiring_within_days is not None:
        from datetime import date, timedelta
        cutoff = date.today() + timedelta(days=expiring_within_days)
        query = query.where(Asset.expires_at <= cutoff, Asset.expires_at.isnot(None))

    rows, page = await paginate_by_id(session, query, Asset, limit, cursor)
    data = [await _build_asset_response(session, a) for a in rows]
    return PageResponse(data=data, page=page)


async def register_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: AssetCreate,
) -> AssetResponse:
    type_res = await session.execute(_asset_type_by_code(org_id, data.type_code))
    asset_type = type_res.scalars().first()
    if not asset_type:
        raise AssetTypeNotFoundError(data.type_code)

    if data.vendor_account_id is not None:
        va = await session.get(VendorAccount, data.vendor_account_id)
        if not va:
            raise VendorAccountNotFoundError(str(data.vendor_account_id))

    asset_tag = await _generate_asset_tag(session, org_id, data.type_code)

    asset = Asset(
        organization_id=org_id,
        asset_tag=asset_tag,
        name=data.name,
        asset_type_id=asset_type.id,
        owner_unit_id=data.owner_unit_id,
        criticality=data.criticality,
        vendor_account_id=data.vendor_account_id,
        expires_at=data.expires_at,
        auto_renew=data.auto_renew,
        acquisition_cost=float(data.acquisition_cost.amount) if data.acquisition_cost else None,
        currency=data.acquisition_cost.currency if data.acquisition_cost else "INR",
        attributes=data.attributes or {},
        status="active",
        version=1,
    )
    # Set renewal_due_on 30 days before expiry when expires_at is set
    if data.expires_at:
        from datetime import timedelta
        asset.renewal_due_on = data.expires_at - timedelta(days=30)

    session.add(asset)
    await session.flush()
    return await _build_asset_response(session, asset)


async def get_asset(
    session: AsyncSession, org_id: uuid.UUID, asset_id: uuid.UUID
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    return await _build_asset_response(session, asset)


async def assign_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetAssignmentCreate,
    if_match: Optional[str],
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    # Check no active assignment exists
    active_res = await session.execute(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.returned_at.is_(None),
        )
    )
    if active_res.scalars().first():
        raise AssetAlreadyAssignedError(str(asset.custodian_user_id))

    now = datetime.now(timezone.utc)
    assignment = AssetAssignment(
        asset_id=asset_id,
        assignee_type=data.assignee_type,
        assignee_id=data.assignee_id,
        assigned_at=now,
        condition_out=data.condition_out,
    )
    session.add(assignment)

    asset.status = "assigned"
    asset.custodian_user_id = data.assignee_id if data.assignee_type == "user" else None
    asset.version += 1
    await session.flush()
    return await _build_asset_response(session, asset)


async def return_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetReturn,
    if_match: Optional[str],
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    if asset.status != "assigned":
        raise InvalidStateTransitionError(asset.status, "return")

    active_res = await session.execute(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.returned_at.is_(None),
        )
    )
    assignment = active_res.scalars().first()
    if assignment:
        assignment.returned_at = datetime.now(timezone.utc)
        assignment.condition_in = data.condition_in

    asset.status = "in_stock"
    asset.custodian_user_id = None
    asset.version += 1
    await session.flush()
    return await _build_asset_response(session, asset)


async def reveal_credential(
    session: AsyncSession,
    org_id: uuid.UUID,
    credential_id: uuid.UUID,
    data: CredentialReveal,
) -> CredentialSecretResponse:
    res = await session.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.organization_id == org_id,
        )
    )
    credential = res.scalars().first()
    if not credential:
        raise CredentialNotFoundError(str(credential_id))

    # In production: fetch from secrets manager via credential.secret_ref
    # The value is never stored in the DB — placeholder here
    now = datetime.now(timezone.utc)
    return CredentialSecretResponse(
        value="••••••••••••",
        expires_in=60,
        revealed_at=now,
    )
