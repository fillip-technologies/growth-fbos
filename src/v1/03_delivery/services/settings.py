"""
An organization's delivery settings (models/settings.py). No row means every setting is at its
default; the first change creates it.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import VersionConflictError
from models.settings import DeliverySettings
from schemas.settings import DeliverySettingsResponse, DeliverySettingsUpdate
from services.refs import user_ref
from services.versions import check_if_match


async def _settings_row(session: AsyncSession, org_id: uuid.UUID) -> Optional[DeliverySettings]:
    return await session.get(DeliverySettings, org_id)


def _response(row: Optional[DeliverySettings]) -> DeliverySettingsResponse:
    if row is None:
        return DeliverySettingsResponse(team_assignment_only=False, team_visibility=False, team_alerts=False, version=0)
    return DeliverySettingsResponse(
        team_assignment_only=row.team_assignment_only,
        team_visibility=row.team_visibility,
        team_alerts=row.team_alerts,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=user_ref(row.updated_by),
    )


async def get_settings(session: AsyncSession, org_id: uuid.UUID) -> DeliverySettingsResponse:
    return _response(await _settings_row(session, org_id))


async def team_assignment_only(session: AsyncSession, org_id: uuid.UUID) -> bool:
    row = await _settings_row(session, org_id)
    return row is not None and row.team_assignment_only


async def team_visibility(session: AsyncSession, org_id: uuid.UUID) -> bool:
    row = await _settings_row(session, org_id)
    return row is not None and row.team_visibility


async def team_alerts(session: AsyncSession, org_id: uuid.UUID) -> bool:
    row = await _settings_row(session, org_id)
    return row is not None and row.team_alerts


async def update_settings(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: DeliverySettingsUpdate,
    if_match: Optional[str],
) -> DeliverySettingsResponse:
    row = await _settings_row(session, org_id)
    current_version = row.version if row else 0
    check_if_match(if_match, current_version)

    if row is None:
        row = DeliverySettings(organization_id=org_id, team_assignment_only=False, team_visibility=False, team_alerts=False)
        session.add(row)
    if data.team_assignment_only is not None:
        row.team_assignment_only = data.team_assignment_only
    if data.team_visibility is not None:
        row.team_visibility = data.team_visibility
    if data.team_alerts is not None:
        row.team_alerts = data.team_alerts
    row.version = current_version + 1
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Two first changes at once: the other one created the row first.
        raise VersionConflictError(current_version + 1) from exc
    return _response(row)
