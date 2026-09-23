import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    InvalidStateTransitionError,
    LeadNotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from models.client import Client
from models.deal import Deal
from models.lead import Lead
from models.opportunity import Opportunity
from schemas.common import PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.lead import (
    LeadConvertRequest,
    LeadConvertResult,
    LeadCreate,
    LeadDisqualify,
    LeadResponse,
    LeadUpdate,
)
from schemas.opportunity import UserRef, VerticalRef
from services.client_service import ClientService
from services.opportunity_service import format_opportunity_detail


def format_lead_response(lead: Lead) -> LeadResponse:
    score = None
    if lead.attributes and isinstance(lead.attributes, dict):
        score = lead.attributes.get("score")

    code = lead.name if lead.name.startswith("LD-") else f"LD-{str(lead.id)[:8].upper()}"

    return LeadResponse(
        id=lead.id,
        code=code,
        deal_id=getattr(lead, "deal_id", None),
        vertical=VerticalRef(id=lead.vertical_id, name="Vertical"),
        status=lead.status,
        source=lead.source,
        campaign_ref=lead.company_ref,
        contact_name=lead.contact_name,
        contact_email=lead.contact_email,
        contact_phone=lead.contact_phone,
        company_name=lead.company_name,
        owner=UserRef(id=lead.owner_user_id, name="Assigned Owner"),
        score=score,
        client_id=lead.client_id,
        attributes=lead.attributes or {},
        version=lead.version,
        created_at=lead.created_at,
    )


class LeadService:
    @staticmethod
    async def list_leads(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str] = None,
        vertical_id: Optional[uuid.UUID] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[LeadResponse]:
        query = select(Lead).where(Lead.organization_id == org_id)
        if status:
            query = query.where(Lead.status == status)
        if vertical_id:
            query = query.where(Lead.vertical_id == vertical_id)
        if owner_user_id:
            query = query.where(Lead.owner_user_id == owner_user_id)
        if source:
            query = query.where(Lead.source == source)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_name" in c_data:
                query = query.where(Lead.name > c_data["last_name"])

        query = query.order_by(Lead.name.asc()).limit(limit + 1)
        result = await session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_name": data_rows[-1].name})

        return PageResponse(
            data=[format_lead_response(ld) for ld in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def create_lead(
        session: AsyncSession,
        org_id: uuid.UUID,
        payload: LeadCreate,
    ) -> LeadResponse:
        current_year = datetime.now(timezone.utc).year
        count_res = await session.execute(
            select(func.count(Lead.id)).where(Lead.organization_id == org_id)
        )
        lead_num = (count_res.scalar_one() or 0) + 1
        code = f"LD-{current_year}-{lead_num:04d}"

        owner_id = payload.owner_user_id or uuid.uuid4()

        lead = Lead(
            organization_id=org_id,
            vertical_id=payload.vertical_id,
            name=code,
            contact_name=payload.contact_name,
            contact_email=str(payload.contact_email) if payload.contact_email else None,
            contact_phone=payload.contact_phone,
            company_name=payload.company_name,
            company_ref=payload.campaign_ref,
            source=payload.source,
            owner_user_id=owner_id,
            status="new",
            attributes=payload.attributes or {},
            version=1,
        )
        session.add(lead)
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def get_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> LeadResponse:
        res = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
        )
        lead = res.scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))
        return format_lead_response(lead)

    @staticmethod
    async def update_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: LeadUpdate,
        if_match: Optional[str] = None,
    ) -> LeadResponse:
        res = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
        )
        lead = res.scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if lead.version != expected_version:
            raise VersionConflictError(lead.version)

        if payload.status is not None:
            if lead.status in ("converted", "disqualified"):
                raise InvalidStateTransitionError(lead.status, f"update to {payload.status}")
            lead.status = payload.status

        if payload.owner_user_id is not None:
            lead.owner_user_id = payload.owner_user_id

        if payload.score is not None:
            attrs = lead.attributes or {}
            attrs["score"] = payload.score
            lead.attributes = attrs

        if payload.attributes is not None:
            attrs = lead.attributes or {}
            attrs.update(payload.attributes)
            lead.attributes = attrs

        lead.version += 1
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def disqualify_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: LeadDisqualify,
        if_match: Optional[str] = None,
    ) -> LeadResponse:
        res = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
        )
        lead = res.scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if lead.version != expected_version:
            raise VersionConflictError(lead.version)

        if lead.status in ("converted", "disqualified"):
            raise InvalidStateTransitionError(lead.status, "disqualify")

        lead.status = "disqualified"
        lead.loss_reason = f"{payload.reason}: {payload.note}" if payload.note else payload.reason
        lead.version += 1
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def convert_lead(
        session: AsyncSession,
        org_id: uuid.UUID,
        lead_id: uuid.UUID,
        payload: LeadConvertRequest,
        if_match: Optional[str] = None,
    ) -> LeadConvertResult:
        res = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
        )
        lead = res.scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if lead.version != expected_version:
            raise VersionConflictError(lead.version)

        if lead.status in ("converted", "disqualified"):
            raise InvalidStateTransitionError(lead.status, "convert")

        # 1. Resolve or create client
        client_created = False
        if payload.existing_client_id:
            c_res = await session.execute(
                select(Client).where(Client.id == payload.existing_client_id, Client.organization_id == org_id)
            )
            client_entity = c_res.scalars().first()
            if not client_entity:
                raise ClientNotFoundError(str(payload.existing_client_id))
            client_resp = await ClientService.get_client(session, client_entity.id, org_id)
        elif payload.new_client:
            client_resp = await ClientService.create_client(session, org_id, payload.new_client)
            client_entity = await session.get(Client, client_resp.id)
            client_created = True
        else:
            raise ClientNotFoundError("Either existing_client_id or new_client must be provided")

        # 2. Create Deal
        deal = Deal(
            organization_id=org_id,
            name=payload.opportunity.name,
            status="open",
            owner_user_id=lead.owner_user_id,
        )
        session.add(deal)
        await session.flush()

        # 3. Create Opportunity
        opp = Opportunity(
            organization_id=org_id,
            client_id=client_entity.id,
            deal_id=deal.id,
            lead_id=lead.id,
            name=payload.opportunity.name,
            status="qualification",
            probability=50,
            expected_value=payload.opportunity.expected_value.amount,
            currency=payload.opportunity.expected_value.currency,
            expected_close_date=payload.opportunity.expected_close_date,
            owner_user_id=lead.owner_user_id,
            version=1,
        )
        session.add(opp)
        await session.flush()

        # 4. Mark Lead as Converted
        lead.status = "converted"
        lead.client_id = client_entity.id
        lead.version += 1
        await session.flush()

        return LeadConvertResult(
            lead=format_lead_response(lead),
            client=client_resp,
            opportunity=format_opportunity_detail(opp, client_resp.name),
            client_created=client_created,
        )
