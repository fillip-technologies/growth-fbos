import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DuplicateCodeError, OfferingNotFoundError
from models.offering import Offering
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.offering import OfferingCreate, OfferingResponse
from schemas.opportunity import VerticalRef


def format_offering_response(offering: Offering) -> OfferingResponse:
    price = Money(amount=float(offering.list_price or 0), currency="INR")
    gst_rate = float(offering.gst_code) if offering.gst_code else 18.0

    return OfferingResponse(
        id=offering.id,
        code=offering.code,
        name=offering.name,
        vertical=VerticalRef(id=offering.vertical_id, name="Vertical"),
        sac_code=offering.sac_code or "",
        gst_rate=gst_rate,
        unit=offering.unit or "project",
        billing_model=offering.billing_model,
        list_price=price,
        default_work_template_code=offering.default_work_template_code,
        status=offering.status,
    )


class OfferingService:
    @staticmethod
    async def list_offerings(
        session: AsyncSession,
        org_id: uuid.UUID,
        vertical_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[OfferingResponse]:
        query = select(Offering).where(Offering.organization_id == org_id)
        if vertical_id:
            query = query.where(Offering.vertical_id == vertical_id)
        if status:
            query = query.where(Offering.status == status)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_code" in c_data:
                query = query.where(Offering.code > c_data["last_code"])

        query = query.order_by(Offering.code.asc()).limit(limit + 1)
        result = await session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_code": data_rows[-1].code})

        return PageResponse(
            data=[format_offering_response(o) for o in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def create_offering(
        session: AsyncSession,
        org_id: uuid.UUID,
        payload: OfferingCreate,
    ) -> OfferingResponse:
        existing = await session.execute(
            select(Offering).where(Offering.organization_id == org_id, Offering.code == payload.code.strip().upper())
        )
        if existing.scalars().first():
            raise DuplicateCodeError(payload.code)

        offering = Offering(
            organization_id=org_id,
            vertical_id=payload.vertical_id,
            code=payload.code.strip().upper(),
            name=payload.name,
            sac_code=payload.sac_code,
            gst_code=str(payload.gst_rate),
            unit=payload.unit,
            billing_model=payload.billing_model,
            list_price=payload.list_price.amount if payload.list_price else None,
            default_work_template_code=payload.default_work_template_code,
            status="active",
        )
        session.add(offering)
        await session.flush()
        return format_offering_response(offering)

    @staticmethod
    async def get_offering(
        session: AsyncSession,
        offering_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> OfferingResponse:
        res = await session.execute(
            select(Offering).where(Offering.id == offering_id, Offering.organization_id == org_id)
        )
        offering = res.scalars().first()
        if not offering:
            raise OfferingNotFoundError(str(offering_id))
        return format_offering_response(offering)
