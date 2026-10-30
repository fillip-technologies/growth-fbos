"""Employee bank accounts: account numbers are encrypted, one account is primary, changes reset verification."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import BankAccountNotFoundError, ConflictError, ValidationFailedError
from models.worker import WorkerBankAccount
from schemas.worker_documents import BankAccountCreate, BankAccountUpdate
from services import crypto
from services.document_catalog import ACCOUNT_RE, IFSC_RE
from services.identity_client import Actor
from services.worker_documents import ensure_worker, log_access

PENDING, VERIFIED, INACTIVE = "pending", "verified", "inactive"
ACCOUNT_TYPES = ("savings", "current")


def to_response(account: WorkerBankAccount) -> dict:
    return {
        "id": account.id,
        "worker_id": account.worker_id,
        "account_holder_name": account.account_holder_name,
        "bank_name": account.bank_name,
        "branch": account.branch,
        "account_masked": crypto.mask(account.account_last4),
        "ifsc": account.ifsc,
        "account_type": account.account_type,
        "upi_id": account.upi_id,
        "is_primary": account.is_primary,
        "status": account.status,
        "proof_document_id": account.proof_document_id,
        "verified_at": account.verified_at,
    }


def _clean_account_number(raw: str) -> str:
    number = "".join(raw.split())
    if not ACCOUNT_RE.fullmatch(number):
        raise ValidationFailedError("account_number", "Account number must be 9 to 18 digits")
    return number


def _clean_ifsc(raw: str) -> str:
    ifsc = raw.strip().upper()
    if not IFSC_RE.fullmatch(ifsc):
        raise ValidationFailedError("ifsc", "IFSC must be 11 characters, like HDFC0001234")
    return ifsc


def _check_type(account_type: str) -> str:
    if account_type not in ACCOUNT_TYPES:
        raise ValidationFailedError("account_type", "Account type must be savings or current")
    return account_type


async def _get(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, account_id: uuid.UUID) -> WorkerBankAccount:
    account = (
        await session.execute(
            select(WorkerBankAccount).where(
                WorkerBankAccount.organization_id == organization_id,
                WorkerBankAccount.worker_id == worker_id,
                WorkerBankAccount.id == account_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise BankAccountNotFoundError()
    return account


async def list_accounts(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID) -> list[WorkerBankAccount]:
    await ensure_worker(session, organization_id, worker_id)
    return list(
        (
            await session.execute(
                select(WorkerBankAccount)
                .where(WorkerBankAccount.organization_id == organization_id, WorkerBankAccount.worker_id == worker_id)
                .order_by(WorkerBankAccount.is_primary.desc(), WorkerBankAccount.created_at)
            )
        ).scalars()
    )


async def _make_only_primary(session: AsyncSession, account: WorkerBankAccount) -> None:
    await session.execute(
        update(WorkerBankAccount)
        .where(
            WorkerBankAccount.organization_id == account.organization_id,
            WorkerBankAccount.worker_id == account.worker_id,
            WorkerBankAccount.id != account.id,
        )
        .values(is_primary=False)
    )
    account.is_primary = True


async def create_account(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, data: BankAccountCreate
) -> WorkerBankAccount:
    await ensure_worker(session, actor.organization_id, worker_id)
    number = _clean_account_number(data.account_number)
    account = WorkerBankAccount(
        organization_id=actor.organization_id,
        worker_id=worker_id,
        account_holder_name=data.account_holder_name.strip(),
        bank_name=data.bank_name.strip(),
        branch=(data.branch or "").strip() or None,
        account_number_encrypted=crypto.encrypt(number),
        account_last4=crypto.last4(number),
        ifsc=_clean_ifsc(data.ifsc),
        account_type=_check_type(data.account_type),
        upi_id=(data.upi_id or "").strip() or None,
        proof_document_id=data.proof_document_id,
        status=PENDING,
        is_primary=False,
    )
    session.add(account)
    await session.flush()
    has_primary = any(a.is_primary for a in await list_accounts(session, actor.organization_id, worker_id))
    if data.is_primary or not has_primary:
        await _make_only_primary(session, account)
    log_access(session, actor, worker_id, "update", f"bank_account:{account.id}")
    await session.flush()
    return account


async def update_account(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, account_id: uuid.UUID, data: BankAccountUpdate
) -> WorkerBankAccount:
    account = await _get(session, actor.organization_id, worker_id, account_id)
    if account.status == INACTIVE:
        raise ConflictError("This account is inactive and cannot be changed", code="BANK_ACCOUNT_INACTIVE")
    fields = data.model_dump(exclude_unset=True)
    changed_payment_details = False

    if "account_number" in fields:
        number = _clean_account_number(fields.pop("account_number"))
        account.account_number_encrypted = crypto.encrypt(number)
        account.account_last4 = crypto.last4(number)
        changed_payment_details = True
    if "ifsc" in fields:
        account.ifsc = _clean_ifsc(fields.pop("ifsc"))
        changed_payment_details = True
    if "account_type" in fields:
        account.account_type = _check_type(fields.pop("account_type"))
    if "account_holder_name" in fields:
        changed_payment_details = True
    for field, value in fields.items():
        setattr(account, field, value.strip() if isinstance(value, str) else value)

    if changed_payment_details:
        account.status = PENDING
        account.verified_by = None
        account.verified_at = None
    await session.flush()
    log_access(session, actor, worker_id, "update", f"bank_account:{account.id}")
    return account


async def set_primary(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, account_id: uuid.UUID) -> WorkerBankAccount:
    account = await _get(session, actor.organization_id, worker_id, account_id)
    if account.status == INACTIVE:
        raise ConflictError("An inactive account cannot be primary", code="BANK_ACCOUNT_INACTIVE")
    await _make_only_primary(session, account)
    await session.flush()
    log_access(session, actor, worker_id, "update", f"bank_account:{account.id}")
    return account


async def verify_account(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, account_id: uuid.UUID) -> WorkerBankAccount:
    account = await _get(session, actor.organization_id, worker_id, account_id)
    if account.status != PENDING:
        raise ConflictError(f"This account is {account.status} and cannot be verified", code="BANK_ACCOUNT_STATE")
    account.status = VERIFIED
    account.verified_by = actor.user_id
    account.verified_at = datetime.now(timezone.utc)
    await session.flush()
    log_access(session, actor, worker_id, "verify", f"bank_account:{account.id}")
    return account


async def deactivate_account(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, account_id: uuid.UUID) -> WorkerBankAccount:
    account = await _get(session, actor.organization_id, worker_id, account_id)
    if account.is_primary:
        raise ConflictError("Make another account primary before deactivating this one", code="BANK_ACCOUNT_PRIMARY")
    account.status = INACTIVE
    await session.flush()
    log_access(session, actor, worker_id, "update", f"bank_account:{account.id}")
    return account


async def reveal_account_number(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, account_id: uuid.UUID) -> str:
    account = await _get(session, actor.organization_id, worker_id, account_id)
    value = crypto.decrypt(account.account_number_encrypted)
    log_access(session, actor, worker_id, "reveal", f"bank_account:{account.id}")
    return value
