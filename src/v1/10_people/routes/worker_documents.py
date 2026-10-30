import uuid

from fastapi import APIRouter, Depends

from dependencies import CurrentActor, DatabaseSession, require_any_permission, require_permission
import permissions
from schemas.worker_documents import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    DocumentReject,
    DocumentUpsert,
    OnboardingResponse,
    RequirementsResponse,
    RequirementsUpdate,
    RevealResponse,
)
import services.bank_accounts as banks
import services.worker_documents as documents

router = APIRouter(tags=["worker-documents"])

CAN_READ = Depends(require_permission(permissions.EMPLOYEE_READ))
CAN_MANAGE = Depends(require_permission(permissions.EMPLOYEE_MANAGE))
# Bank details and revealing numbers are for those who manage employees or read compensation.
CAN_SEE_BANK = Depends(require_any_permission(permissions.EMPLOYEE_MANAGE, permissions.COMPENSATION_READ))
CAN_REVEAL = Depends(require_permission(permissions.COMPENSATION_READ))


# --- Onboarding checklist ---------------------------------------------------------------------


@router.get("/onboarding/requirements", response_model=RequirementsResponse, dependencies=[CAN_READ])
async def get_onboarding_requirements(session: DatabaseSession, actor: CurrentActor):
    """What this organization requires before an employee file counts as complete."""
    requirements = await documents.get_requirements(session, actor.organization_id)
    return {"items": documents.requirement_items(requirements)}


@router.put("/onboarding/requirements", response_model=RequirementsResponse, dependencies=[CAN_MANAGE])
async def set_onboarding_requirements(session: DatabaseSession, actor: CurrentActor, payload: RequirementsUpdate):
    requirements = await documents.set_requirements(session, actor.organization_id, payload.required)
    await session.commit()
    return {"items": documents.requirement_items(requirements)}


@router.get("/workers/{worker_id}/onboarding", response_model=OnboardingResponse, dependencies=[CAN_READ])
async def get_worker_onboarding(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    """The employee's document checklist, with ID numbers masked unless the caller may see them."""
    return await documents.get_onboarding(session, actor, worker_id)


# --- Documents --------------------------------------------------------------------------------


@router.put("/workers/{worker_id}/documents/{document_type}", response_model=OnboardingResponse, dependencies=[CAN_MANAGE])
async def save_worker_document(
    session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, document_type: str, payload: DocumentUpsert
):
    """Record or change a document's number, dates and file. It then waits for verification."""
    await documents.upsert_document(session, actor, worker_id, document_type, payload)
    await session.commit()
    return await documents.get_onboarding(session, actor, worker_id)


@router.post("/workers/{worker_id}/documents/{document_type}/verify", response_model=OnboardingResponse, dependencies=[CAN_MANAGE])
async def verify_worker_document(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, document_type: str):
    await documents.verify_document(session, actor, worker_id, document_type)
    await session.commit()
    return await documents.get_onboarding(session, actor, worker_id)


@router.post("/workers/{worker_id}/documents/{document_type}/reject", response_model=OnboardingResponse, dependencies=[CAN_MANAGE])
async def reject_worker_document(
    session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, document_type: str, payload: DocumentReject
):
    await documents.reject_document(session, actor, worker_id, document_type, payload)
    await session.commit()
    return await documents.get_onboarding(session, actor, worker_id)


@router.get("/workers/{worker_id}/documents/{document_type}/number", response_model=RevealResponse, dependencies=[CAN_REVEAL])
async def reveal_document_number(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, document_type: str):
    """The full ID number. Each call is written to the access log."""
    value = await documents.reveal_number(session, actor, worker_id, document_type)
    await session.commit()
    return RevealResponse(value=value)


# --- Bank accounts ----------------------------------------------------------------------------


@router.get("/workers/{worker_id}/bank-accounts", response_model=list[BankAccountResponse], dependencies=[CAN_SEE_BANK])
async def list_bank_accounts(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    return [banks.to_response(a) for a in await banks.list_accounts(session, actor.organization_id, worker_id)]


@router.post("/workers/{worker_id}/bank-accounts", response_model=BankAccountResponse, status_code=201, dependencies=[CAN_MANAGE])
async def create_bank_account(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, payload: BankAccountCreate):
    account = await banks.create_account(session, actor, worker_id, payload)
    await session.commit()
    return banks.to_response(account)


@router.patch("/workers/{worker_id}/bank-accounts/{account_id}", response_model=BankAccountResponse, dependencies=[CAN_MANAGE])
async def update_bank_account(
    session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, account_id: uuid.UUID, payload: BankAccountUpdate
):
    """Changing the holder, number or IFSC sends the account back to 'pending' verification."""
    account = await banks.update_account(session, actor, worker_id, account_id, payload)
    await session.commit()
    return banks.to_response(account)


@router.post("/workers/{worker_id}/bank-accounts/{account_id}/primary", response_model=BankAccountResponse, dependencies=[CAN_MANAGE])
async def make_primary_bank_account(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, account_id: uuid.UUID):
    account = await banks.set_primary(session, actor, worker_id, account_id)
    await session.commit()
    return banks.to_response(account)


@router.post("/workers/{worker_id}/bank-accounts/{account_id}/verify", response_model=BankAccountResponse, dependencies=[CAN_MANAGE])
async def verify_bank_account(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, account_id: uuid.UUID):
    account = await banks.verify_account(session, actor, worker_id, account_id)
    await session.commit()
    return banks.to_response(account)


@router.post("/workers/{worker_id}/bank-accounts/{account_id}/deactivate", response_model=BankAccountResponse, dependencies=[CAN_MANAGE])
async def deactivate_bank_account(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, account_id: uuid.UUID):
    account = await banks.deactivate_account(session, actor, worker_id, account_id)
    await session.commit()
    return banks.to_response(account)


@router.get("/workers/{worker_id}/bank-accounts/{account_id}/number", response_model=RevealResponse, dependencies=[CAN_REVEAL])
async def reveal_bank_account_number(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, account_id: uuid.UUID):
    """The full account number. Each call is written to the access log."""
    value = await banks.reveal_account_number(session, actor, worker_id, account_id)
    await session.commit()
    return RevealResponse(value=value)
