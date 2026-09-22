import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    InvalidStateTransitionError,
    OpportunityNotFoundError,
    VersionConflictError,
)
from models.client import Client
from models.opportunity import Opportunity
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import (
    ClientRef,
    OpportunityDetailResponse,
    OpportunityLost,
    OpportunityUpdate,
    UserRef,
)


def format_opportunity_detail(opp: Opportunity, client_name: str) -> OpportunityDetailResponse:
    code = opp.name if opp.name.startswith("OP-") else f"OP-{str(opp.id)[:8].upper()}"
    exp_val = float(opp.expected_value) if opp.expected_value is not None else 0.0
    probability = opp.probability if opp.probability is not None else 50

    return OpportunityDetailResponse(
        id=opp.id,
        code=code,
        deal_id=opp.deal_id or opp.id,
        lead_id=opp.lead_id,
        client=ClientRef(id=opp.client_id, name=client_name),
        name=opp.name,
        stage=opp.status if opp.status in ("qualification", "proposal", "negotiation", "won", "lost") else "proposal",
        probability=probability,
        expected_value=Money(amount=exp_val, currency=opp.currency or "INR"),
        expected_close_date=opp.expected_close_date,
        owner=UserRef(id=opp.owner_user_id, name="Assigned Owner"),
        lost_reason=opp.loss_reason,
        version=opp.version,
    )


class OpportunityService:
    @staticmethod
    async def list_opportunities(
        session: AsyncSession,
        org_id: uuid.UUID,
        stage: Optional[str] = None,
        client_id: Optional[uuid.UUID] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[OpportunityDetailResponse]:
        query = (
            select(Opportunity, Client.name.label("client_name"))
            .join(Client, Client.id == Opportunity.client_id)
            .where(Opportunity.organization_id == org_id)
        )

        if stage:
            query = query.where(Opportunity.status == stage)
        if client_id:
            query = query.where(Opportunity.client_id == client_id)
        if owner_user_id:
            query = query.where(Opportunity.owner_user_id == owner_user_id)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_id" in c_data:
                query = query.where(Opportunity.id > uuid.UUID(c_data["last_id"]))

        query = query.order_by(Opportunity.id.asc()).limit(limit + 1)
        result = await session.execute(query)
        rows = list(result.all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_id": str(data_rows[-1][0].id)})

        return PageResponse(
            data=[format_opportunity_detail(opp, client_name) for opp, client_name in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def get_opportunity(
        session: AsyncSession,
        opportunity_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> OpportunityDetailResponse:
        query = (
            select(Opportunity, Client.name.label("client_name"))
            .join(Client, Client.id == Opportunity.client_id)
            .where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
        res = await session.execute(query)
        row = res.first()
        if not row:
            raise OpportunityNotFoundError(str(opportunity_id))

        opp, client_name = row
        return format_opportunity_detail(opp, client_name)

    @staticmethod
    async def update_opportunity(
        session: AsyncSession,
        opportunity_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: OpportunityUpdate,
        if_match: Optional[str] = None,
    ) -> OpportunityDetailResponse:
        query = (
            select(Opportunity, Client.name.label("client_name"))
            .join(Client, Client.id == Opportunity.client_id)
            .where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
        res = await session.execute(query)
        row = res.first()
        if not row:
            raise OpportunityNotFoundError(str(opportunity_id))

        opp, client_name = row

        if if_match is not None:
            expected_version = int(if_match.strip('"').replace("W/", ""))
            if opp.version != expected_version:
                raise VersionConflictError(opp.version)

        if opp.status in ("won", "lost"):
            raise InvalidStateTransitionError(opp.status, "update")

        if payload.stage is not None:
            opp.status = payload.stage

        if payload.probability is not None:
            opp.probability = payload.probability

        if payload.expected_value is not None:
            opp.expected_value = payload.expected_value.amount
            opp.currency = payload.expected_value.currency

        if payload.expected_close_date is not None:
            opp.expected_close_date = payload.expected_close_date

        opp.version += 1
        await session.flush()
        return format_opportunity_detail(opp, client_name)

    @staticmethod
    async def mark_opportunity_lost(
        session: AsyncSession,
        opportunity_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: OpportunityLost,
        if_match: Optional[str] = None,
    ) -> OpportunityDetailResponse:
        query = (
            select(Opportunity, Client.name.label("client_name"))
            .join(Client, Client.id == Opportunity.client_id)
            .where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
        res = await session.execute(query)
        row = res.first()
        if not row:
            raise OpportunityNotFoundError(str(opportunity_id))

        opp, client_name = row

        if if_match is not None:
            expected_version = int(if_match.strip('"').replace("W/", ""))
            if opp.version != expected_version:
                raise VersionConflictError(opp.version)

        if opp.status in ("won", "lost"):
            raise InvalidStateTransitionError(opp.status, "mark_lost")

        opp.status = "lost"
        loss_details = [payload.reason]
        if payload.competitor:
            loss_details.append(f"Competitor: {payload.competitor}")
        if payload.note:
            loss_details.append(f"Note: {payload.note}")
        opp.loss_reason = " | ".join(loss_details)

        opp.version += 1
        await session.flush()
        return format_opportunity_detail(opp, client_name)
