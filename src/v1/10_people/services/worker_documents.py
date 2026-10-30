"""
An employee's document file: ID numbers (encrypted), dates, the scanned file and verification,
plus the onboarding checklist that says what a company requires before the file is complete.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import ConflictError, ValidationFailedError, WorkerDocumentNotFoundError, WorkerNotFoundError
from models.worker import (
    OnboardingRequirement,
    SensitiveAccessLog,
    Worker,
    WorkerBankAccount,
    WorkerDocument,
)
from schemas.worker_documents import DocumentReject, DocumentUpsert
from services import crypto
from services.document_catalog import (
    ALL_ITEMS,
    BANK_ACCOUNT_ITEM,
    BANK_ACCOUNT_LABEL,
    DEFAULT_REQUIRED,
    DOCUMENT_TYPES,
    DocumentType,
    get_type,
    normalize_number,
)
from services.identity_client import Actor

PENDING, UPLOADED, VERIFIED, REJECTED = "pending", "uploaded", "verified", "rejected"


def can_see_numbers(actor: Actor) -> bool:
    """Masked ID numbers are for those who manage employees or read compensation."""
    return actor.has(permissions.EMPLOYEE_MANAGE) or actor.has(permissions.COMPENSATION_READ)


def log_access(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, action: str, target: str) -> None:
    session.add(
        SensitiveAccessLog(
            organization_id=actor.organization_id,
            worker_id=worker_id,
            actor_user_id=actor.user_id,
            action=action,
            target=target,
        )
    )


async def ensure_worker(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID) -> Worker:
    worker = (
        await session.execute(select(Worker).where(Worker.organization_id == organization_id, Worker.id == worker_id))
    ).scalar_one_or_none()
    if worker is None:
        raise WorkerNotFoundError(str(worker_id))
    return worker


async def _find(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, code: str) -> Optional[WorkerDocument]:
    return (
        await session.execute(
            select(WorkerDocument).where(
                WorkerDocument.organization_id == organization_id,
                WorkerDocument.worker_id == worker_id,
                WorkerDocument.document_type == code,
            )
        )
    ).scalar_one_or_none()


async def _require(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, code: str) -> WorkerDocument:
    doc = await _find(session, organization_id, worker_id, code)
    if doc is None:
        raise WorkerDocumentNotFoundError(code)
    return doc


def _reset_verification(doc: WorkerDocument) -> None:
    doc.verified = False
    doc.verified_by = None
    doc.verified_at = None
    doc.rejection_reason = None


def _entered_status(doc: WorkerDocument) -> str:
    return UPLOADED if (doc.number_encrypted or doc.document_id) else PENDING


async def upsert_document(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, code: str, data: DocumentUpsert
) -> WorkerDocument:
    """Record or change a document's details. Any change sends it back to 'uploaded' for verification."""
    doc_type = get_type(code)
    await ensure_worker(session, actor.organization_id, worker_id)
    fields = data.model_dump(exclude_unset=True)
    if fields.get("expires_on") and not doc_type.has_expiry:
        raise ValidationFailedError("expires_on", f"{doc_type.label} does not expire")

    doc = await _find(session, actor.organization_id, worker_id, code)
    if doc is None:
        doc = WorkerDocument(
            organization_id=actor.organization_id, worker_id=worker_id, document_type=code, status=PENDING
        )
        session.add(doc)

    if "document_number" in fields:
        raw = (fields["document_number"] or "").strip()
        if raw:
            number = normalize_number(doc_type, raw)
            doc.number_encrypted = crypto.encrypt(number)
            doc.number_last4 = crypto.last4(number)
        else:
            doc.number_encrypted = None
            doc.number_last4 = None
    for field in ("name_on_document", "issued_on", "expires_on", "issuing_authority", "document_id", "file_name"):
        if field in fields:
            setattr(doc, field, fields[field])

    _reset_verification(doc)
    doc.status = _entered_status(doc)
    await session.flush()
    log_access(session, actor, worker_id, "update", f"document:{code}")
    return doc


def _check_verifiable(doc: WorkerDocument, doc_type: DocumentType) -> None:
    if doc_type.has_number and not doc.number_encrypted:
        raise ConflictError(f"Enter the {doc_type.number_label} before verifying", code="DOCUMENT_INCOMPLETE")
    if not doc_type.has_number and not doc.document_id:
        raise ConflictError(f"Attach the file for {doc_type.label} before verifying", code="DOCUMENT_INCOMPLETE")


async def verify_document(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, code: str) -> WorkerDocument:
    doc_type = get_type(code)
    doc = await _require(session, actor.organization_id, worker_id, code)
    if doc.status not in (UPLOADED, REJECTED):
        raise ConflictError(f"{doc_type.label} is {doc.status} and cannot be verified", code="DOCUMENT_STATE")
    _check_verifiable(doc, doc_type)
    doc.status = VERIFIED
    doc.verified = True
    doc.verified_by = actor.user_id
    doc.verified_at = datetime.now(timezone.utc)
    doc.rejection_reason = None
    await session.flush()
    log_access(session, actor, worker_id, "verify", f"document:{code}")
    return doc


