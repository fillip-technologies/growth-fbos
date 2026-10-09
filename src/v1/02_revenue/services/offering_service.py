from datetime import date
import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DuplicateCodeError, OfferingNotFoundError
from finance.errors import TaxConfigError
from finance.money import as_float
from finance.tax.snapshot import ConfigSnapshot
from finance.tax.store import load_snapshot
from models.offering import Offering
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.offering import OfferingCreate, OfferingResponse
from schemas.opportunity import VerticalRef
from services.tax_service import legacy_rate


def _gst_rate(offering: Offering, snapshot: Optional[ConfigSnapshot]) -> Optional[float]:
    """The category's rate today, or the legacy percentage; None when the offering has neither."""
    if offering.tax_category_code and snapshot is not None:
        entry = snapshot.find("category", offering.tax_category_code)
        rate_code = entry.data.rate if entry else None  # type: ignore[attr-defined]
        rate_entry = snapshot.find("rate", rate_code) if rate_code else None
        return as_float(rate_entry.data.percent) if rate_entry else None  # type: ignore[attr-defined]
    parsed = legacy_rate(offering.gst_code)
    return as_float(parsed) if parsed is not None else None


async def _snapshot_if_needed(session: AsyncSession, org_id: uuid.UUID, offerings: Iterable[Offering]) -> Optional[ConfigSnapshot]:
    if not any(offering.tax_category_code for offering in offerings):
        return None
    return await load_snapshot(session, org_id, date.today())


def format_offering_response(offering: Offering, snapshot: Optional[ConfigSnapshot] = None) -> OfferingResponse:
    price = Money(amount=float(offering.list_price or 0), currency="INR")
    gst_rate = _gst_rate(offering, snapshot)
    valid_units = {"project", "hour", "month", "unit"}
    unit = offering.unit if offering.unit in valid_units else "project"

    return OfferingResponse(
        id=offering.id,
        code=offering.code,
        name=offering.name,
        vertical=VerticalRef(id=offering.vertical_id, name="Vertical") if offering.vertical_id else None,
        sac_code=offering.sac_code or "",
        tax_category_code=offering.tax_category_code,
        gst_rate=gst_rate,
        unit=unit,
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

        snapshot = await _snapshot_if_needed(session, org_id, data_rows)
        return PageResponse(
            data=[format_offering_response(o, snapshot) for o in data_rows],
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
        snapshot = await load_snapshot(session, org_id, date.today())
        if payload.tax_category_code:
            category = snapshot.category(payload.tax_category_code)
            if category.treatment == "taxable" and category.rate is None:
                raise TaxConfigError("TAX_CATEGORY_RATE_MISSING", f"Category {payload.tax_category_code} has no rate.")

        offering = Offering(
            organization_id=org_id,
            vertical_id=payload.vertical_id,
            code=payload.code.strip().upper(),
            name=payload.name,
            sac_code=payload.sac_code,
            gst_code=str(payload.gst_rate) if payload.gst_rate is not None else None,
            tax_category_code=payload.tax_category_code,
            unit=payload.unit,
            billing_model=payload.billing_model,
            list_price=payload.list_price.amount if payload.list_price else None,
            default_work_template_code=payload.default_work_template_code,
            status="active",
        )
        session.add(offering)
        await session.flush()
        return format_offering_response(offering, snapshot)

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
        return format_offering_response(offering, await _snapshot_if_needed(session, org_id, [offering]))
