import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    InvalidStateTransitionError,
    OfferingNotFoundError,
    OpportunityNotFoundError,
    PreconditionRequiredError,
    QuotationFrozenError,
    QuotationNotFoundError,
    VersionConflictError,
)
from models.client import Client
from models.offering import Offering
from models.opportunity import Opportunity
from models.quotation import NegotiationNote, Quotation, QuotationItem
from schemas.common import Money
from schemas.opportunity import ClientRef
from schemas.quotation import (
    QuotationCreate,
    QuotationItemInput,
    QuotationItemResponse,
    QuotationItemsReplace,
    QuotationReject,
    QuotationResponse,
    QuotationTotals,
)


def calculate_tax_and_totals(
    items_input: List[QuotationItemInput],
    offerings_map: dict[uuid.UUID, Offering],
    place_of_supply: str,
    org_state_code: str = "29",
) -> tuple[List[dict], QuotationTotals]:
    """Calculate subtotal, discount, taxable value, GST split (CGST+SGST vs IGST), and totals."""
    processed_items = []
    subtotal_acc = Decimal("0.00")
    discount_acc = Decimal("0.00")
    taxable_acc = Decimal("0.00")
    cgst_acc = Decimal("0.00")
    sgst_acc = Decimal("0.00")
    igst_acc = Decimal("0.00")

    is_inter_state = place_of_supply.strip() != org_state_code.strip()

    for idx, item in enumerate(items_input, start=1):
        offering = offerings_map.get(item.offering_id)
        if not offering:
            raise OfferingNotFoundError(str(item.offering_id))

        if item.unit_price is not None:
            unit_price_val = Decimal(str(item.unit_price.amount))
        elif offering.list_price is not None:
            unit_price_val = Decimal(str(offering.list_price))
        else:
            unit_price_val = Decimal("0.00")

        qty = Decimal(str(item.quantity))
        disc_pct = Decimal(str(item.discount_pct))

        raw_subtotal = qty * unit_price_val
        disc_amount = (raw_subtotal * disc_pct) / Decimal("100.00")
        taxable_value = raw_subtotal - disc_amount

        try:
            gst_rate_val = Decimal(str(offering.gst_code or "18.0"))
        except InvalidOperation:
            gst_rate_val = Decimal("18.0")

        if is_inter_state:
            item_cgst = Decimal("0.00")
            item_sgst = Decimal("0.00")
            item_igst = (taxable_value * gst_rate_val) / Decimal("100.00")
        else:
            half_rate = gst_rate_val / Decimal("2.00")
            item_cgst = (taxable_value * half_rate) / Decimal("100.00")
            item_sgst = (taxable_value * half_rate) / Decimal("100.00")
            item_igst = Decimal("0.00")

        line_total = taxable_value + item_cgst + item_sgst + item_igst

        subtotal_acc += raw_subtotal
        discount_acc += disc_amount
        taxable_acc += taxable_value
        cgst_acc += item_cgst
        sgst_acc += item_sgst
        igst_acc += item_igst

        processed_items.append(
            {
                "line_no": idx,
                "offering_id": offering.id,
                "description": item.description or offering.name,
                "quantity": float(qty),
                "unit": offering.unit or "project",
                "unit_price": Money(amount=float(unit_price_val), currency="INR"),
                "discount_pct": float(disc_pct),
                "taxable_value": Money(amount=float(taxable_value), currency="INR"),
                "gst_rate": float(gst_rate_val),
                "sac_code": offering.sac_code,
                "line_total": Money(amount=float(line_total), currency="INR"),
                "billing_model": offering.billing_model,
                "cgst": item_cgst,
                "sgst": item_sgst,
                "igst": item_igst,
            }
        )

    grand_total = taxable_acc + cgst_acc + sgst_acc + igst_acc
    totals = QuotationTotals(
        subtotal=Money(amount=float(subtotal_acc), currency="INR"),
        discount_total=Money(amount=float(discount_acc), currency="INR"),
        taxable_total=Money(amount=float(taxable_acc), currency="INR"),
        cgst=Money(amount=float(cgst_acc), currency="INR"),
        sgst=Money(amount=float(sgst_acc), currency="INR"),
        igst=Money(amount=float(igst_acc), currency="INR"),
        grand_total=Money(amount=float(grand_total), currency="INR"),
    )
    return processed_items, totals


