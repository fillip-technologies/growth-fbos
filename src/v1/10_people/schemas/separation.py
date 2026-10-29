"""Pydantic schemas for Offboarding, Clearance Matrix, and Full & Final Settlement."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# Separation Cases
# ---------------------------------------------------------
class SeparationInitiateRequest(BaseModel):
    worker_id: uuid.UUID
    separation_type: str = "resignation"  # resignation, termination, mutual_separation, retirement
    resignation_date: date  # Past date supported for historical exits
    contractual_lwd: date
    agreed_lwd: date
    notice_shortfall_days: int = 0
    reason: Optional[str] = None


class ExitClearanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    separation_id: uuid.UUID
    department: str
    status: str
    cleared_by: Optional[uuid.UUID] = None
    remarks: Optional[str] = None
    updated_at: datetime


class UpdateClearanceRequest(BaseModel):
    department: str  # it_assets, finance, admin, team_lead, hr
    status: str  # cleared, blocked, pending
    remarks: Optional[str] = None


class FullAndFinalSettlementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    separation_id: uuid.UUID
    worker_id: uuid.UUID
    unpaid_worked_days: Decimal
    unpaid_worked_days_amount: Decimal
    encashable_leave_days: Decimal
    encashable_leaves_amount: Decimal
    gratuity_amount: Decimal
    bonus_pending_amount: Decimal
    notice_shortfall_deduction: Decimal
    asset_damage_deductions: Decimal
    net_payable: Decimal
    currency: str
    relieving_letter_doc_id: Optional[uuid.UUID] = None
    status: str
    created_at: datetime
    updated_at: datetime


class SeparationCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    separation_code: str
    worker_id: uuid.UUID
    separation_type: str
    resignation_date: date
    contractual_lwd: date
    agreed_lwd: date
    notice_shortfall_days: int
    reason: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    clearances: Optional[List[ExitClearanceResponse]] = None
    settlement: Optional[FullAndFinalSettlementResponse] = None
