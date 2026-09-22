import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    CollectionCaseNotFoundError,
)
from models.client import Client
from models.collection import CollectionCase, CollectionCaseInvoice, CollectionFollowup
from schemas.collection import (
    CollectionCaseResponse,
    CollectionFollowUpCreate,
)
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import ClientRef, UserRef


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
        session.add(followup)

        if payload.outcome == "promised":
            case.status = "promised"
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
