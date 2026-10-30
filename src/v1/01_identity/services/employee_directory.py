"""
Active employee users of an organization, as People asks for them when it creates employee
records from existing users. Only `user_type = employee` with `status = active` ever qualifies.
"""
from typing import Optional
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from schemas.rbac import EmployeeRef, EmployeesResponse

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
    data = [
        EmployeeRef(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            employee_code=user.employee_code,
            manager_user_id=user.manager_user_id,
            home_unit_id=user.home_unit_id,
        )
        for user in users[:limit]
    ]
    return EmployeesResponse(data=data, has_more=len(users) > limit)
