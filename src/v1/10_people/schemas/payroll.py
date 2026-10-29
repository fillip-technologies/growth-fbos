"""Pydantic schemas for Salary Structure, Payroll Runs, Payslips, and Reimbursements."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# Salary Structure
# ---------------------------------------------------------
class SalaryStructureCreate(BaseModel):
    worker_id: uuid.UUID
    currency: str = "USD"
    basic_salary: Decimal
    hra: Decimal = Decimal("0.0")
    special_allowance: Decimal = Decimal("0.0")
    pf_deduction: Decimal = Decimal("0.0")
    pt_deduction: Decimal = Decimal("0.0")
    tds_tax: Decimal = Decimal("0.0")
    gross_monthly: Decimal
    annual_ctc: Decimal
    effective_from: date  # Supports past joining dates or historical back-dating
    is_current: bool = True


class SalaryStructureResponse(SalaryStructureCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Reimbursements
# ---------------------------------------------------------
class ReimbursementClaimCreate(BaseModel):
    worker_id: uuid.UUID
    category: str = "travel"  # travel, food, broadband, medical, office_supplies, other
    amount: Decimal
    currency: str = "USD"
    spent_date: date  # Supports historical back-dated claims
    receipt_doc_id: Optional[uuid.UUID] = None
    description: str


class ReimbursementClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    claim_code: str
    category: str
    amount: Decimal
    currency: str
    spent_date: date
    receipt_doc_id: Optional[uuid.UUID] = None
    description: str
    status: str
    approved_by: Optional[uuid.UUID] = None
    settled_in_payroll_run_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Payroll Runs & Payslips
# ---------------------------------------------------------
class PayrollRunCreate(BaseModel):
    year: int
    month: int  # 1-12


class PayslipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    payroll_run_id: uuid.UUID
    worker_id: uuid.UUID
    year: int
    month: int
    payable_days: Decimal
    unpaid_days: Decimal
    basic_earned: Decimal
    allowances_earned: Decimal
    overtime_pay: Decimal
    reimbursements_pay: Decimal
    bonus_pay: Decimal
    gross_earned: Decimal
    total_deductions: Decimal
    net_payable: Decimal
    currency: str
    pdf_doc_id: Optional[uuid.UUID] = None
    status: str
    created_at: datetime


class PayrollRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    payroll_code: str
    year: int
    month: int
    total_workers: int
    total_gross: Decimal
    total_net: Decimal
    total_deductions: Decimal
    status: str
    processed_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    payslips: Optional[List[PayslipResponse]] = None