def format_quotation_response(
    quote: Quotation,
    client: Client,
    items: List[QuotationItem],
    totals: QuotationTotals,
) -> QuotationResponse:
    item_responses = [
        QuotationItemResponse(
            line_no=it.line_no,
            offering_id=it.offering_id,
            description=it.description,
            quantity=float(it.quantity),
            unit=it.unit or "project",
            unit_price=Money(amount=float(it.unit_price), currency=quote.currency),
            discount_pct=float(it.discount_pct),
            taxable_value=Money(amount=float(it.net_price), currency=quote.currency),
            gst_rate=float(it.gst_rate),
            sac_code=None,
            line_total=Money(amount=float(it.line_total), currency=quote.currency),
        )
        for it in items
    ]

    return QuotationResponse(
        id=quote.id,
        quote_no=quote.quote_no,
        revision_no=quote.revision_no,
        previous_revision_id=quote.previous_revision_id,
        opportunity_id=quote.opportunity_id,
        client=ClientRef(id=client.id, name=client.name),
        status=quote.status,
        valid_until=quote.completed_at.date() if quote.completed_at else datetime.now(timezone.utc).date(),
        currency=quote.currency,
        place_of_supply=quote.place_of_supply or "29",
        items=item_responses,
        totals=totals,
        approval_request_id=quote.approved_request_id,
        pdf_document_id=None,
        terms=quote.summary,
        sent_at=quote.completed_at if quote.status in ("sent", "accepted", "rejected") else None,
        accepted_at=quote.completed_at if quote.status == "accepted" else None,
        version=quote.version,
    )


