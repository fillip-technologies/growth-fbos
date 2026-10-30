import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


from exceptions import ConflictError, PositionNotFoundError, ValidationFailedError
from models.job_architecture import JobProfile, PayBand, Position
from schemas.common import PageMeta, PageResponse
from schemas.position import JobProfileCreate, PayBandCreate, PositionCreate
from services.codes import next_position_code
from services.pagination import paginate


async def create_pay_band(
    session: AsyncSession, organization_id: uuid.UUID, data: PayBandCreate
) -> PayBand:
    existing = (
        await session.execute(
            select(PayBand).where(
                PayBand.organization_id == organization_id,
                PayBand.grade_code == data.grade_code,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"Pay band grade '{data.grade_code}' already exists")

    band = PayBand(
        organization_id=organization_id,
        grade_code=data.grade_code,
        currency=data.currency,
        minimum_annual=data.minimum_annual,
        midpoint_annual=data.midpoint_annual,
        maximum_annual=data.maximum_annual,
    )
    session.add(band)
    await session.flush()
    return band


async def list_pay_bands(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[PayBand]:
    stmt = (
        select(PayBand)
        .where(PayBand.organization_id == organization_id)
        .order_by(PayBand.grade_code.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_job_profile(
    session: AsyncSession, organization_id: uuid.UUID, data: JobProfileCreate
) -> JobProfile:
    existing = (
        await session.execute(
            select(JobProfile).where(
                JobProfile.organization_id == organization_id,
                JobProfile.job_code == data.job_code,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"Job profile code '{data.job_code}' already exists")

    profile = JobProfile(
        organization_id=organization_id,
        job_code=data.job_code,
        title=data.title,
        job_family=data.job_family,
        job_level=data.job_level,
        pay_band_id=data.pay_band_id,
        status=data.status,
    )
    session.add(profile)
    await session.flush()
    if profile.pay_band_id:
        await session.refresh(profile, ["pay_band"])
    return profile



async def list_job_profiles(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[JobProfile]:
    stmt = (
        select(JobProfile)
        .options(selectinload(JobProfile.pay_band))
        .where(JobProfile.organization_id == organization_id)
        .order_by(JobProfile.title.asc())
    )

    return list((await session.execute(stmt)).scalars().all())


async def create_position(
    session: AsyncSession, organization_id: uuid.UUID, data: PositionCreate
) -> Position:
    if data.job_profile_id:
        jp = (
            await session.execute(
                select(JobProfile).where(
                    JobProfile.organization_id == organization_id,
                    JobProfile.id == data.job_profile_id,
                )
            )
        ).scalar_one_or_none()
        if not jp:
            raise ValidationFailedError("job_profile_id", f"Job profile '{data.job_profile_id}' not found in organization")

    if data.reports_to_position_id:
        parent_pos = (
            await session.execute(
                select(Position).where(
                    Position.organization_id == organization_id,
                    Position.id == data.reports_to_position_id,
                )
            )
        ).scalar_one_or_none()
        if not parent_pos:
            raise ValidationFailedError("reports_to_position_id", f"Reporting position '{data.reports_to_position_id}' not found in organization")

    pos_code = await next_position_code(session, organization_id)
    pos = Position(
        organization_id=organization_id,
        position_code=pos_code,
        title=data.title,
        job_profile_id=data.job_profile_id,
        unit_id=data.unit_id,
        reports_to_position_id=data.reports_to_position_id,
        budgeted_fte=data.budgeted_fte,
        hiring_status="vacant",
        is_critical=data.is_critical,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
    )
    session.add(pos)
    await session.flush()
    return pos


async def list_positions(
    session: AsyncSession,
    organization_id: uuid.UUID,
    unit_id: Optional[uuid.UUID] = None,
    hiring_status: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> tuple[list[Position], PageMeta]:
    stmt = select(Position).where(Position.organization_id == organization_id)
    if unit_id:
        stmt = stmt.where(Position.unit_id == unit_id)
    if hiring_status:
        stmt = stmt.where(Position.hiring_status == hiring_status)

    return await paginate(
        session, stmt, Position, limit=limit, cursor=cursor, order_by=Position.position_code, descending=True
    )
