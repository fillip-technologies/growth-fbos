"""
Which verticals (industries) a branch or department works in.

A branch or department may set its own verticals; one that sets none inherits from the
nearest parent that does. Teams never set their own: they always follow their department.
Inheritance follows the materialized `path`, so moving a unit needs no extra bookkeeping.
"""
from typing import Iterable, Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import OrgUnitNotFoundError, ValidationFailedError
from models.org_unit import OrgUnit, OrgUnitVertical
from models.organization import Organization
from models.vertical import Vertical
from schemas.org_unit import InheritedFromRef, OrgUnitVerticalsResponse, UnitVerticalRef
from services.event_publisher import event_publisher

UNIT_TYPES_WITH_OWN_VERTICALS = {"branch", "department"}


def path_unit_ids(unit: OrgUnit) -> list[uuid.UUID]:
    """The unit's ancestors and itself, root first ("/branch/dept/team/")."""
    return [uuid.UUID(part) for part in unit.path.strip("/").split("/") if part]


def _ref(vertical: Vertical) -> UnitVerticalRef:
    return UnitVerticalRef(id=vertical.id, name=vertical.name, status=vertical.status)


class OrgUnitVerticalService:
    async def own_vertical_ids(
        self, session: AsyncSession, unit_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """unit id -> the vertical ids set on that unit itself (one query for many units)."""
        ids = list(unit_ids)
        if not ids:
            return {}
        result = await session.execute(
            select(OrgUnitVertical.org_unit_id, OrgUnitVertical.vertical_id).where(OrgUnitVertical.org_unit_id.in_(ids))
        )
        own: dict[uuid.UUID, list[uuid.UUID]] = {}
        for unit_id, vertical_id in result.all():
            own.setdefault(unit_id, []).append(vertical_id)
        return own

    async def _get_unit(self, session: AsyncSession, organization_id: uuid.UUID, unit_id: uuid.UUID) -> OrgUnit:
        unit = await session.get(OrgUnit, unit_id)
        if not unit or unit.organization_id != organization_id:
            raise OrgUnitNotFoundError()
        return unit

    async def _verticals(self, session: AsyncSession, vertical_ids: Iterable[uuid.UUID]) -> list[Vertical]:
        ids = list(vertical_ids)
        if not ids:
            return []
        result = await session.execute(select(Vertical).where(Vertical.id.in_(ids)).order_by(Vertical.name))
        return list(result.scalars().all())

    async def resolve(self, session: AsyncSession, unit: OrgUnit) -> OrgUnitVerticalsResponse:
        chain = path_unit_ids(unit)
        own_by_unit = await self.own_vertical_ids(session, chain)
        own = await self._verticals(session, own_by_unit.get(unit.id, []))

        # Nearest unit on the path (itself first) that sets any verticals wins.
        source_id: Optional[uuid.UUID] = next((uid for uid in reversed(chain) if own_by_unit.get(uid)), None)
        effective = await self._verticals(session, own_by_unit.get(source_id, [])) if source_id else []

        inherited_from = None
        if source_id and source_id != unit.id:
            source = await session.get(OrgUnit, source_id)
            inherited_from = InheritedFromRef(id=source.id, name=source.name, unit_type=source.unit_type)

        return OrgUnitVerticalsResponse(
            unit_id=unit.id,
            own=[_ref(v) for v in own],
            effective=[_ref(v) for v in effective if v.status == "active"],
            inherited_from=inherited_from,
        )

    async def get_unit_verticals(
        self, session: AsyncSession, organization_id: uuid.UUID, unit_id: uuid.UUID
    ) -> OrgUnitVerticalsResponse:
        return await self.resolve(session, await self._get_unit(session, organization_id, unit_id))

    async def effective_vertical_ids(
        self, session: AsyncSession, organization_id: uuid.UUID, unit_id: uuid.UUID
    ) -> list[uuid.UUID]:
        resolved = await self.get_unit_verticals(session, organization_id, unit_id)
        return [v.id for v in resolved.effective]

    async def replace_unit_verticals(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        unit_id: uuid.UUID,
        vertical_ids: list[uuid.UUID],
    ) -> OrgUnitVerticalsResponse:
        unit = await self._get_unit(session, organization_id, unit_id)
        if unit.unit_type not in UNIT_TYPES_WITH_OWN_VERTICALS:
            raise ValidationFailedError.for_field(
                "vertical_ids", "Teams follow their department's verticals; set them on the department instead."
            )

        wanted = list(dict.fromkeys(vertical_ids))
        organization = await session.get(Organization, organization_id)
        verticals = await self._verticals(session, wanted)
        found = {v.id: v for v in verticals if v.client_id == organization.client_id}
        errors = [
            {"field": f"vertical_ids[{i}]", "issue": "Unknown vertical"}
            for i, vid in enumerate(wanted)
            if vid not in found
        ]
        current = set((await self.own_vertical_ids(session, [unit.id])).get(unit.id, []))
        # An archived vertical may stay where it already is, but can't be newly added.
        errors += [
            {"field": f"vertical_ids[{i}]", "issue": f"'{found[vid].name}' is archived"}
            for i, vid in enumerate(wanted)
            if vid in found and found[vid].status != "active" and vid not in current
        ]
        if errors:
            raise ValidationFailedError(errors)

        await session.execute(delete(OrgUnitVertical).where(OrgUnitVertical.org_unit_id == unit.id))
        for vertical_id in wanted:
            session.add(OrgUnitVertical(org_unit_id=unit.id, vertical_id=vertical_id))
        await session.commit()

        await event_publisher.publish(
            "identity.org_unit.verticals_changed.v1",
            {
                "org_unit_id": str(unit.id),
                "organization_id": str(organization_id),
                "vertical_ids": [str(v) for v in wanted],
            },
        )
        return await self.resolve(session, unit)


org_unit_vertical_service = OrgUnitVerticalService()
