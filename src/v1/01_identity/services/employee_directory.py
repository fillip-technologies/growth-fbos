"""
Active employee users of an organization, as People asks for them when it creates employee
records from existing users. Only `user_type = employee` with `status = active` ever qualifies.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.rbac import Role, RoleAssignment
from models.user import User
from schemas.rbac import EmployeeRef, EmployeeRole, EmployeesResponse

EMPLOYEE_USER_TYPE = "employee"
ACTIVE_STATUS = "active"


async def active_employees(
    session: AsyncSession,
    organization_id: uuid.UUID,
    search: Optional[str],
    user_ids: Optional[list[uuid.UUID]],
    limit: int,
    offset: int,
) -> EmployeesResponse:
    """One page of the organization's active employees by name, narrowed by `search` and `user_ids`."""
    query = select(User).where(
        User.organization_id == organization_id,
        User.user_type == EMPLOYEE_USER_TYPE,
        User.status == ACTIVE_STATUS,
    )
    if user_ids:
        query = query.where(User.id.in_(user_ids))
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(User.name.ilike(term), User.email.ilike(term), User.employee_code.ilike(term)))

    users = (await session.execute(query.order_by(User.name, User.id).offset(offset).limit(limit + 1))).scalars().all()
    roles = await _roles_of(session, [user.id for user in users[:limit]])
    data = [
        EmployeeRef(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            employee_code=user.employee_code,
            manager_user_id=user.manager_user_id,
            home_unit_id=user.home_unit_id,
            roles=roles.get(user.id, []),
        )
        for user in users[:limit]
    ]
    return EmployeesResponse(data=data, has_more=len(users) > limit)


async def _roles_of(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[EmployeeRole]]:
    """
    The roles applied to each user and still in force, earliest first. Roles another service manages
    (`source` set: People's, from a job) are left out: they follow the job, they are not the user's role.
    """
    if not user_ids:
        return {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = await session.execute(
        select(RoleAssignment.user_id, Role.code, Role.name)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(
            RoleAssignment.user_id.in_(user_ids),
            RoleAssignment.source.is_(None),
            or_(RoleAssignment.valid_to.is_(None), RoleAssignment.valid_to > now),
        )
        .order_by(RoleAssignment.valid_from, Role.code)
    )
    roles: dict[uuid.UUID, list[EmployeeRole]] = {}
    for user_id, code, name in rows:
        held = roles.setdefault(user_id, [])
        if code not in {role.code for role in held}:
            held.append(EmployeeRole(code=code, name=name or code))
    return roles
