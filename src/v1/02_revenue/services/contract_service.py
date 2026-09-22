import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ContractNotFoundError,
    InvalidStateTransitionError,
    PaymentTermsTotalError,
    QuotationNotAcceptedError,
    QuotationNotFoundError,
    VersionConflictError,
)
from models.client import Client
from models.contract import Contract, ContractPaymentTerm, ContractTerm
from models.quotation import Quotation, QuotationItem
from schemas.common import Money
from schemas.contract import (
    ContractCreate,
    ContractResponse,
    PaymentTermResponse,
)
from schemas.opportunity import ClientRef


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
        quote = await session.get(Quotation, payload.quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(payload.quotation_id))

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

        if if_match is not None:
            expected_version = int(if_match.strip('"').replace("W/", ""))
            if contract.version != expected_version:
                raise VersionConflictError(contract.version)

        if contract.status not in ("draft", "pending_signature"):
            raise InvalidStateTransitionError(contract.status, "activate")

        contract.status = "active"
        contract.signed_at = datetime.now(timezone.utc)
        contract.version += 1
        await session.flush()

        return await ContractService.get_contract(session, contract_id, org_id)
