import logging
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    DuplicateCodeError,
    IdentityServiceError,
    OrgUnitCycleError,
    OrgUnitHierarchyInvalidError,
    OrgUnitNotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
)
from models.org_unit import OrgUnit
from models.rbac import RoleAssignment
from models.user import User
from schemas.common import PageInfo, PaginatedResponse
from schemas.org_unit import (
    HeadUserRef,
    OrgUnitCreate,
    OrgUnitMoveRequest,
    OrgUnitResponse,
    OrgUnitUpdate,
)
from services.event_publisher import event_publisher

logger = logging.getLogger("identity.org_unit_service")

ALLOWED_PARENTS = {
    "company": [],
    "branch": ["company"],
    "department": ["company", "branch", "department"],
    "team": ["department"],
}


class OrgUnitService:
    def _validate_hierarchy(self, unit_type: Optional[str], parent: Optional[OrgUnit]) -> None:
        if not unit_type:
            return

        allowed = ALLOWED_PARENTS.get(unit_type)
        if allowed is None:
            return

        if unit_type == "company":
            if parent is not None:
                raise OrgUnitHierarchyInvalidError(
                    allowed_parent_types=[],
                    message="A company cannot have a parent unit",
                )
            return

        # For branch, department, team: parent is required
        if parent is None:
            raise OrgUnitHierarchyInvalidError(
                allowed_parent_types=allowed,
                message=f"Unit of type '{unit_type}' requires a parent of type: {', '.join(allowed)}",
            )

        if parent.unit_type not in allowed:
            raise OrgUnitHierarchyInvalidError(
                allowed_parent_types=allowed,
                message=f"A {unit_type} cannot be placed under a {parent.unit_type}. Allowed parent types: {', '.join(allowed)}",
            )

    def _build_response(self, unit: OrgUnit) -> OrgUnitResponse:
        head_user_ref: Optional[HeadUserRef] = None
        if unit.head_user:
            head_user_ref = HeadUserRef(id=unit.head_user.id, name=unit.head_user.name)

        return OrgUnitResponse(
            id=unit.id,
            code=unit.code,
            name=unit.name,
            unit_type=unit.unit_type,
            parent_id=unit.parent_id,
            path=unit.path,
            head_user=head_user_ref,
            calendar_id=unit.calendar_id,
            status=unit.status,
            version=unit.version,
            created_at=unit.created_at,
            updated_at=unit.updated_at,
        )

    async def list_org_units(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        unit_type: Optional[str] = None,
        parent_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        sort: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[OrgUnitResponse]:
        query = (
            select(OrgUnit)
            .options(selectinload(OrgUnit.head_user))
            .where(OrgUnit.organization_id == organization_id)
        )

        if unit_type:
            query = query.where(OrgUnit.unit_type == unit_type)

        if parent_id is not None:
            query = query.where(OrgUnit.parent_id == parent_id)

        if status:
            query = query.where(OrgUnit.status == status)

        if q:
            term = f"%{q}%"
            query = query.where((OrgUnit.name.ilike(term)) | (OrgUnit.code.ilike(term)))

        # Sorting
        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr_name = field[1:]
                    if hasattr(OrgUnit, attr_name):
                        query = query.order_by(getattr(OrgUnit, attr_name).desc())
                else:
                    if hasattr(OrgUnit, field):
                        query = query.order_by(getattr(OrgUnit, field).asc())
        else:
            query = query.order_by(OrgUnit.name.asc(), OrgUnit.id.asc())

        # Cursor pagination via numeric offset
        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        units = list(result.scalars().all())

        has_more = len(units) > limit
        if has_more:
            units = units[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [self._build_response(u) for u in units]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def get_org_unit(
        self, session: AsyncSession, unit_id: uuid.UUID, organization_id: uuid.UUID
    ) -> OrgUnitResponse:
        query = (
            select(OrgUnit)
            .options(selectinload(OrgUnit.head_user))
            .where(OrgUnit.id == unit_id, OrgUnit.organization_id == organization_id)
        )
        result = await session.execute(query)
        unit = result.scalar_one_or_none()
        if not unit:
            raise OrgUnitNotFoundError()

        return self._build_response(unit)

    async def create_org_unit(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: OrgUnitCreate,
    ) -> OrgUnitResponse:
        # Check duplicate code within organization
        existing_code = await session.execute(
            select(OrgUnit).where(
                OrgUnit.organization_id == organization_id,
                func.lower(OrgUnit.code) == data.code.lower(),
            )
        )
        if existing_code.scalar_one_or_none():
            raise DuplicateCodeError(data.code)

        # Parent retrieval and verification
        parent: Optional[OrgUnit] = None
        if data.parent_id is not None:
            parent = await session.get(OrgUnit, data.parent_id)
            if not parent or parent.organization_id != organization_id:
                raise OrgUnitNotFoundError()

        # Validate hierarchy rules
        self._validate_hierarchy(data.unit_type, parent)

        # Verify head_user_id if provided
        head_user: Optional[User] = None
        if data.head_user_id is not None:
            head_user = await session.get(User, data.head_user_id)
            if not head_user or head_user.organization_id != organization_id:
                raise IdentityServiceError(
                    status_code=422,
                    code="USER_NOT_FOUND",
                    message="Head user does not exist in this organization",
                )

        # Calendar inheritance
        calendar_id = data.calendar_id
        if calendar_id is None and parent is not None:
            calendar_id = parent.calendar_id

        unit_id = uuid.uuid4()
        path = f"{parent.path}{unit_id}/" if parent is not None else f"/{unit_id}/"

        unit = OrgUnit(
            id=unit_id,
            organization_id=organization_id,
            code=data.code,
            name=data.name,
            unit_type=data.unit_type,
            parent_id=data.parent_id,
            path=path,
            head_user_id=data.head_user_id,
            calendar_id=calendar_id,
            status="active",
            version=1,
        )
        session.add(unit)
        await session.commit()
        await session.refresh(unit)

        # Manually attach preloaded head_user for response mapping
        unit.head_user = head_user

        await event_publisher.publish(
            "identity.org_unit.created.v1",
            {
                "unit_id": str(unit.id),
                "organization_id": str(organization_id),
                "code": unit.code,
                "name": unit.name,
                "unit_type": unit.unit_type,
                "path": unit.path,
            },
        )

        return self._build_response(unit)

    async def update_org_unit(
        self,
        session: AsyncSession,
        unit_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: OrgUnitUpdate,
        if_match: Optional[str] = None,
    ) -> OrgUnitResponse:
        query = (
            select(OrgUnit)
            .options(selectinload(OrgUnit.head_user))
            .where(OrgUnit.id == unit_id, OrgUnit.organization_id == organization_id)
        )
        result = await session.execute(query)
        unit = result.scalar_one_or_none()
        if not unit:
            raise OrgUnitNotFoundError()

        if if_match is None:
            raise PreconditionRequiredError()

        clean_match = if_match.strip(' "')
        if clean_match.isdigit() and int(clean_match) != unit.version:
            raise PreconditionFailedError(
                f"ETag mismatch. Current version is '{unit.version}'"
            )

        if data.name is not None:
            unit.name = data.name

        if data.head_user_id is not None:
            head_user = await session.get(User, data.head_user_id)
            if not head_user or head_user.organization_id != organization_id:
                raise IdentityServiceError(
                    status_code=422,
                    code="USER_NOT_FOUND",
                    message="Head user does not exist in this organization",
                )
            unit.head_user_id = data.head_user_id
            unit.head_user = head_user

        if data.calendar_id is not None:
            unit.calendar_id = data.calendar_id

        if data.status is not None:
            unit.status = data.status

        unit.version += 1
        await session.commit()
        await session.refresh(unit)

        await event_publisher.publish(
            "identity.org_unit.updated.v1",
            {
                "unit_id": str(unit.id),
                "organization_id": str(organization_id),
                "version": unit.version,
            },
        )

        return self._build_response(unit)

    async def move_org_unit(
        self,
        session: AsyncSession,
        unit_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: OrgUnitMoveRequest,
        if_match: Optional[str] = None,
    ) -> OrgUnitResponse:
        query = (
            select(OrgUnit)
            .options(selectinload(OrgUnit.head_user))
            .where(OrgUnit.id == unit_id, OrgUnit.organization_id == organization_id)
        )
        result = await session.execute(query)
        unit = result.scalar_one_or_none()
        if not unit:
            raise OrgUnitNotFoundError()

        if if_match is None:
            raise PreconditionRequiredError()

        clean_match = if_match.strip(' "')
        if clean_match.isdigit() and int(clean_match) != unit.version:
            raise PreconditionFailedError(
                f"ETag mismatch. Current version is '{unit.version}'"
            )

        if unit.id == data.new_parent_id:
            raise OrgUnitCycleError("Cannot move unit into itself")

        new_parent = await session.get(OrgUnit, data.new_parent_id)
        if not new_parent or new_parent.organization_id != organization_id:
            raise OrgUnitNotFoundError()

        # Prevent cycles: cannot move into own subtree
        if new_parent.path.startswith(unit.path):
            raise OrgUnitCycleError("The new parent is inside the unit's subtree.")

        # Hierarchy validation against new parent
        self._validate_hierarchy(unit.unit_type, new_parent)

        old_prefix = unit.path
        new_prefix = f"{new_parent.path}{unit.id}/"

        unit.parent_id = new_parent.id
        unit.path = new_prefix
        unit.version += 1

        # Rewrite paths of all descendant org units
        descendants_res = await session.execute(
            select(OrgUnit).where(
                OrgUnit.organization_id == organization_id,
                OrgUnit.path.startswith(old_prefix),
                OrgUnit.id != unit.id,
            )
        )
        for desc in descendants_res.scalars().all():
            desc.path = new_prefix + desc.path[len(old_prefix):]

        # Rewrite paths of all role assignments scoped inside this subtree
        assignments_res = await session.execute(
            select(RoleAssignment).where(
                RoleAssignment.scope_path.startswith(old_prefix)
            )
        )
        for assignment in assignments_res.scalars().all():
            if assignment.scope_path:
                assignment.scope_path = new_prefix + assignment.scope_path[len(old_prefix):]

        await session.commit()
        await session.refresh(unit)

        await event_publisher.publish(
            "identity.org_unit.moved.v1",
            {
                "unit_id": str(unit.id),
                "organization_id": str(organization_id),
                "old_path_prefix": old_prefix,
                "new_path_prefix": new_prefix,
                "reason": data.reason,
            },
        )

        return self._build_response(unit)


org_unit_service = OrgUnitService()
