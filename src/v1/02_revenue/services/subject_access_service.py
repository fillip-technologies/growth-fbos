"""
Revenue's answer to the documents service: may this user see, or attach files to, this
quotation / contract?

Each attachable record type is one `SubjectRule`; making another revenue record take
documents means adding a rule here, nothing in the documents service.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ContractNotFoundError, PermissionDeniedError, SubjectLockedError, SubjectNotFoundError
from models.contract import Contract
from schemas.subject_access import SubjectAccessResponse
from services.identity_client import Actor
from services.quotation_service import get_quote_in_org

SubjectAction = Literal["read", "attach"]


@dataclass(frozen=True)
class LoadedSubject:
    status: str
    label: str


@dataclass(frozen=True)
class SubjectRule:
    read_permission: str
    attach_permission: str
    # Statuses in which the record keeps its files but takes no new ones.
    closed_statuses: frozenset[str]
    load: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[LoadedSubject]]


async def _load_quotation(session: AsyncSession, org_id: uuid.UUID, quotation_id: uuid.UUID) -> LoadedSubject:
    quote = await get_quote_in_org(session, org_id, quotation_id)
    return LoadedSubject(status=quote.status, label=f"{quote.quote_no} rev {quote.revision_no}")


async def _load_contract(session: AsyncSession, org_id: uuid.UUID, contract_id: uuid.UUID) -> LoadedSubject:
    contract = (
        await session.execute(select(Contract).where(Contract.id == contract_id, Contract.organization_id == org_id))
    ).scalar_one_or_none()
    if not contract:
        raise ContractNotFoundError(str(contract_id))
    return LoadedSubject(status=contract.status, label=contract.contract_no)


SUBJECT_RULES: dict[str, SubjectRule] = {
    "revenue.quotation": SubjectRule(
        read_permission="revenue.opportunity.read",
        attach_permission="revenue.opportunity.write",
        # A superseded revision's files are carried over to the next revision.
        closed_statuses=frozenset({"accepted", "rejected", "superseded"}),
        load=_load_quotation,
    ),
    "revenue.contract": SubjectRule(
        read_permission="revenue.contract.read",
        attach_permission="revenue.contract.write",
        closed_statuses=frozenset({"completed", "terminated", "expired"}),
        load=_load_contract,
    ),
}


async def check_subject_access(
    session: AsyncSession,
    actor: Actor,
    subject_type: str,
    subject_id: uuid.UUID,
    action: SubjectAction,
) -> SubjectAccessResponse:
    rule = SUBJECT_RULES.get(subject_type)
    if not rule:
        raise SubjectNotFoundError(subject_type)

    permission = rule.attach_permission if action == "attach" else rule.read_permission
    if not actor.has(permission):
        raise PermissionDeniedError(permission)

    subject = await rule.load(session, actor.organization_id, subject_id)
    if action == "attach" and subject.status in rule.closed_statuses:
        raise SubjectLockedError(subject_type, subject.status)

    return SubjectAccessResponse(
        type=subject_type, id=subject_id, organization_id=actor.organization_id, label=subject.label
    )
