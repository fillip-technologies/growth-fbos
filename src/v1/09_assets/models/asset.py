import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class AssetCategory(Base):
    """
    Hierarchical taxonomy grouping for organizational assets.
    """

    __tablename__ = "asset_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("asset_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class AssetType(Base):
    """
    Sub-category specification defining asset family, metadata schemas, and lifecycle behaviors.
    """

    __tablename__ = "asset_types"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("asset_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    family: Mapped[str] = mapped_column(String(50), nullable=False)  # hardware, software, vehicle, facility, IP
    attribute_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tracks_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    single_custodian: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Vendor(Base):
    """
    External supplier, SaaS provider, hardware manufacturer, or contractor vendor.
    """

    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class VendorAccount(Base):
    """
    Account, portal registration, or billing subscription maintained with an external vendor.
    """

    __tablename__ = "vendor_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    billing_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class Asset(Base):
    """
    Managed organizational physical or digital asset record.
    """

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    parent_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    asset_tag: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("asset_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    owner_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    custodian_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="available", index=True)
    criticality: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    serial_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    acquired_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    acquisition_cost: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    expires_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    renewal_due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vendor_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("vendor_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )


class AssetCost(Base):
    """
    Cost, lease, depreciation, or expense allocation associated with an asset.
    """

    __tablename__ = "asset_costs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cost_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    vendor_invoice_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class MaintenanceRecord(Base):
    """
    Scheduled or completed maintenance, calibration, repair, or inspection service log.
    """

    __tablename__ = "maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    maintenance_type: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scheduled_on: Mapped[date] = mapped_column(Date, nullable=False)
    completed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    cost: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AssetRenewal(Base):
    """
    Warranty, lease, certificate, or subscription contract renewal tracking.
    """

    __tablename__ = "asset_renewals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    new_expires_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class AssetDisposal(Base):
    """
    Decommissioning, disposal, sale, or scrapping event record with certificate proof.
    """

    __tablename__ = "asset_disposals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    disposed_on: Mapped[date] = mapped_column(Date, nullable=False)
    value_realised: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    data_wiped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certificate_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)


class AssetRelationship(Base):
    """
    Graph association between assets (parent_of, depends_on, installed_on, backup_for).
    """

    __tablename__ = "asset_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    related_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )


class AssetAssignment(Base):
    """
    Custody check-out / assignment tracking of an asset to an employee, team, or facility.
    """

    __tablename__ = "asset_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignee_type: Mapped[str] = mapped_column(String(50), nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_out: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    condition_in: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    assigned_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)


class Subscription(Base):
    """
    Recurring software license or service subscription plan details.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class License(Base):
    """
    Software product license entitlement, key reference, and allocated capacity.
    """

    __tablename__ = "licenses"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    license_type: Mapped[str] = mapped_column(String(50), nullable=False)
    seats_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    key_secret_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class LicenseSeat(Base):
    """
    Individual seat assignment of a software license to a user or endpoint.
    """

    __tablename__ = "license_seats"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    license_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignee_type: Mapped[str] = mapped_column(String(50), nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Credential(Base):
    """
    Digital secret, service account, API token, or SSH key metadata linked to an asset or vendor.
    """

    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    vendor_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("vendor_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    rotation_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class CredentialGrant(Base):
    """
    Access authorization grant permitting a principal to access or manage a credential.
    """

    __tablename__ = "credential_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(50), nullable=False, default="read")
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class VendorContract(Base):
    """
    Commercial agreement, MSA, SLA, or lease contract with an external vendor.
    """

    __tablename__ = "vendor_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
