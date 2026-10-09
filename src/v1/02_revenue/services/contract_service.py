import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ContractNotFoundError,
    DocumentNotLinkedError,
    InvalidStateTransitionError,
    PaymentTermsTotalError,
    PreconditionRequiredError,
    QuotationNotAcceptedError,
    SignedCopyRequiredError,
    VersionConflictError,
)
from models.client import Client
from models.contract import Contract, ContractPaymentTerm, ContractTerm
from models.quotation import QuotationItem
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.contract import (
    ContractCreate,
    ContractResponse,
    PaymentTermResponse,
)
from schemas.opportunity import ClientRef
from services.billing_schedule_service import build_schedule
from services.documents_client import DocumentsClient
from services.quotation_service import get_quote_in_org

# Statuses in which the signed copy can still be (re)attached.
SIGNABLE_STATUSES = ("draft", "pending_signature")


def format_contract_response(
    contract: Contract,
    client: Client,
    terms: List[ContractPaymentTerm],
) -> ContractResponse:
    payment_terms = [
        PaymentTermResponse(
            seq=pt.seq,
            trigger_type=pt.trigger_type,
            milestone_code=pt.milestone_code,
            percent=float(pt.percent) if pt.percent is not None else None,
            amount=Money(amount=float(pt.amount), currency=contract.currency) if pt.amount is not None else None,
            due_offset_days=pt.due_offset_days or 15,
        )
        for pt in terms
    ]

    return ContractResponse(
        id=contract.id,
        contract_no=contract.contract_no,
        contract_type=contract.contract_type,
        client=ClientRef(id=client.id, name=client.name),
        deal_id=contract.deal_id,
        accepted_quotation_id=contract.accepted_quotation_id,
        opportunity_id=contract.opportunity_id,
        status=contract.status if contract.status in ("draft", "pending_signature", "active", "completed", "terminated", "expired") else "active",
        start_date=contract.start_date,
        end_date=contract.end_date,
        total_value=Money(amount=float(contract.total_value), currency=contract.currency),
        payment_terms=payment_terms,
        signed_at=contract.signed_at,
        signed_document_id=contract.signed_document_id,
        version=contract.version,
    )


