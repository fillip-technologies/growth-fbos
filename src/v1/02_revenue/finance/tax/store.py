"""
Reading and versioning an organization's tax configuration in the database.

`load_snapshot` is the one way services get configuration for the engine. The first time an
organization uses billing, its configuration is started from the default packs.
"""

from datetime import date
import uuid
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from finance.errors import TaxConfigError
from finance.tax.periods import find_overlaps
from finance.tax.snapshot import ConfigSnapshot
from models.tax_config import TaxConfigEntry, TaxConfigRevision, TaxPackApplication


async def load_entries(session: AsyncSession, org_id: uuid.UUID, kind: Optional[str] = None) -> list[TaxConfigEntry]:
    query = select(TaxConfigEntry).where(TaxConfigEntry.organization_id == org_id)
    if kind is not None:
        query = query.where(TaxConfigEntry.kind == kind)
    rows = await session.execute(query.order_by(TaxConfigEntry.kind, TaxConfigEntry.code, TaxConfigEntry.effective_from))
    return list(rows.scalars().all())


async def current_revision(session: AsyncSession, org_id: uuid.UUID) -> int:
    latest = await session.execute(
        select(func.max(TaxConfigRevision.revision)).where(TaxConfigRevision.organization_id == org_id)
    )
    return latest.scalar_one() or 0


async def record_revision(
    session: AsyncSession, org_id: uuid.UUID, user_id: Optional[uuid.UUID], source: str, summary: str
) -> int:
    revision = await current_revision(session, org_id) + 1
    session.add(
        TaxConfigRevision(organization_id=org_id, revision=revision, source=source, summary=summary, changed_by=user_id)
    )
    await session.flush()
    return revision


def snapshot_from_entries(as_of: date, revision: int, entries: Iterable[TaxConfigEntry]) -> ConfigSnapshot:
    return ConfigSnapshot.from_raw(
        as_of, revision, ((row.kind, row.code, row.effective_from, row.effective_to, row.data) for row in entries)
    )


async def ensure_tax_config(session: AsyncSession, org_id: uuid.UUID, user_id: Optional[uuid.UUID] = None) -> None:
    """Start an organization's configuration from the default packs, once."""
    started = await session.execute(
        select(TaxPackApplication.id).where(TaxPackApplication.organization_id == org_id).limit(1)
    )
    if started.first() is not None:
        return
    # Imported here: the applier itself uses this module.
    from finance.packs import get_pack
    from finance.packs.applier import apply_pack

    for pack_code in settings.default_tax_pack_codes:
        await apply_pack(session, org_id, get_pack(pack_code), user_id=user_id, today=date.today())


async def load_snapshot(session: AsyncSession, org_id: uuid.UUID, as_of: date) -> ConfigSnapshot:
    await ensure_tax_config(session, org_id)
    entries = await load_entries(session, org_id)
    return snapshot_from_entries(as_of, await current_revision(session, org_id), entries)


def check_no_overlaps(entries: Iterable[TaxConfigEntry]) -> None:
    clashes = find_overlaps((row.kind, row.code, row.effective_from, row.effective_to) for row in entries)
    if clashes:
        raise TaxConfigError(
            "TAX_CONFIG_OVERLAP",
            "Two entries of the same kind and code would be in effect on the same day.",
            meta={"entries": [{"kind": kind, "code": code} for kind, code in clashes]},
        )
