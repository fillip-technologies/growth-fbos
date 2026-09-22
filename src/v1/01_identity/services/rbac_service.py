from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    DuplicateCodeError,
    IdentityServiceError,
    OrgUnitNotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    RoleAssignmentNotFoundError,
    RoleIsSystemError,
    RoleNotFoundError,
    UserNotFoundError,
)
from models.org_unit import OrgUnit
from models.rbac import Permission, Role, RoleAssignment, RolePermission
from models.user import User
from models.vertical import Vertical
from schemas.common import PageInfo, PaginatedResponse
from schemas.rbac import (
    GrantItem,
    GrantsResponse,
    OrgUnitRef,
    PermissionResponse,
    RoleAssignmentCreate,
    RoleAssignmentResponse,
    RoleCreate,
    RolePermissionsReplace,
    RoleRef,
    RoleResponse,
    UserRef,
    VerticalRef,
)
from services.event_publisher import event_publisher

logger = logging.getLogger("identity.rbac_service")


class RbacService:
    def _build_role_response(self, role: Role) -> RoleResponse:
        permissions = [rp.permission_code for rp in role.role_permissions] if role.role_permissions else []
        return RoleResponse(
            id=role.id,
            code=role.code,
            name=role.name,
            is_system=role.is_system,
            permissions=permissions,
        )

    def _build_role_assignment_response(self, assignment: RoleAssignment) -> RoleAssignmentResponse:
        user_ref = UserRef(
            id=assignment.user.id,
            name=assignment.user.name,
            avatar_url=None,
        )
        role_ref = RoleRef(
            id=assignment.role.id,
            code=assignment.role.code,
            name=assignment.role.name,
        )
        scope_unit_ref = (
            OrgUnitRef(id=assignment.scope_unit.id, name=assignment.scope_unit.name)
            if assignment.scope_unit
            else None
        )
        scope_vert_ref = (
            VerticalRef(id=assignment.scope_vertical.id, name=assignment.scope_vertical.name)
            if assignment.scope_vertical
            else None
        )
        granted_by_ref = (
            UserRef(id=assignment.granted_by.id, name=assignment.granted_by.name)
            if assignment.granted_by
            else None
        )

        return RoleAssignmentResponse(
            id=assignment.id,
            user=user_ref,
            role=role_ref,
            scope_unit=scope_unit_ref,
            scope_vertical=scope_vert_ref,
            self_only=assignment.self_only,
            valid_from=assignment.valid_from,
            valid_to=assignment.valid_to,
            granted_by=granted_by_ref,
        )

    async def list_roles(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[RoleResponse]:
        query = (
            select(Role)
            .options(selectinload(Role.role_permissions))
            .where((Role.organization_id == organization_id) | (Role.is_system == True))
        )

        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(Role, attr):
                        query = query.order_by(getattr(Role, attr).desc())
                else:
                    if hasattr(Role, field):
                        query = query.order_by(getattr(Role, field).asc())
        else:
            query = query.order_by(Role.is_system.desc(), Role.name.asc(), Role.id.asc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        roles = list(result.scalars().all())

        has_more = len(roles) > limit
        if has_more:
            roles = roles[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [self._build_role_response(r) for r in roles]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def create_role(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: RoleCreate,
    ) -> RoleResponse:
        existing = await session.execute(
            select(Role).where(
                Role.organization_id == organization_id,
                func.lower(Role.code) == data.code.lower(),
            )
        )
        if existing.scalar_one_or_none():
            raise DuplicateCodeError(data.code)

        role = Role(
            id=uuid.uuid4(),
            organization_id=organization_id,
            code=data.code,
            name=data.name,
            is_system=False,
            version=1,
        )
        session.add(role)

        for perm_code in data.permissions:
            perm_record = RolePermission(role_id=role.id, permission_code=perm_code)
            session.add(perm_record)

        await session.commit()
        await session.refresh(role)

        # Reload permissions
        stmt = select(Role).options(selectinload(Role.role_permissions)).where(Role.id == role.id)
        role = (await session.execute(stmt)).scalar_one()

        await event_publisher.publish(
            "identity.role.created.v1",
            {
                "role_id": str(role.id),
                "organization_id": str(organization_id),
                "code": role.code,
                "name": role.name,
            },
        )

        return self._build_role_response(role)

    async def replace_role_permissions(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        role_id: uuid.UUID,
        data: RolePermissionsReplace,
        if_match: Optional[str] = None,
    ) -> RoleResponse:
        if if_match is None:
            raise PreconditionRequiredError()

        stmt = select(Role).options(selectinload(Role.role_permissions)).where(Role.id == role_id)
        result = await session.execute(stmt)
        role = result.scalar_one_or_none()
        if not role:
            raise RoleNotFoundError()

        if role.is_system:
            raise RoleIsSystemError()

        if role.organization_id != organization_id:
            raise RoleNotFoundError()

        clean_match = if_match.strip(' "')
        if clean_match.isdigit() and int(clean_match) != role.version:
            raise PreconditionFailedError(
                f"ETag mismatch. Current version is '{role.version}'"
            )

        # Delete existing permissions
        await session.execute(
            delete(RolePermission).where(RolePermission.role_id == role.id)
        )

        # Add new permissions
        for perm_code in data.permissions:
            session.add(RolePermission(role_id=role.id, permission_code=perm_code))

        role.version += 1
        await session.commit()
        await session.refresh(role)

        # Reload permissions
        stmt = select(Role).options(selectinload(Role.role_permissions)).where(Role.id == role.id)
        role = (await session.execute(stmt)).scalar_one()

        await event_publisher.publish(
            "identity.role.updated.v1",
            {
                "role_id": str(role.id),
                "organization_id": str(organization_id),
                "version": role.version,
            },
        )

        return self._build_role_response(role)

    async def list_permissions(
        self,
        session: AsyncSession,
        service: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[PermissionResponse]:
        query = select(Permission)

        if service:
            query = query.where(Permission.service == service)

        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(Permission, attr):
                        query = query.order_by(getattr(Permission, attr).desc())
                else:
                    if hasattr(Permission, field):
                        query = query.order_by(getattr(Permission, field).asc())
        else:
            query = query.order_by(Permission.service.asc(), Permission.code.asc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        perms = list(result.scalars().all())

        has_more = len(perms) > limit
        if has_more:
            perms = perms[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [
            PermissionResponse(
                code=p.code,
                service=p.service,
                description=p.description,
            )
            for p in perms
        ]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def list_role_assignments(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        scope_unit_id: Optional[uuid.UUID] = None,
        active: Optional[bool] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[RoleAssignmentResponse]:
        query = (
            select(RoleAssignment)
            .options(
                selectinload(RoleAssignment.user),
                selectinload(RoleAssignment.role),
                selectinload(RoleAssignment.scope_unit),
                selectinload(RoleAssignment.scope_vertical),
                selectinload(RoleAssignment.granted_by),
            )
            .where(RoleAssignment.organization_id == organization_id)
        )

        if user_id:
            query = query.where(RoleAssignment.user_id == user_id)

        if scope_unit_id:
            query = query.where(RoleAssignment.scope_unit_id == scope_unit_id)

        if active is True:
            now = datetime.now(timezone.utc)
            query = query.where(
                (RoleAssignment.valid_to.is_(None)) | (RoleAssignment.valid_to > now)
            )

        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(RoleAssignment, attr):
                        query = query.order_by(getattr(RoleAssignment, attr).desc())
                else:
                    if hasattr(RoleAssignment, field):
                        query = query.order_by(getattr(RoleAssignment, field).asc())
        else:
            query = query.order_by(RoleAssignment.valid_from.desc(), RoleAssignment.id.desc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        assignments = list(result.scalars().all())

        has_more = len(assignments) > limit
        if has_more:
            assignments = assignments[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [self._build_role_assignment_response(a) for a in assignments]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def create_role_assignment(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: RoleAssignmentCreate,
        granted_by_id: Optional[uuid.UUID] = None,
    ) -> RoleAssignmentResponse:
        user = await session.get(User, data.user_id)
        if not user or user.organization_id != organization_id:
            raise UserNotFoundError()

        role = await session.get(Role, data.role_id)
        if not role or (not role.is_system and role.organization_id != organization_id):
            raise RoleNotFoundError()

        scope_path: Optional[str] = None
        if data.scope_unit_id:
            unit = await session.get(OrgUnit, data.scope_unit_id)
            if not unit or unit.organization_id != organization_id:
                raise OrgUnitNotFoundError()
            scope_path = unit.path

        if data.scope_vertical_id:
            vert = await session.get(Vertical, data.scope_vertical_id)
            if not vert:
                raise IdentityServiceError(
                    status_code=422,
                    code="VERTICAL_NOT_FOUND",
                    message="Vertical not found",
                )

        assignment_id = uuid.uuid4()
        assignment = RoleAssignment(
            id=assignment_id,
            organization_id=organization_id,
            user_id=data.user_id,
            role_id=data.role_id,
            scope_unit_id=data.scope_unit_id,
            scope_vertical_id=data.scope_vertical_id,
            scope_path=scope_path,
            self_only=data.self_only,
            valid_from=datetime.now(timezone.utc),
            valid_to=data.valid_to,
            granted_by_id=granted_by_id,
            reason=data.reason,
        )
        session.add(assignment)
        await session.commit()

        # Reload with joined relations
        stmt = (
            select(RoleAssignment)
            .options(
                selectinload(RoleAssignment.user),
                selectinload(RoleAssignment.role),
                selectinload(RoleAssignment.scope_unit),
                selectinload(RoleAssignment.scope_vertical),
                selectinload(RoleAssignment.granted_by),
            )
            .where(RoleAssignment.id == assignment_id)
        )
        assignment = (await session.execute(stmt)).scalar_one()

        await event_publisher.publish(
            "identity.role.assigned.v1",
            {
                "assignment_id": str(assignment.id),
                "user_id": str(assignment.user_id),
                "role_id": str(assignment.role_id),
                "scope_unit_id": str(assignment.scope_unit_id) if assignment.scope_unit_id else None,
                "scope_path": assignment.scope_path,
            },
        )

        return self._build_role_assignment_response(assignment)

    async def revoke_role_assignment(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        assignment_id: uuid.UUID,
        reason: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> None:
        assignment = await session.get(RoleAssignment, assignment_id)
        if not assignment or assignment.organization_id != organization_id:
            raise RoleAssignmentNotFoundError()

        user_id = assignment.user_id
        role_id = assignment.role_id

        await session.delete(assignment)
        await session.commit()

        await event_publisher.publish(
            "identity.role.revoked.v1",
            {
                "assignment_id": str(assignment_id),
                "user_id": str(user_id),
                "role_id": str(role_id),
                "reason": reason,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )

    async def get_effective_grants(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> GrantsResponse:
        user = await session.get(User, user_id)
        if not user:
            raise UserNotFoundError()

        now = datetime.now(timezone.utc)
        stmt = (
            select(RoleAssignment)
            .options(
                selectinload(RoleAssignment.role).selectinload(Role.role_permissions)
            )
            .where(
                RoleAssignment.user_id == user_id,
                (RoleAssignment.valid_to.is_(None)) | (RoleAssignment.valid_to > now),
            )
        )
        result = await session.execute(stmt)
        assignments = result.scalars().all()

        grants: list[GrantItem] = []
        for a in assignments:
            if a.role and a.role.role_permissions:
                for rp in a.role.role_permissions:
                    grants.append(
                        GrantItem(
                            permission=rp.permission_code,
                            scope_path=a.scope_path,
                            vertical_id=a.scope_vertical_id,
                            self_only=a.self_only,
                        )
                    )

        return GrantsResponse(
            user_id=user.id,
            organization_id=user.organization_id,
            grants=grants,
            computed_at=now,
            ttl_seconds=300,
        )


rbac_service = RbacService()
