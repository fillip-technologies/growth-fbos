"""Compensation, Payroll Runs, and Reimbursements API routes."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import COMPENSATION_MANAGE, COMPENSATION_READ
from schemas.payroll import (
    PayrollRunCreate,
    PayrollRunResponse,
    PayslipResponse,
    ReimbursementClaimCreate,
    ReimbursementClaimResponse,
    SalaryStructureCreate,
    SalaryStructureResponse,
)
from services.payroll_service import (
    approve_reimbursement,
    calculate_payroll_run,
    create_salary_structure,
    disburse_payroll_run,
    get_payroll_run,
    get_worker_salary_structure,
    list_payroll_runs,
    list_reimbursements,
    submit_reimbursement,
)

router = APIRouter(tags=["Compensation & Payroll"])


# ---------------------------------------------------------
# Salary Structures
# ---------------------------------------------------------
@router.post(
    "/salary-structures",
    response_model=SalaryStructureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_salary_structure_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: SalaryStructureCreate,
):
    """
    Creates or updates salary breakdown.
    Supports historical back-dated effective dates for existing workforce import.
    """
    actor.require_permission(COMPENSATION_MANAGE)
    result = await create_salary_structure(session, org_id, data)
    await session.commit()
    return result


@router.get("/salary-structures/{worker_id}", response_model=Optional[SalaryStructureResponse])
async def get_salary_structure_endpoint(
    worker_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    return await get_worker_salary_structure(session, org_id, worker_id)


# ---------------------------------------------------------
# Reimbursements
# ---------------------------------------------------------
@router.post(
    "/reimbursements",
    response_model=ReimbursementClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_reimbursement_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: ReimbursementClaimCreate,
):
    actor.require_permission(COMPENSATION_READ)
    result = await submit_reimbursement(session, org_id, data)
    await session.commit()
    return result


@router.get("/reimbursements", response_model=List[ReimbursementClaimResponse])
async def list_reimbursements_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
):
    actor.require_permission(COMPENSATION_READ)
    return await list_reimbursements(session, org_id, worker_id=worker_id, status=status)


@router.patch("/reimbursements/{id}/approve", response_model=ReimbursementClaimResponse)
async def approve_reimbursement_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    approved: bool = Query(True),
):
    actor.require_permission(COMPENSATION_MANAGE)
    result = await approve_reimbursement(session, org_id, id, user_id, approved)
    await session.commit()
    return result


# ---------------------------------------------------------
# Payroll Runs
# ---------------------------------------------------------
@router.post(
    "/payroll/runs",
    response_model=PayrollRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def calculate_payroll_run_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    data: PayrollRunCreate,
):
    actor.require_permission(COMPENSATION_MANAGE)
    result = await calculate_payroll_run(session, org_id, user_id, data)
    await session.commit()
    return result


@router.get("/payroll/runs", response_model=List[PayrollRunResponse])
async def list_payroll_runs_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    return await list_payroll_runs(session, org_id)


@router.get("/payroll/runs/{id}", response_model=PayrollRunResponse)
async def get_payroll_run_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    return await get_payroll_run(session, org_id, id)


@router.post("/payroll/runs/{id}/disburse", response_model=PayrollRunResponse)
async def disburse_payroll_run_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_MANAGE)
    result = await disburse_payroll_run(session, org_id, id)
    await session.commit()
    return result
