"""
Applying what People declares about an employee's login.

People owns the HR facts (department, manager, employee code, name, phone, who has left) and the
access a job brings; Identity owns the login. This is the one place Identity takes those from
another service, so it needs no acting user: the caller is trusted by its internal token, and a
change made here is recorded without a "granted by" person.

The declaration is the whole truth for what it names, so applying it twice changes nothing.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DuplicateCodeError, PermissionDeniedError, UserNotFoundError, ValidationFailedError
from models.org_unit import OrgUnit
from models.rbac import PEOPLE_SOURCE, Role, RoleAssignment
from models.user import User
from models.user_permission import UserPermission
from schemas.people_sync import (
    AdoptedRole,
    AdoptRolesRequest,
    AdoptRolesResponse,
    CanGrantRequest,
    CanGrantResponse,
    EmploymentApplied,
    EmploymentDeclaration,
    EmploymentState,
    EmploymentSyncResponse,
    ManagedRole,
    ManagedRoleState,
    RoleOption,
    SyncProblem,
)
from schemas.user import RolePresetInput
from services.access_control import Actor, load_grants
from services.event_publisher import event_publisher
from services.rbac_service import rbac_service
from services.user_permission_service import user_permission_service
from services.user_service import user_service

logger = logging.getLogger("identity.people_sync")

STATES_LIMIT = 100

RoleKey = tuple[uuid.UUID, Optional[uuid.UUID]]  # role id, scope unit


async def _load_employee(session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.organization_id != organization_id:
        raise UserNotFoundError()
    return user


async def _roles_by_code(session: AsyncSession, organization_id: uuid.UUID, codes: set[str]) -> dict[str, Role]:
    if not codes:
        return {}
    roles = (
        await session.execute(
            select(Role).where(Role.organization_id == organization_id, func.lower(Role.code).in_(codes))
        )
    ).unique().scalars().all()
    return {role.code.lower(): role for role in roles}


async def _managed_assignments(session: AsyncSession, user_id: uuid.UUID) -> list[RoleAssignment]:
    return list(
        (
            await session.execute(
                select(RoleAssignment).where(RoleAssignment.user_id == user_id, RoleAssignment.source == PEOPLE_SOURCE)
            )
        ).unique().scalars()
    )


async def _apply_placement(
    session: AsyncSession, user: User, declaration: EmploymentDeclaration, applied: EmploymentApplied, problems: list[SyncProblem]
) -> None:
    provided = declaration.model_fields_set

    if "home_unit_id" in provided and declaration.home_unit_id != user.home_unit_id:
        unit = await session.get(OrgUnit, declaration.home_unit_id) if declaration.home_unit_id else None
        if declaration.home_unit_id and (unit is None or unit.organization_id != user.organization_id or unit.status != "active"):
            problems.append(SyncProblem(field="home_unit_id", issue="Unknown or inactive branch, department or team"))
        else:
            await user_service.place_in_unit(session, user, unit)
            applied.fields.append("home_unit_id")

    if "manager_user_id" in provided and declaration.manager_user_id != user.manager_user_id:
        try:
            await user_service.resolve_manager(session, user.organization_id, declaration.manager_user_id, subject_id=user.id)
        except ValidationFailedError as error:
            problems.append(SyncProblem(field="manager_user_id", issue=error.details[0]["issue"]))
        else:
            user.manager_user_id = declaration.manager_user_id
            applied.fields.append("manager_user_id")


async def _apply_profile(
    session: AsyncSession, user: User, declaration: EmploymentDeclaration, applied: EmploymentApplied, problems: list[SyncProblem]
) -> None:
    provided = declaration.model_fields_set
    if "name" in provided and declaration.name is not None and declaration.name != user.name:
        user.name = declaration.name
        applied.fields.append("name")
    if "phone" in provided and declaration.phone != user.phone:
        user.phone = declaration.phone
        applied.fields.append("phone")
    if "employee_code" in provided:
        code = (declaration.employee_code or "").strip() or None
        if (code or "").lower() != (user.employee_code or "").lower():
            try:
                await user_service.assert_employee_code_free(session, user.organization_id, code)
            except DuplicateCodeError:
                problems.append(SyncProblem(field="employee_code", issue=f"Another user already has the code '{code}'"))
            else:
                user.employee_code = code
                applied.fields.append("employee_code")


async def _apply_managed_roles(
    session: AsyncSession, user: User, wanted: list[ManagedRole], applied: EmploymentApplied, problems: list[SyncProblem]
) -> None:
    roles = await _roles_by_code(session, user.organization_id, {w.role_code.lower() for w in wanted})
    desired: dict[RoleKey, ManagedRole] = {}
    for item in wanted:
        role = roles.get(item.role_code.lower())
        if role is None:
            problems.append(SyncProblem(field="managed_roles", issue=f"Unknown role '{item.role_code}'"))
            continue
        if not role.assignable_by_people:
            problems.append(SyncProblem(field="managed_roles", issue=f"{item.role_code}: this role cannot be granted from People"))
            continue
        desired.setdefault((role.id, item.scope_unit_id), item)

    ours = await _managed_assignments(session, user.id)
    ours_by_key: dict[RoleKey, RoleAssignment] = {(a.role_id, a.scope_unit_id): a for a in ours}
    # A problem with one wanted role must not take away a role People already granted for it.
    # A role People may no longer grant is also left as it is: a problem must not take access away.
    unresolved = {w.role_code.lower() for w in wanted} - {code for code, r in roles.items() if r.assignable_by_people}
    protected = {key for key, a in ours_by_key.items() if a.role and a.role.code.lower() in unresolved}

    for key, assignment in ours_by_key.items():
        if key in desired or key in protected:
            continue
        granted, revoked, still = await rbac_service.plan_revocation(session, assignment)
        code = assignment.role.code
        await rbac_service.apply_revocation(session, assignment, granted, revoked, still)
        applied.roles_removed.append(code)

    held_by_hand = {
        (a.role_id, a.scope_unit_id)
        for a in (
            await session.execute(select(RoleAssignment).where(RoleAssignment.user_id == user.id, RoleAssignment.source.is_(None)))
        ).unique().scalars()
    }
    for key, item in desired.items():
        if key in ours_by_key or key in held_by_hand:
            continue  # already there (or granted by hand, which stays as it is)
        try:
            grants, presets = await user_permission_service.resolve(
                session, user.organization_id, permissions=[],
                presets=[RolePresetInput(role_id=key[0], scope_unit_id=key[1])],
            )
        except ValidationFailedError as error:
            problems.append(SyncProblem(field="managed_roles", issue=f"{item.role_code}: {error.details[0]['issue']}"))
            continue
        held = {
            (row.permission_code, row.scope_unit_id)
            for row in (await session.execute(select(UserPermission).where(UserPermission.user_id == user.id))).unique().scalars()
        }
        user_permission_service.add_to_user(
            session, None, user, [g for g in grants if g.key not in held], presets,
            reason="Access that comes with the job, granted from People", source=PEOPLE_SOURCE, source_ref=item.source_ref,
        )
        applied.roles_added.append(item.role_code)
    await session.flush()


async def apply_declaration(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, declaration: EmploymentDeclaration
) -> EmploymentSyncResponse:
    user = await _load_employee(session, organization_id, user_id)
    applied, problems = EmploymentApplied(), []

    if user.user_type != "employee":
        problems.append(SyncProblem(field="user_id", issue="Only employee users are managed by People"))
        return EmploymentSyncResponse(user_id=user.id, status=user.status, applied=applied, problems=problems)

    if user.status == "deactivated":
        if not declaration.deactivate:
            problems.append(SyncProblem(field="user_id", issue="The user is deactivated"))
        return EmploymentSyncResponse(user_id=user.id, status=user.status, applied=applied, problems=problems)

    if declaration.deactivate:
        now = datetime.now(timezone.utc)
        await user_service.deactivate_in_session(session, user, now)
        await session.commit()
        applied.deactivated = True
        await event_publisher.publish(
            "identity.user.deactivated.v1",
            {
                "user_id": str(user.id), "organization_id": str(user.organization_id), "reason": "Left the company",
                "reassign_to_user_id": None, "effective_at": now.isoformat(), "actor_id": None,
            },
        )
        return EmploymentSyncResponse(user_id=user.id, status=user.status, applied=applied, problems=problems)

    await _apply_profile(session, user, declaration, applied, problems)
    await _apply_placement(session, user, declaration, applied, problems)
    if declaration.managed_roles is not None:
        await _apply_managed_roles(session, user, declaration.managed_roles, applied, problems)

    if applied.fields:
        user.version += 1
    await session.commit()
    if applied.fields:
        await event_publisher.publish(
            "identity.user.updated.v1",
            {
                "user_id": str(user.id), "organization_id": str(user.organization_id), "changed": applied.fields,
                "version": user.version, "actor_id": None,
            },
        )
    return EmploymentSyncResponse(user_id=user.id, status=user.status, applied=applied, problems=problems)


async def employment_states(session: AsyncSession, organization_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[EmploymentState]:
    """What Identity holds for these users, in the shape People declares it (for the drift check)."""
    users = (
        await session.execute(
            select(User).where(User.organization_id == organization_id, User.id.in_(user_ids[:STATES_LIMIT])).order_by(User.id)
        )
    ).scalars().all()
    assignments = (
        await session.execute(
            select(RoleAssignment).where(
                RoleAssignment.organization_id == organization_id,
                RoleAssignment.user_id.in_([u.id for u in users]),
                RoleAssignment.source == PEOPLE_SOURCE,
            )
        )
    ).unique().scalars().all()
    roles_of: dict[uuid.UUID, list[ManagedRoleState]] = {}
    for assignment in assignments:
        roles_of.setdefault(assignment.user_id, []).append(
            ManagedRoleState(role_code=assignment.role.code, scope_unit_id=assignment.scope_unit_id)
        )
    return [
        EmploymentState(
            user_id=u.id, status=u.status, name=u.name, phone=u.phone, employee_code=u.employee_code,
            home_unit_id=u.home_unit_id, manager_user_id=u.manager_user_id, managed_roles=roles_of.get(u.id, []),
        )
        for u in users
    ]


async def list_role_options(session: AsyncSession, organization_id: uuid.UUID) -> list[RoleOption]:
    """The roles of the organization, with whether People may grant each (for the role picker)."""
    rows = (
        await session.execute(select(Role).where(Role.organization_id == organization_id).order_by(Role.name, Role.code))
    ).unique().scalars().all()
    return [
        RoleOption(code=r.code, name=r.name or r.code, is_system=r.is_system, assignable_by_people=r.assignable_by_people)
        for r in rows
    ]


async def adopt_roles(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, request: AdoptRolesRequest
) -> AdoptRolesResponse:
    """
    Take over roles the user holds by hand: they become People's, tied to the post that gives them, so a
    later promotion replaces them. Nothing is granted or removed. Repeating it changes nothing.
    """
    user = await _load_employee(session, organization_id, user_id)
    codes = {c.lower() for c in request.role_codes}
    held = (
        await session.execute(
            select(RoleAssignment).where(RoleAssignment.user_id == user.id, RoleAssignment.organization_id == organization_id)
        )
    ).unique().scalars().all()
    adopted: list[AdoptedRole] = []
    found: set[str] = set()
    for assignment in held:
        code = assignment.role.code.lower()
        if code not in codes:
            continue
        if assignment.source is not None and assignment.source != PEOPLE_SOURCE:
            continue  # another service manages it
        found.add(code)
        if assignment.source is None:
            assignment.source = PEOPLE_SOURCE
            assignment.source_ref = request.source_ref
        elif assignment.source_ref != request.source_ref:
            continue
        adopted.append(AdoptedRole(role_code=assignment.role.code, scope_unit_id=assignment.scope_unit_id))
    await session.commit()
    return AdoptRolesResponse(user_id=user.id, adopted=adopted, missing=sorted(codes - found))


async def can_grant(session: AsyncSession, organization_id: uuid.UUID, request: CanGrantRequest) -> CanGrantResponse:
    """Which of these roles the requester could not grant themselves with the access they hold."""
    requester = await _load_employee(session, organization_id, request.requester_user_id)
    if requester.user_type == "client_admin":
        return CanGrantResponse()
    actor = Actor(
        user_id=requester.id, organization_id=organization_id, user_type=requester.user_type,
        name=requester.name, grants=await load_grants(session, requester.id),
    )
    not_grantable: list[str] = []
    for code in request.role_codes:
        try:
            grants, _ = await user_permission_service.resolve(
                session, organization_id, permissions=[],
                presets=[RolePresetInput(role_code=code, scope_unit_id=request.scope_unit_id)],
            )
            user_permission_service.assert_can_grant(actor, grants)
        except (ValidationFailedError, PermissionDeniedError):  # an unknown role, or more than the requester holds
            not_grantable.append(code)
    return CanGrantResponse(not_grantable=not_grantable)