async def reject_document(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, code: str, data: DocumentReject
) -> WorkerDocument:
    doc_type = get_type(code)
    doc = await _require(session, actor.organization_id, worker_id, code)
    if doc.status == PENDING:
        raise ConflictError(f"{doc_type.label} has nothing to reject yet", code="DOCUMENT_STATE")
    _reset_verification(doc)
    doc.status = REJECTED
    doc.rejection_reason = data.reason.strip()
    await session.flush()
    log_access(session, actor, worker_id, "reject", f"document:{code}")
    return doc


async def reveal_number(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, code: str) -> str:
    doc = await _require(session, actor.organization_id, worker_id, code)
    if not doc.number_encrypted:
        raise WorkerDocumentNotFoundError(code)
    value = crypto.decrypt(doc.number_encrypted)
    log_access(session, actor, worker_id, "reveal", f"document:{code}")
    return value


# --- Requirements and the checklist ---------------------------------------------------------------


def _label(code: str) -> str:
    return BANK_ACCOUNT_LABEL if code == BANK_ACCOUNT_ITEM else DOCUMENT_TYPES[code].label


async def get_requirements(session: AsyncSession, organization_id: uuid.UUID) -> dict[str, bool]:
    """Item code -> required, from the company's saved list, else the defaults."""
    rows = (
        await session.execute(select(OnboardingRequirement).where(OnboardingRequirement.organization_id == organization_id))
    ).scalars().all()
    if not rows:
        return {code: code in DEFAULT_REQUIRED for code in ALL_ITEMS}
    saved = {row.item_code: row.is_required for row in rows}
    return {code: saved.get(code, False) for code in ALL_ITEMS}


async def set_requirements(session: AsyncSession, organization_id: uuid.UUID, required: list[str]) -> dict[str, bool]:
    unknown = [code for code in required if code not in ALL_ITEMS]
    if unknown:
        raise ValidationFailedError("required", f"Unknown onboarding item '{unknown[0]}'")
    await session.execute(delete(OnboardingRequirement).where(OnboardingRequirement.organization_id == organization_id))
    for code in ALL_ITEMS:
        session.add(OnboardingRequirement(organization_id=organization_id, item_code=code, is_required=code in required))
    await session.flush()
    return {code: code in required for code in ALL_ITEMS}


def requirement_items(requirements: dict[str, bool]) -> list[dict]:
    return [{"code": code, "label": _label(code), "required": required} for code, required in requirements.items()]


def _document_item(doc_type: DocumentType, doc: Optional[WorkerDocument], required: bool, can_see: bool) -> dict:
    item = {
        "code": doc_type.code,
        "label": doc_type.label,
        "kind": "document",
        "required": required,
        "status": doc.status if doc else PENDING,
        "number_label": doc_type.number_label,
        "has_expiry": doc_type.has_expiry,
        "has_number": bool(doc and doc.number_encrypted),
    }
    if doc:
        item.update(
            number_masked=crypto.mask(doc.number_last4) if can_see else None,
            name_on_document=doc.name_on_document,
            issued_on=doc.issued_on,
            expires_on=doc.expires_on,
            issuing_authority=doc.issuing_authority,
            document_id=doc.document_id,
            file_name=doc.file_name,
            rejection_reason=doc.rejection_reason,
            verified_at=doc.verified_at,
        )
    return item


async def get_onboarding(session: AsyncSession, actor: Actor, worker_id: uuid.UUID) -> dict:
    org = actor.organization_id
    await ensure_worker(session, org, worker_id)
    requirements = await get_requirements(session, org)
    docs = {
        doc.document_type: doc
        for doc in (
            await session.execute(
                select(WorkerDocument).where(WorkerDocument.organization_id == org, WorkerDocument.worker_id == worker_id)
            )
        ).scalars()
    }
    primary = (
        await session.execute(
            select(WorkerBankAccount).where(
                WorkerBankAccount.organization_id == org,
                WorkerBankAccount.worker_id == worker_id,
                WorkerBankAccount.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()

    can_see = can_see_numbers(actor)
    items = []
    for code in ALL_ITEMS:
        if code == BANK_ACCOUNT_ITEM:
            bank_status = PENDING if primary is None else (VERIFIED if primary.status == VERIFIED else UPLOADED)
            items.append(
                {"code": code, "label": BANK_ACCOUNT_LABEL, "kind": "bank", "required": requirements[code], "status": bank_status}
            )
        else:
            items.append(_document_item(DOCUMENT_TYPES[code], docs.get(code), requirements[code], can_see))

    required_items = [item for item in items if item["required"]]
    done = sum(1 for item in required_items if item["status"] == VERIFIED)
    return {
        "items": items,
        "required_total": len(required_items),
        "required_done": done,
        "complete": done == len(required_items),
    }
