import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    CollectionCaseNotFoundError,
)
from models.client import Client
from models.collection import CollectionCase, CollectionCaseInvoice, CollectionFollowup
from models.invoice import Invoice
from schemas.collection import (
    CollectionCaseResponse,
    CollectionFollowUpCreate,
    CollectionFollowUpResponse,
    CollectionRefreshResult,
)
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import ClientRef, UserRef


# Cases still being worked; a client has at most one of these at a time.
LIVE_CASE_STATUSES = ("open", "promised", "escalated")


async def _case_invoice_ids(session: AsyncSession, case_id: uuid.UUID) -> set[uuid.UUID]:
    res = await session.execute(select(CollectionCaseInvoice.invoice_id).where(CollectionCaseInvoice.case_id == case_id))
    return set(res.scalars().all())


def format_collection_case(
    case: CollectionCase,
    client: Client,
    invoice_ids: List[uuid.UUID],
) -> CollectionCaseResponse:
    promised_money = None
    if case.promised_amount is not None:
        promised_money = Money(amount=float(case.promised_amount), currency="INR")

    return CollectionCaseResponse(
        id=case.id,
        client=ClientRef(id=client.id, name=client.name),
        status=case.status if case.status in ("open", "promised", "escalated", "resolved", "written_off") else "open",
        dunning_level=case.dunning_level,
        total_overdue=Money(amount=float(case.total_overdue), currency="INR"),
        invoice_ids=invoice_ids,
        owner=UserRef(id=case.owner_user_id, name="Collection Agent"),
        next_action_at=None,
        promised_date=case.promised_date,
        promised_amount=promised_money,
    )


class CollectionService:
    @staticmethod
    async def list_collection_cases(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        client_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[CollectionCaseResponse]:
        query = (
            select(CollectionCase, Client)
            .join(Client, Client.id == CollectionCase.client_id)
            .where(CollectionCase.organization_id == org_id)
        )

        if status:
            query = query.where(CollectionCase.status == status)
        if owner_user_id:
            query = query.where(CollectionCase.owner_user_id == owner_user_id)
        if client_id:
            query = query.where(CollectionCase.client_id == client_id)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_id" in c_data:
                query = query.where(CollectionCase.id > uuid.UUID(c_data["last_id"]))

        query = query.order_by(CollectionCase.id.asc()).limit(limit + 1)
        res = await session.execute(query)
        rows = list(res.all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_id": str(data_rows[-1][0].id)})

        items = []
        for case, client in data_rows:
            inv_res = await session.execute(
                select(CollectionCaseInvoice.invoice_id).where(CollectionCaseInvoice.case_id == case.id)
            )
            inv_ids = list(inv_res.scalars().all())
            items.append(format_collection_case(case, client, inv_ids))

        return PageResponse(
            data=items,
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def list_follow_ups(
        session: AsyncSession, case_id: uuid.UUID, org_id: uuid.UUID
    ) -> List[CollectionFollowUpResponse]:
        case = await session.get(CollectionCase, case_id)
        if not case or case.organization_id != org_id:
            raise CollectionCaseNotFoundError(str(case_id))
        res = await session.execute(
            select(CollectionFollowup)
            .where(CollectionFollowup.case_id == case.id)
            .order_by(CollectionFollowup.followed_up_at.desc())
        )
        return [CollectionFollowUpResponse.model_validate(f) for f in res.scalars().all()]

    @staticmethod
    async def refresh(session: AsyncSession, org_id: uuid.UUID, today: date) -> CollectionRefreshResult:
        """
        Bring receivables up to date: issued tax invoices past their due date with money
        still owed become `overdue`; each client owing overdue money gets one live case
        tracking those invoices (owned by the client's owner); a live case whose invoices
        are all settled is resolved. Safe to run any number of times.
        """
        late = await session.execute(
            select(Invoice).where(
                Invoice.organization_id == org_id,
                Invoice.doc_type == "tax_invoice",
                Invoice.status.in_(("issued", "partially_paid")),
                Invoice.due_date < today,
                Invoice.balance_due > 0,
            )
        )
        marked = 0
        for inv in late.scalars().all():
            inv.status = "overdue"
            inv.version += 1
            marked += 1
        await session.flush()

        overdue = await session.execute(
            select(Invoice).where(
                Invoice.organization_id == org_id, Invoice.status == "overdue", Invoice.balance_due > 0
            )
        )
        overdue_by_client: dict[uuid.UUID, list[Invoice]] = defaultdict(list)
        for inv in overdue.scalars().all():
            overdue_by_client[inv.client_id].append(inv)

        live = await session.execute(
            select(CollectionCase).where(
                CollectionCase.organization_id == org_id,
                CollectionCase.status.in_(LIVE_CASE_STATUSES),
            )
        )
        live_cases = {case.client_id: case for case in live.scalars().all()}

        opened = updated = resolved = 0
        for client_id, invoices in overdue_by_client.items():
            case = live_cases.get(client_id)
            if case is None:
                client = await session.get(Client, client_id)
                case = CollectionCase(
                    organization_id=org_id,
                    client_id=client_id,
                    owner_user_id=client.owner_user_id,
                    status="open",
                    dunning_level=1,
                    total_overdue=0,
                )
                session.add(case)
                await session.flush()
                live_cases[client_id] = case
                opened += 1
            else:
                updated += 1
            tracked = await _case_invoice_ids(session, case.id)
            for inv in invoices:
                if inv.id not in tracked:
                    session.add(CollectionCaseInvoice(case_id=case.id, invoice_id=inv.id))

        for case in live_cases.values():
            tracked = await _case_invoice_ids(session, case.id)
            if not tracked:
                continue
            owed = await session.execute(select(Invoice.balance_due).where(Invoice.id.in_(tracked)))
            case.total_overdue = sum(float(b) for b in owed.scalars().all())
            if case.total_overdue == 0:
                case.status = "resolved"
                resolved += 1

        await session.flush()
        return CollectionRefreshResult(
            invoices_marked_overdue=marked, cases_opened=opened, cases_updated=updated, cases_resolved=resolved
        )

    @staticmethod
    async def log_collection_follow_up(
        session: AsyncSession,
        case_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: CollectionFollowUpCreate,
    ) -> CollectionCaseResponse:
        case = await session.get(CollectionCase, case_id)
        if not case or case.organization_id != org_id:
            raise CollectionCaseNotFoundError(str(case_id))

        client = await session.get(Client, case.client_id)

        followup = CollectionFollowup(
            case_id=case.id,
            channel=payload.channel,
            by_user_id=user_id,
            notes=payload.notes,
            outcome=payload.outcome,
        )
        if payload.followed_up_on:
            followup.followed_up_at = datetime.combine(payload.followed_up_on, datetime.min.time())
        session.add(followup)

        if payload.outcome == "promised":
            case.status = "promised"
        elif payload.outcome == "escalate":
            case.status = "escalated"
            case.dunning_level += 1
        if payload.promised_date:
            case.promised_date = payload.promised_date
        if payload.promised_amount:
            case.promised_amount = payload.promised_amount.amount

        await session.flush()

        inv_res = await session.execute(
            select(CollectionCaseInvoice.invoice_id).where(CollectionCaseInvoice.case_id == case.id)
        )
        inv_ids = list(inv_res.scalars().all())

        return format_collection_case(case, client, inv_ids)