class QuotationService:
    @staticmethod
    async def create_quotation(
        session: AsyncSession,
        org_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        payload: QuotationCreate,
    ) -> QuotationResponse:
        opp_res = await session.execute(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
        opp = opp_res.scalars().first()
        if not opp:
            raise OpportunityNotFoundError(str(opportunity_id))

        client = await session.get(Client, opp.client_id)

        # Determine place of supply
        place_of_supply = payload.place_of_supply
        if not place_of_supply and client and client.billing_address:
            try:
                addr_dict = json.loads(client.billing_address) if isinstance(client.billing_address, str) else client.billing_address
                place_of_supply = addr_dict.get("state_code", "29")
            except (json.JSONDecodeError, AttributeError, TypeError):
                place_of_supply = "29"
        if not place_of_supply:
            place_of_supply = "29"

        # Fetch offerings
        offering_ids = [it.offering_id for it in payload.items]
        off_res = await session.execute(select(Offering).where(Offering.id.in_(offering_ids)))
        offerings_map = {o.id: o for o in off_res.scalars().all()}

        processed_items, totals = calculate_tax_and_totals(
            items_input=payload.items,
            offerings_map=offerings_map,
            place_of_supply=place_of_supply,
        )

        current_year = datetime.now(timezone.utc).year
        count_res = await session.execute(select(func.count(Quotation.id)))
        q_count = (count_res.scalar_one() or 0) + 1
        quote_no = f"QT-{current_year}-{q_count:04d}"

        valid_until_dt = datetime.combine(payload.valid_until, datetime.min.time())

        quote = Quotation(
            opportunity_id=opp.id,
            client_id=client.id,
            quote_no=quote_no,
            revision_no=1,
            currency="INR",
            summary=payload.terms,
            place_of_supply=place_of_supply,
            subtotal=totals.subtotal.amount,
            discount_total=totals.discount_total.amount,
            tax_total=totals.cgst.amount + totals.sgst.amount + totals.igst.amount,
            grand_total=totals.grand_total.amount,
            status="draft",
            completed_at=valid_until_dt,
            version=1,
        )
        session.add(quote)
        await session.flush()

        persisted_items = []
        for p in processed_items:
            q_item = QuotationItem(
                quotation_id=quote.id,
                offering_id=p["offering_id"],
                line_no=p["line_no"],
                description=p["description"],
                quantity=p["quantity"],
                unit=p["unit"],
                unit_price=p["unit_price"].amount,
                discount_pct=p["discount_pct"],
                gst_rate=p["gst_rate"],
                net_price=p["taxable_value"].amount,
                billing_model=p["billing_model"],
                line_total=p["line_total"].amount,
            )
            session.add(q_item)
            persisted_items.append(q_item)

        await session.flush()
        return format_quotation_response(quote, client, persisted_items, totals)

    @staticmethod
    async def get_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        client = await session.get(Client, quote.client_id)
        items_res = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quotation_id).order_by(QuotationItem.line_no.asc())
        )
        items = list(items_res.scalars().all())

        totals = QuotationTotals(
            subtotal=Money(amount=float(quote.subtotal), currency=quote.currency),
            discount_total=Money(amount=float(quote.discount_total), currency=quote.currency),
            taxable_total=Money(amount=float(quote.subtotal - quote.discount_total), currency=quote.currency),
            cgst=Money(amount=float(quote.tax_total / 2), currency=quote.currency),
            sgst=Money(amount=float(quote.tax_total / 2), currency=quote.currency),
            igst=Money(amount=0.0, currency=quote.currency),
            grand_total=Money(amount=float(quote.grand_total), currency=quote.currency),
        )
        return format_quotation_response(quote, client, items, totals)

    @staticmethod
    async def replace_quotation_items(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationItemsReplace,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if quote.version != expected_version:
            raise VersionConflictError(quote.version)

        if quote.status != "draft":
            raise QuotationFrozenError("replace items on", quote.status)

        client = await session.get(Client, quote.client_id)

        # Fetch offerings
        offering_ids = [it.offering_id for it in payload.items]
        off_res = await session.execute(select(Offering).where(Offering.id.in_(offering_ids)))
        offerings_map = {o.id: o for o in off_res.scalars().all()}

        processed_items, totals = calculate_tax_and_totals(
            items_input=payload.items,
            offerings_map=offerings_map,
            place_of_supply=quote.place_of_supply or "29",
        )

        # Remove existing items
        old_items = await session.execute(select(QuotationItem).where(QuotationItem.quotation_id == quotation_id))
        for item in old_items.scalars().all():
            await session.delete(item)

        persisted_items = []
        for p in processed_items:
            q_item = QuotationItem(
                quotation_id=quote.id,
                offering_id=p["offering_id"],
                line_no=p["line_no"],
                description=p["description"],
                quantity=p["quantity"],
                unit=p["unit"],
                unit_price=p["unit_price"].amount,
                discount_pct=p["discount_pct"],
                gst_rate=p["gst_rate"],
                net_price=p["taxable_value"].amount,
                billing_model=p["billing_model"],
                line_total=p["line_total"].amount,
            )
            session.add(q_item)
            persisted_items.append(q_item)

        quote.subtotal = totals.subtotal.amount
        quote.discount_total = totals.discount_total.amount
        quote.tax_total = totals.cgst.amount + totals.sgst.amount + totals.igst.amount
        quote.grand_total = totals.grand_total.amount
        quote.version += 1
        await session.flush()

        return format_quotation_response(quote, client, persisted_items, totals)

    @staticmethod
    async def submit_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if quote.version != expected_version:
            raise VersionConflictError(quote.version)

        if quote.status != "draft":
            raise InvalidStateTransitionError(quote.status, "submit")

        # Approval policy: if discount percentage > 20%, set pending_approval; otherwise approved immediately
        disc_pct = (float(quote.discount_total) / float(quote.subtotal) * 100.0) if quote.subtotal > 0 else 0.0
        if disc_pct > 20.0:
            quote.status = "pending_approval"
            quote.approved_request_id = uuid.uuid4()
        else:
            quote.status = "approved"

        quote.version += 1
        await session.flush()
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def send_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if quote.version != expected_version:
            raise VersionConflictError(quote.version)

        if quote.status not in ("approved", "draft"):
            raise InvalidStateTransitionError(quote.status, "send")

        quote.status = "sent"
        quote.completed_at = datetime.now(timezone.utc)
        quote.version += 1
        await session.flush()
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def revise_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> QuotationResponse:
        curr_quote = await session.get(Quotation, quotation_id)
        if not curr_quote:
            raise QuotationNotFoundError(str(quotation_id))

        client = await session.get(Client, curr_quote.client_id)
        old_items_res = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quotation_id).order_by(QuotationItem.line_no.asc())
        )
        old_items = list(old_items_res.scalars().all())

        # Mark current quotation superseded
        curr_quote.status = "superseded"
        curr_quote.version += 1
        await session.flush()

        # Create revision N+1
        new_rev = Quotation(
            opportunity_id=curr_quote.opportunity_id,
            client_id=curr_quote.client_id,
            previous_revision_id=curr_quote.id,
            quote_no=curr_quote.quote_no,
            revision_no=curr_quote.revision_no + 1,
            currency=curr_quote.currency,
            summary=curr_quote.summary,
            place_of_supply=curr_quote.place_of_supply,
            subtotal=curr_quote.subtotal,
            discount_total=curr_quote.discount_total,
            tax_total=curr_quote.tax_total,
            grand_total=curr_quote.grand_total,
            status="draft",
            completed_at=curr_quote.completed_at,
            version=1,
        )
        session.add(new_rev)
        await session.flush()

        persisted_items = []
        for it in old_items:
            new_item = QuotationItem(
                quotation_id=new_rev.id,
                offering_id=it.offering_id,
                line_no=it.line_no,
                description=it.description,
                quantity=it.quantity,
                unit=it.unit,
                unit_price=it.unit_price,
                discount_pct=it.discount_pct,
                gst_rate=it.gst_rate,
                net_price=it.net_price,
                billing_model=it.billing_model,
                line_total=it.line_total,
            )
            session.add(new_item)
            persisted_items.append(new_item)

        await session.flush()

        totals = QuotationTotals(
            subtotal=Money(amount=float(new_rev.subtotal), currency=new_rev.currency),
            discount_total=Money(amount=float(new_rev.discount_total), currency=new_rev.currency),
            taxable_total=Money(amount=float(new_rev.subtotal - new_rev.discount_total), currency=new_rev.currency),
            cgst=Money(amount=float(new_rev.tax_total / 2), currency=new_rev.currency),
            sgst=Money(amount=float(new_rev.tax_total / 2), currency=new_rev.currency),
            igst=Money(amount=0.0, currency=new_rev.currency),
            grand_total=Money(amount=float(new_rev.grand_total), currency=new_rev.currency),
        )
        return format_quotation_response(new_rev, client, persisted_items, totals)

    @staticmethod
    async def accept_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if quote.version != expected_version:
            raise VersionConflictError(quote.version)

        if quote.status not in ("sent", "approved", "draft"):
            raise InvalidStateTransitionError(quote.status, "accept")

        quote.status = "accepted"
        quote.completed_at = datetime.now(timezone.utc)
        quote.version += 1

        # Advance opportunity to won
        if quote.opportunity_id:
            opp = await session.get(Opportunity, quote.opportunity_id)
            if opp:
                opp.status = "won"
                opp.version += 1

        await session.flush()
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def reject_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationReject,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await session.get(Quotation, quotation_id)
        if not quote:
            raise QuotationNotFoundError(str(quotation_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if quote.version != expected_version:
            raise VersionConflictError(quote.version)

        if quote.status != "sent":
            raise InvalidStateTransitionError(quote.status, "reject")

        quote.status = "rejected"
        quote.version += 1

        # Add negotiation note
        note = NegotiationNote(
            quotation_id=quote.id,
            summary=f"Quotation rejected by client: {payload.reason}",
            requested_changes=payload.reason,
            round_no=quote.revision_no,
        )
        session.add(note)
        await session.flush()

        return await QuotationService.get_quotation(session, quotation_id, org_id)
