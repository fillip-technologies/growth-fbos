import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import DeviceToken, NotificationPreference
from schemas.preferences import (
    DeviceTokenCreate,
    NotificationPreferenceItem,
    PreferencesReplace,
    QuietHours,
)


def _to_pref_item(pref: NotificationPreference) -> NotificationPreferenceItem:
    quiet_hours = None
    if pref.quiet_hours:
        quiet_hours = QuietHours(**pref.quiet_hours)
    return NotificationPreferenceItem(
        event_category=pref.event_category,
        channel_type=pref.channel_type,
        enabled=pref.enabled,
        digest=pref.digest,
        quiet_hours=quiet_hours,
    )


async def get_preferences(session: AsyncSession, user_id: uuid.UUID) -> PreferencesReplace:
    res = await session.execute(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    prefs = res.scalars().all()
    return PreferencesReplace(preferences=[_to_pref_item(p) for p in prefs])


async def replace_preferences(
    session: AsyncSession, user_id: uuid.UUID, data: PreferencesReplace
) -> PreferencesReplace:
    existing_res = await session.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    for existing in existing_res.scalars().all():
        await session.delete(existing)
    await session.flush()

    for item in data.preferences:
        session.add(
            NotificationPreference(
                user_id=user_id,
                event_category=item.event_category,
                channel_type=item.channel_type,
                enabled=item.enabled,
                digest=item.digest,
                quiet_hours=item.quiet_hours.model_dump() if item.quiet_hours else None,
            )
        )
    await session.flush()
    return data


async def register_device_token(
    session: AsyncSession, user_id: uuid.UUID, data: DeviceTokenCreate
) -> None:
    # Upsert: delete existing token string if already registered to another user
    existing_res = await session.execute(
        select(DeviceToken).where(DeviceToken.token == data.token)
    )
    existing = existing_res.scalars().first()
    if existing:
        await session.delete(existing)
        await session.flush()

    session.add(DeviceToken(user_id=user_id, platform=data.platform, token=data.token))
    await session.flush()
