"""Lifecycle management business logic for enterprise assets:

- Maintenance & Repair logs with automated state transition (in_maintenance <-> in_stock)
- Warranty & Contract renewals with decision tracking and expiry extension
- Decommissioning & Disposal with data wiping verification and certificate link
- Total Cost of Ownership (TCO) tracking (acquisition, repairs, leases)
- Topology relationships (parent-child bundles, dependencies)
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssetNotFoundError,
    InvalidStateTransitionError,
    PreconditionRequiredError,
    ValidationFailedError,
    VersionConflictError,
)
from models.asset import (
    Asset,
    AssetCost,
    AssetDisposal,
    AssetRelationship,
    AssetRenewal,
    MaintenanceRecord,
)
from schemas.common import Money
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


# --- Maintenance & Repairs ---------------------------------------------------


async def schedule_or_log_maintenance(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: MaintenanceRecordCreate,
) -> MaintenanceRecordResponse:
    asset = await _get_asset(session, org_id, asset_id)
    if asset.status in ("disposed", "in_use"):
        raise InvalidStateTransitionError(asset.status, "maintain (return the asset from custody first)" if asset.status == "in_use" else "maintain")

    cost_val = float(data.cost.amount) if data.cost else None

    record = MaintenanceRecord(
        id=uuid.uuid4(),
        asset_id=asset_id,
        maintenance_type=data.maintenance_type,
        vendor_id=data.vendor_id,
        scheduled_on=data.scheduled_on,
        completed_on=data.completed_on,
        cost=cost_val,
        task_id=data.task_id,
        notes=data.notes,
    )
    session.add(record)

    # If maintenance is currently active (not yet completed), mark asset in maintenance
    if data.completed_on is None:
        asset.status = "in_maintenance"
        asset.version += 1
    elif cost_val:
        # If already completed with cost, log cost record
        cost_entry = AssetCost(
            id=uuid.uuid4(),
            asset_id=asset_id,
            cost_type="maintenance",
            amount=cost_val,
            currency=asset.currency or "INR",
            period_start=data.completed_on,
            period_end=data.completed_on,
            vendor_invoice_ref=None,
        )
        session.add(cost_entry)

    await session.flush()
    return _build_maintenance_response(record, asset.currency)


async def complete_maintenance(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    data: MaintenanceRecordUpdate,
) -> MaintenanceRecordResponse:
    asset = await _get_asset(session, org_id, asset_id)

    res = await session.execute(
        select(MaintenanceRecord).where(
            MaintenanceRecord.id == record_id,
            MaintenanceRecord.asset_id == asset_id,
        )
    )
    record = res.scalars().first()
    if not record:
        raise AssetNotFoundError(f"Maintenance record {record_id} not found")
    if record.completed_on is not None:
        raise InvalidStateTransitionError("completed", "complete maintenance")

    completed_date = data.completed_on or date.today()
    record.completed_on = completed_date

    if data.cost is not None:
        cost_val = float(data.cost.amount)
        record.cost = cost_val
        cost_entry = AssetCost(
            id=uuid.uuid4(),
            asset_id=asset_id,
            cost_type="maintenance",
            amount=cost_val,
            currency=asset.currency or "INR",
            period_start=completed_date,
            period_end=completed_date,
        )
        session.add(cost_entry)

    if data.notes:
        record.notes = (record.notes + "\n" + data.notes) if record.notes else data.notes

    # Back to stock only when nothing else is still open and the asset wasn't moved on meanwhile.
    await session.flush()
    still_open = await session.execute(
        select(func.count(MaintenanceRecord.id)).where(
            MaintenanceRecord.asset_id == asset_id,
            MaintenanceRecord.completed_on.is_(None),
        )
    )
    if asset.status == "in_maintenance" and still_open.scalar_one() == 0:
        asset.status = "in_stock"
    asset.version += 1

    await session.flush()
    return _build_maintenance_response(record, asset.currency)


async def list_maintenance(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> list[MaintenanceRecordResponse]:
    asset = await _get_asset(session, org_id, asset_id)
    res = await session.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.asset_id == asset_id)
        .order_by(MaintenanceRecord.scheduled_on.desc())
    )
    rows = res.scalars().all()
    return [_build_maintenance_response(r, asset.currency) for r in rows]


def _build_maintenance_response(r: MaintenanceRecord, currency: Optional[str]) -> MaintenanceRecordResponse:
    cost_obj = Money(amount=float(r.cost), currency=currency or "INR") if r.cost is not None else None
    return MaintenanceRecordResponse(
        id=r.id,
        asset_id=r.asset_id,
        maintenance_type=r.maintenance_type,
        vendor_id=r.vendor_id,
        scheduled_on=r.scheduled_on,
        completed_on=r.completed_on,
        cost=cost_obj,
        task_id=r.task_id,
        notes=r.notes,
    )


# --- Renewals ----------------------------------------------------------------


async def create_renewal(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetRenewalCreate,
) -> AssetRenewalResponse:
    await _get_asset(session, org_id, asset_id)

    renewal = AssetRenewal(
        id=uuid.uuid4(),
        asset_id=asset_id,
        due_on=data.due_on,
        status="pending",
        approval_request_id=data.approval_request_id,
    )
    session.add(renewal)
    await session.flush()
    return AssetRenewalResponse.model_validate(renewal)


async def decide_renewal(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    renewal_id: uuid.UUID,
    data: AssetRenewalDecision,
    decided_by_user_id: uuid.UUID,
) -> AssetRenewalResponse:
    asset = await _get_asset(session, org_id, asset_id)

    res = await session.execute(
        select(AssetRenewal).where(AssetRenewal.id == renewal_id, AssetRenewal.asset_id == asset_id)
    )
    renewal = res.scalars().first()
    if not renewal:
        raise AssetNotFoundError(f"Renewal {renewal_id} not found")
    if renewal.status != "pending":
        raise InvalidStateTransitionError(renewal.status, "decide renewal")

    renewal.status = data.status
    renewal.decided_by = decided_by_user_id
    renewal.new_expires_at = data.new_expires_at

    if data.status == "approved" and data.new_expires_at:
        asset.expires_at = data.new_expires_at
        asset.renewal_due_on = data.new_expires_at - timedelta(days=30)
        asset.version += 1

    await session.flush()
    return AssetRenewalResponse.model_validate(renewal)


async def list_renewals(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> list[AssetRenewalResponse]:
    await _get_asset(session, org_id, asset_id)
    res = await session.execute(
        select(AssetRenewal).where(AssetRenewal.asset_id == asset_id).order_by(AssetRenewal.due_on.asc())
    )
    rows = res.scalars().all()
    return [AssetRenewalResponse.model_validate(r) for r in rows]


# --- Decommissioning & Disposal ----------------------------------------------


async def dispose_asset(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetDisposalCreate,
    if_match: Optional[str],
) -> AssetDisposalResponse:
    asset = await _get_asset(session, org_id, asset_id)
    _check_if_match(if_match, asset.version)

    if asset.status == "disposed":
        raise InvalidStateTransitionError(asset.status, "dispose")
    if asset.status == "in_use":
        raise InvalidStateTransitionError(asset.status, "dispose (must return asset from active custody first)")

    val = float(data.value_realised.amount) if data.value_realised else None

    disposal = AssetDisposal(
        id=uuid.uuid4(),
        asset_id=asset_id,
        method=data.method,
        disposed_on=data.disposed_on,
        value_realised=val,
        data_wiped=data.data_wiped,
        certificate_document_id=data.certificate_document_id,
    )
    session.add(disposal)

    asset.status = "disposed"
    asset.custodian_user_id = None
    asset.version += 1

    await session.flush()
    val_money = Money(amount=val, currency=asset.currency or "INR") if val is not None else None
    return AssetDisposalResponse(
        id=disposal.id,
        asset_id=disposal.asset_id,
        method=disposal.method,
        disposed_on=disposal.disposed_on,
        value_realised=val_money,
        data_wiped=disposal.data_wiped,
        certificate_document_id=disposal.certificate_document_id,
    )


async def get_disposal(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Optional[AssetDisposalResponse]:
    asset = await _get_asset(session, org_id, asset_id)
    res = await session.execute(select(AssetDisposal).where(AssetDisposal.asset_id == asset_id))
    disp = res.scalars().first()
    if not disp:
        return None
    val_money = Money(amount=float(disp.value_realised), currency=asset.currency or "INR") if disp.value_realised is not None else None
    return AssetDisposalResponse(
        id=disp.id,
        asset_id=disp.asset_id,
        method=disp.method,
        disposed_on=disp.disposed_on,
        value_realised=val_money,
        data_wiped=disp.data_wiped,
        certificate_document_id=disp.certificate_document_id,
    )


# --- Costs & Total Cost of Ownership (TCO) -----------------------------------


async def add_cost(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetCostCreate,
) -> AssetCostResponse:
    await _get_asset(session, org_id, asset_id)

    cost_val = float(data.amount)
    entry = AssetCost(
        id=uuid.uuid4(),
        asset_id=asset_id,
        cost_type=data.cost_type,
        amount=cost_val,
        currency=data.currency,
        period_start=data.period_start,
        period_end=data.period_end,
        vendor_invoice_ref=data.vendor_invoice_ref,
    )
    session.add(entry)
    await session.flush()
    return AssetCostResponse(
        id=entry.id,
        asset_id=entry.asset_id,
        cost_type=entry.cost_type,
        amount=Money(amount=cost_val, currency=entry.currency),
        period_start=entry.period_start,
        period_end=entry.period_end,
        vendor_invoice_ref=entry.vendor_invoice_ref,
    )


async def get_costs(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> tuple[list[AssetCostResponse], AssetCostSummary]:
    asset = await _get_asset(session, org_id, asset_id)

    res = await session.execute(
        select(AssetCost).where(AssetCost.asset_id == asset_id).order_by(AssetCost.period_start.desc())
    )
    entries = res.scalars().all()

    total = 0.0
    by_type: dict[str, float] = {}

    # Include initial acquisition cost if present
    if asset.acquisition_cost:
        total += float(asset.acquisition_cost)
        by_type["acquisition"] = float(asset.acquisition_cost)

    data = []
    for e in entries:
        val = float(e.amount)
        total += val
        by_type[e.cost_type] = by_type.get(e.cost_type, 0.0) + val
        data.append(
            AssetCostResponse(
                id=e.id,
                asset_id=e.asset_id,
                cost_type=e.cost_type,
                amount=Money(amount=val, currency=e.currency),
                period_start=e.period_start,
                period_end=e.period_end,
                vendor_invoice_ref=e.vendor_invoice_ref,
            )
        )

    summary = AssetCostSummary(
        total_cost=Money(amount=total, currency=asset.currency or "INR"),
        costs_by_type=by_type,
    )
    return data, summary


# --- Relationships (Bundling & Dependencies) ---------------------------------


async def create_relationship(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
    data: AssetRelationshipCreate,
) -> AssetRelationshipResponse:
    if data.related_asset_id == asset_id:
        raise ValidationFailedError("related_asset_id", "An asset cannot be related to itself")
    await _get_asset(session, org_id, asset_id)
    await _get_asset(session, org_id, data.related_asset_id)

    rel = AssetRelationship(
        id=uuid.uuid4(),
        asset_id=asset_id,
        relation_type=data.relation_type,
        related_asset_id=data.related_asset_id,
    )
    session.add(rel)
    await session.flush()
    return AssetRelationshipResponse.model_validate(rel)


async def list_relationships(
    session: AsyncSession,
    org_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> list[AssetRelationshipResponse]:
    await _get_asset(session, org_id, asset_id)
    res = await session.execute(
        select(AssetRelationship).where(AssetRelationship.asset_id == asset_id)
    )
    rows = res.scalars().all()
    return [AssetRelationshipResponse.model_validate(r) for r in rows]
