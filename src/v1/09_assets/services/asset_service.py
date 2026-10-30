"""Business logic for the Assets service.

Enforces:
- Optimistic locking: `If-Match` with ETag version verification.
- Atomic tag numbering: `AST-{year}-{0001}` generated via CodeSequence.
- Multi-axis association: Financial owner (unit), physical location (branch), operational custody (user/unit/project).
- Immutable chain of custody: Every handover logs an AssetAssignment row.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import Select, and_, false, select
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
from models.asset import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetType,
    Credential,
    Vendor,
    VendorAccount,
)
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
from schemas.common import (
    CustodianRef,
    Money,
    PageResponse,
    SubjectRef,
    TypeRef,
    UnitRef,
    VendorAccountRef,
)
from services.codes import next_asset_tag
from services.pagination import paginate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _require_vendor_account(session: AsyncSession, org_id: uuid.UUID, vendor_account_id: uuid.UUID) -> VendorAccount:
    """A vendor account belongs to the organization through its vendor."""
    res = await session.execute(
        select(VendorAccount)
        .join(Vendor, VendorAccount.vendor_id == Vendor.id)
        .where(VendorAccount.id == vendor_account_id, Vendor.organization_id == org_id)
    )
    account = res.scalars().first()
    if not account:
        raise VendorAccountNotFoundError(str(vendor_account_id))
    return account


async def _asset_type_by_code(session: AsyncSession, org_id: uuid.UUID, type_code: str) -> Optional[AssetType]:
    res = await session.execute(
        select(AssetType)
        .join(AssetCategory, AssetType.category_id == AssetCategory.id)
        .where(AssetCategory.organization_id == org_id, AssetType.code == type_code)
    )
    return res.scalars().first()


async def _active_assignment(session: AsyncSession, asset_id: uuid.UUID) -> Optional[AssetAssignment]:
    res = await session.execute(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.returned_at.is_(None),
        )
    )
    return res.scalars().first()


async def _build_asset_response(session: AsyncSession, asset: Asset) -> AssetResponse:
    asset_type = await session.get(AssetType, asset.asset_type_id)
    type_ref = TypeRef(
        code=asset_type.code if asset_type else "",
        name=asset_type.name if asset_type else "",
        family=asset_type.family if asset_type else "hardware",
    )

    owner_unit = UnitRef(id=asset.owner_unit_id, name="") if asset.owner_unit_id else None

    # Location from attributes
    attrs = asset.attributes or {}
    loc_branch_id_str = attrs.get("location_branch_id")
    loc_branch_id = uuid.UUID(loc_branch_id_str) if loc_branch_id_str else None
    loc_details = attrs.get("location_details")

    # Custody / active assignment
    active_asg = await _active_assignment(session, asset.id)
    custody_ref = None
    if active_asg:
        custody_ref = SubjectRef(
            type=active_asg.assignee_type,
            id=active_asg.assignee_id,
            label=None,
        )

    # Custodian human
    custodian = None
    if asset.custodian_user_id:
        custodian = CustodianRef(id=asset.custodian_user_id, name="")

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

    cost = None
    if asset.acquisition_cost is not None:
        cost = Money(amount=float(asset.acquisition_cost), currency=asset.currency or "INR")

    return AssetResponse(
        id=asset.id,
        asset_tag=asset.asset_tag,
        name=asset.name,
        type=type_ref,
        status=asset.status,
        criticality=asset.criticality,
        owner_unit=owner_unit,
        location_branch_id=loc_branch_id,
        location_details=loc_details,
        custody=custody_ref,
        custodian=custodian,
        vendor_account=vendor_account_ref,
        serial_no=asset.serial_no,
        acquired_on=asset.acquired_on,
        acquisition_cost=cost,
        expires_at=asset.expires_at,
        renewal_due_on=asset.renewal_due_on,
        auto_renew=asset.auto_renew,
        attributes=attrs,
        version=asset.version,
    )


# ---------------------------------------------------------------------------
# Asset CRUD
# ---------------------------------------------------------------------------


async def list_assets(
    session: AsyncSession,
    org_id: uuid.UUID,
    type_code: Optional[str] = None,
    status: Optional[str] = None,
    owner_unit_id: Optional[uuid.UUID] = None,
    custodian_user_id: Optional[uuid.UUID] = None,
    expiring_within_days: Optional[int] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> PageResponse[AssetResponse]:
    query = select(Asset).where(Asset.organization_id == org_id)

    if type_code is not None:
        at = await _asset_type_by_code(session, org_id, type_code)
        # An unknown type matches nothing rather than silently listing every asset.
        query = query.where(Asset.asset_type_id == at.id) if at else query.where(false())
    if status is not None:
        query = query.where(Asset.status == status)
    if owner_unit_id is not None:
        query = query.where(Asset.owner_unit_id == owner_unit_id)
    if custodian_user_id is not None:
        query = query.where(Asset.custodian_user_id == custodian_user_id)
    if expiring_within_days is not None:
        cutoff = date.today() + timedelta(days=expiring_within_days)
        query = query.where(Asset.expires_at <= cutoff, Asset.expires_at.isnot(None))

    rows, page = await paginate(session, query, Asset, limit, cursor, order_by=Asset.asset_tag)
    data = [await _build_asset_response(session, a) for a in rows]
    return PageResponse(data=data, page=page)


async def register_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: AssetCreate,
) -> AssetResponse:
    asset_type = await _asset_type_by_code(session, org_id, data.type_code)
    if not asset_type:
        raise AssetTypeNotFoundError(data.type_code)

    if data.vendor_account_id is not None:
        await _require_vendor_account(session, org_id, data.vendor_account_id)

    prefix = data.type_code[:3].upper()
    asset_tag = await next_asset_tag(session, org_id, prefix)

    attrs = data.attributes.copy() if data.attributes else {}
    if data.location_branch_id:
        attrs["location_branch_id"] = str(data.location_branch_id)
    if data.location_details:
        attrs["location_details"] = data.location_details

    cost_val = float(data.acquisition_cost.amount) if data.acquisition_cost else None
    currency_val = data.acquisition_cost.currency if data.acquisition_cost else "INR"

    asset = Asset(
        id=uuid.uuid4(),
        organization_id=org_id,
        asset_tag=asset_tag,
        name=data.name,
        asset_type_id=asset_type.id,
        owner_unit_id=data.owner_unit_id,
        criticality=data.criticality,
        serial_no=data.serial_no,
        vendor_account_id=data.vendor_account_id,
        acquired_on=data.acquired_on or date.today(),
        acquisition_cost=cost_val,
        currency=currency_val,
        expires_at=data.expires_at,
        auto_renew=data.auto_renew,
        attributes=attrs,
        status="in_stock",
        version=1,
    )
    if data.expires_at:
        asset.renewal_due_on = data.expires_at - timedelta(days=30)

    session.add(asset)
    await session.flush()
    return await _build_asset_response(session, asset)


async def get_asset(session: AsyncSession, org_id: uuid.UUID, asset_id: uuid.UUID) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    return await _build_asset_response(session, asset)


async def update_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetUpdate,
    if_match: Optional[str],
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    if data.name is not None:
        asset.name = data.name
    if data.owner_unit_id is not None:
        asset.owner_unit_id = data.owner_unit_id
    if data.criticality is not None:
        asset.criticality = data.criticality
    if data.serial_no is not None:
        asset.serial_no = data.serial_no
    if data.vendor_account_id is not None:
        await _require_vendor_account(session, org_id, data.vendor_account_id)
        asset.vendor_account_id = data.vendor_account_id
    if data.expires_at is not None:
        asset.expires_at = data.expires_at
        asset.renewal_due_on = data.expires_at - timedelta(days=30)
    if data.auto_renew is not None:
        asset.auto_renew = data.auto_renew

    attrs = asset.attributes.copy() if asset.attributes else {}
    if data.location_branch_id is not None:
        attrs["location_branch_id"] = str(data.location_branch_id)
    if data.location_details is not None:
        attrs["location_details"] = data.location_details
    if data.attributes:
        attrs.update(data.attributes)
    asset.attributes = attrs

    asset.version += 1
    await session.flush()
    return await _build_asset_response(session, asset)


# ---------------------------------------------------------------------------
# Custody Workflows (Assign, Transfer, Return, History)
# ---------------------------------------------------------------------------


async def assign_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetAssignmentCreate,
    assigned_by: Optional[uuid.UUID],
    if_match: Optional[str],
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    if asset.status not in ("in_stock", "reserved"):
        raise InvalidStateTransitionError(asset.status, "assign")

    active = await _active_assignment(session, asset_id)
    if active:
        raise AssetAlreadyAssignedError(str(asset.custodian_user_id))

    custodian_id = data.custodian_user_id
    if not custodian_id and data.assignee_type in ("identity.user", "user"):
        custodian_id = data.assignee_id

    assignment = AssetAssignment(
        id=uuid.uuid4(),
        asset_id=asset_id,
        assignee_type=data.assignee_type,
        assignee_id=data.assignee_id,
        assigned_at=datetime.now(timezone.utc),
        condition_out=data.condition_out,
        assigned_by=assigned_by,
    )
    session.add(assignment)

    asset.status = "in_use"
    asset.custodian_user_id = custodian_id
    asset.version += 1
    await session.flush()
    return await _build_asset_response(session, asset)


async def transfer_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetTransferCreate,
    transferred_by: Optional[uuid.UUID],
    if_match: Optional[str],
) -> AssetResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    if asset.status != "in_use":
        raise InvalidStateTransitionError(asset.status, "transfer")

    now = datetime.now(timezone.utc)

    # Close current active assignment
    active = await _active_assignment(session, asset_id)
    if active:
        active.returned_at = now
        active.condition_in = data.condition_transfer

    # Open new assignment
    new_custodian_id = data.to_custodian_user_id
    if not new_custodian_id and data.to_assignee_type in ("identity.user", "user"):
        new_custodian_id = data.to_assignee_id

    new_assignment = AssetAssignment(
        id=uuid.uuid4(),
        asset_id=asset_id,
        assignee_type=data.to_assignee_type,
        assignee_id=data.to_assignee_id,
        assigned_at=now,
        condition_out=data.condition_transfer,
        assigned_by=transferred_by,
    )
    session.add(new_assignment)

    asset.custodian_user_id = new_custodian_id
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

    if asset.status != "in_use":
        raise InvalidStateTransitionError(asset.status, "return")

    active = await _active_assignment(session, asset_id)
    if active:
        active.returned_at = datetime.now(timezone.utc)
        active.condition_in = data.condition_in

    asset.status = "in_stock"
    asset.custodian_user_id = None
    asset.version += 1
    await session.flush()
    return await _build_asset_response(session, asset)


async def get_asset_history(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> list[AssetAssignmentResponse]:
    await _get_asset(session, org_id, asset_id)
    res = await session.execute(
        select(AssetAssignment)
        .where(AssetAssignment.asset_id == asset_id)
        .order_by(AssetAssignment.assigned_at.desc())
    )
    rows = res.scalars().all()
    return [
        AssetAssignmentResponse(
            id=row.id,
            asset_id=row.asset_id,
            assignee=SubjectRef(type=row.assignee_type, id=row.assignee_id),
            assigned_at=row.assigned_at,
            returned_at=row.returned_at,
            condition_out=row.condition_out,
            condition_in=row.condition_in,
            assigned_by=row.assigned_by,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Operational Audits & Clearance
# ---------------------------------------------------------------------------


async def get_employee_clearance(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[AssetResponse]:
    """Returns all assets currently in custody of this employee."""
    res = await session.execute(
        select(Asset).where(
            Asset.organization_id == org_id,
            Asset.custodian_user_id == user_id,
            Asset.status == "in_use",
        )
    )
    assets = res.scalars().all()
    return [await _build_asset_response(session, a) for a in assets]


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

    return CredentialSecretResponse(
        value="••••••••••••",
        expires_in=60,
        revealed_at=datetime.now(timezone.utc),
    )