class ContractService:
    @staticmethod
    async def create_contract(
        session: AsyncSession,
        org_id: uuid.UUID,
        payload: ContractCreate,
    ) -> ContractResponse:
        quote = await get_quote_in_org(session, org_id, payload.quotation_id)

        if quote.status != "accepted":
            raise QuotationNotAcceptedError(quote.status)

        # Validate payment term percentages total 100
        percent_terms = [pt.percent for pt in payload.payment_terms if pt.percent is not None]
        if percent_terms:
            total_pct = sum(percent_terms)
            if abs(total_pct - 100.0) > 0.01:
                raise PaymentTermsTotalError(total_pct)

        client = await session.get(Client, quote.client_id)

        current_year = datetime.now(timezone.utc).year
        count_res = await session.execute(
            select(func.count(Contract.id)).where(Contract.organization_id == org_id)
        )
        c_count = (count_res.scalar_one() or 0) + 1
        contract_no = f"CT-{current_year}-{c_count:04d}"

        contract = Contract(
            organization_id=org_id,
            client_id=client.id,
            accepted_quotation_id=quote.id,
            opportunity_id=quote.opportunity_id,
            contract_no=contract_no,
            contract_type=payload.contract_type,
            status="pending_signature",
            sla_tier=payload.sla_tier,
            start_date=payload.start_date,
            end_date=payload.end_date,
            total_value=quote.grand_total,
            currency=quote.currency,
            version=1,
        )
        session.add(contract)
        await session.flush()

        # Add payment terms
        persisted_terms = []
        for pt in payload.payment_terms:
            c_pt = ContractPaymentTerm(
                contract_id=contract.id,
                seq=pt.seq,
                trigger_type=pt.trigger_type,
                milestone_code=pt.milestone_code,
                percent=pt.percent,
                amount=pt.amount.amount if pt.amount else None,
                due_offset_days=pt.due_offset_days,
            )
            session.add(c_pt)
            persisted_terms.append(c_pt)

        # Copy line items from quote
        q_items = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quote.id)
        )
        for qi in q_items.scalars().all():
            c_term = ContractTerm(
                contract_id=contract.id,
                offering_id=qi.offering_id,
                description=qi.description,
                quantity=qi.quantity,
                unit_price=qi.unit_price,
                billing_model=qi.billing_model,
            )
            session.add(c_term)

        await session.flush()
        return format_contract_response(contract, client, persisted_terms)

    @staticmethod
    async def list_contracts(
        session: AsyncSession,
        org_id: uuid.UUID,
        client_id: Optional[uuid.UUID] = None,
        opportunity_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[ContractResponse]:
        query = (
            select(Contract, Client)
            .join(Client, Client.id == Contract.client_id)
            .where(Contract.organization_id == org_id)
        )
        if client_id:
            query = query.where(Contract.client_id == client_id)
        if opportunity_id:
            query = query.where(Contract.opportunity_id == opportunity_id)
        if status:
            query = query.where(Contract.status == status)
        if cursor:
            last_id = decode_cursor(cursor).get("last_id")
            if last_id:
                query = query.where(Contract.id > uuid.UUID(last_id))

        rows = list((await session.execute(query.order_by(Contract.id.asc()).limit(limit + 1))).all())
        has_more = len(rows) > limit
        rows = rows[:limit]

        terms_by_contract: dict[uuid.UUID, list[ContractPaymentTerm]] = {contract.id: [] for contract, _ in rows}
        if rows:
            terms = await session.execute(
                select(ContractPaymentTerm)
                .where(ContractPaymentTerm.contract_id.in_(terms_by_contract))
                .order_by(ContractPaymentTerm.seq.asc())
            )
            for term in terms.scalars().all():
                terms_by_contract[term.contract_id].append(term)

        next_cursor = encode_cursor({"last_id": str(rows[-1][0].id)}) if has_more and rows else None
        return PageResponse(
            data=[format_contract_response(contract, client, terms_by_contract[contract.id]) for contract, client in rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def get_contract(
        session: AsyncSession,
        contract_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ContractResponse:
        c_res = await session.execute(
            select(Contract).where(Contract.id == contract_id, Contract.organization_id == org_id)
        )
        contract = c_res.scalars().first()
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        client = await session.get(Client, contract.client_id)
        pt_res = await session.execute(
            select(ContractPaymentTerm)
            .where(ContractPaymentTerm.contract_id == contract_id)
            .order_by(ContractPaymentTerm.seq.asc())
        )
        payment_terms = list(pt_res.scalars().all())

        return format_contract_response(contract, client, payment_terms)

    @staticmethod
    async def activate_contract(
        session: AsyncSession,
        contract_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> ContractResponse:
        c_res = await session.execute(
            select(Contract).where(Contract.id == contract_id, Contract.organization_id == org_id)
        )
        contract = c_res.scalars().first()
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if contract.version != expected_version:
            raise VersionConflictError(contract.version)

        if contract.status not in SIGNABLE_STATUSES:
            raise InvalidStateTransitionError(contract.status, "activate")
        if contract.signed_document_id is None:
            raise SignedCopyRequiredError()

        contract.status = "active"
        contract.version += 1
        await session.flush()
        # Staged billing: the contract's money is invoiced line by line from its schedule.
        await build_schedule(session, contract)

        return await ContractService.get_contract(session, contract_id, org_id)

    @staticmethod
    async def set_signed_document(
        session: AsyncSession,
        contract_id: uuid.UUID,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        if_match: Optional[str],
        documents: DocumentsClient,
        authorization: str,
    ) -> ContractResponse:
        """
        Record which uploaded document is the signed copy. The file itself lives in the
        documents service and must already be attached to this contract there.
        """
        contract = (
            await session.execute(select(Contract).where(Contract.id == contract_id, Contract.organization_id == org_id))
        ).scalars().first()
        if not contract:
            raise ContractNotFoundError(str(contract_id))

        if if_match is None:
            raise PreconditionRequiredError()
        if contract.version != int(if_match.strip('"').replace("W/", "")):
            raise VersionConflictError(contract.version)
        if contract.status not in SIGNABLE_STATUSES:
            raise InvalidStateTransitionError(contract.status, "attach signed copy")

        document = await documents.find_document(authorization, org_id, document_id)
        linked_here = document is not None and any(
            link["subject"]["type"] == "revenue.contract" and link["subject"]["id"] == str(contract_id)
            for link in document.get("links", [])
        )
        if not linked_here:
            raise DocumentNotLinkedError()

        contract.signed_document_id = document_id
        contract.signed_at = datetime.now(timezone.utc)
        contract.version += 1
        await session.flush()

        return await ContractService.get_contract(session, contract_id, org_id)
