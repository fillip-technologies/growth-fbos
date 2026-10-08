"""
The global permission catalog (`<service>.<entity>.<action>`) and the presets wired to it.

Shared by the seed script, org bootstrap and tests so the catalog has one definition.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.rbac import Permission, Role, RoleAssignment, RolePermission
from models.user_permission import UserPermission

PERMISSION_CATALOG: list[tuple[str, str, str]] = [
    # Users
    ("identity.user.read", "identity", "Read user profiles"),
    ("identity.user.create", "identity", "Invite users and resend invitations"),
    ("identity.user.update", "identity", "Update user profiles"),
    ("identity.user.deactivate", "identity", "Deactivate users"),
    # Per-user access
    ("identity.user_permission.read", "identity", "View the permissions granted to users"),
    ("identity.user_permission.manage", "identity", "Grant and revoke user permissions"),
    # Roles (permission presets)
    ("identity.role.read", "identity", "Read roles and the permission catalog"),
    ("identity.role.create", "identity", "Create custom roles"),
    ("identity.role.update", "identity", "Change a custom role's permissions"),
    ("identity.role_assignment.read", "identity", "List roles applied to users"),
    ("identity.role_assignment.create", "identity", "Apply a role preset to a user"),
    ("identity.role_assignment.delete", "identity", "Remove a role preset from a user"),
    # Company structure (branches, departments, teams)
    ("identity.org_unit.read", "identity", "View the company structure"),
    ("identity.org_unit.create", "identity", "Add branches, departments and teams"),
    ("identity.org_unit.update", "identity", "Edit branches, departments and teams"),
    ("identity.org_unit.move", "identity", "Move departments and teams"),
    ("identity.calendar.read", "identity", "Read working calendars"),
    ("identity.calendar.create", "identity", "Create working calendars"),
    ("identity.calendar.update", "identity", "Update working calendars"),
    ("identity.field_definition.read", "identity", "Read custom field schemas"),
    ("identity.field_definition.create", "identity", "Create custom field schemas"),
    ("identity.field_definition.publish", "identity", "Publish custom field schemas"),
    ("identity.vertical.manage", "identity", "Create, rename and archive the client's verticals"),
    ("identity.vertical_pack.manage", "identity", "Design vertical packs and publish their versions"),
    ("identity.vertical_pack.install", "identity", "Install vertical packs in the organization"),
    ("identity.session.read", "identity", "View where users are signed in"),
    ("identity.session.revoke", "identity", "Sign users out of their sessions"),
    ("identity.audit_log.read", "identity", "Read the security audit log"),
    # Other services
    ("revenue.deal.read", "revenue", "View deals"),
    ("revenue.deal.create", "revenue", "Create deals"),
    ("revenue.lead.read", "revenue", "View leads"),
    ("revenue.lead.write", "revenue", "Add, update, disqualify and convert leads"),
    ("revenue.opportunity.read", "revenue", "View opportunities and their quotations"),
    ("revenue.opportunity.write", "revenue", "Work opportunities and prepare, send and close quotations"),
    ("revenue.quotation.approve", "revenue", "Approve quotations held for a large discount"),
    ("revenue.contract.read", "revenue", "View contracts"),
    ("revenue.contract.write", "revenue", "Create and activate contracts"),
    ("revenue.offering.read", "revenue", "View the offerings catalog"),
    ("revenue.offering.write", "revenue", "Add offerings to the catalog"),
    ("revenue.activity.read", "revenue", "View calls, meetings and notes logged on sales records"),
    ("revenue.activity.write", "revenue", "Log calls, meetings and notes on sales records"),
    ("revenue.invoice.read", "revenue", "View invoices and credit notes"),
    ("revenue.invoice.write", "revenue", "Draft and issue invoices and raise credit notes"),
    ("revenue.payment.read", "revenue", "View payments received"),
    ("revenue.payment.write", "revenue", "Record payments and allocate them to invoices"),
    ("revenue.collection.read", "revenue", "View collection cases for overdue invoices"),
    ("revenue.collection.write", "revenue", "Log collection follow-ups and refresh overdue cases"),
    ("revenue.client.read", "revenue", "View customers and their contacts"),
    ("revenue.client.write", "revenue", "Add and edit customers and their contacts"),
    ("revenue.client_service.read", "revenue", "View the outside services clients use"),
    ("revenue.client_service.write", "revenue", "Add, edit and delete client services, providers and categories"),
    # Delivery: projects (work units), tasks, time, handovers and workflows
    ("delivery.work_unit.read", "delivery", "View projects with their milestones, team, risks and change requests (own records only: the projects you manage, are on or have tasks in)"),
    ("delivery.work_unit.write", "delivery", "Create and update projects, milestones, team, risks and change requests"),
    ("delivery.change_request.approve", "delivery", "Approve or reject project change requests"),
    ("delivery.task.read", "delivery", "View tasks and work on the ones assigned to you (own records only: just the tasks you're assigned, review or created)"),
    ("delivery.task.write", "delivery", "Create, edit, assign, block and cancel tasks and set up recurring tasks"),
    ("delivery.task.review", "delivery", "Review submitted tasks even when you aren't the named reviewer"),
    ("delivery.task.request", "delivery", "Ask other teams for work they take requests for, and follow your own requests"),
    ("delivery.time_entry.read", "delivery", "View the time everyone has logged"),
    ("delivery.handover.read", "delivery", "View handovers of work between teams"),
    ("delivery.handover.write", "delivery", "Request, accept and reject handovers of work between teams"),
    ("delivery.template.manage", "delivery", "Manage delivery setup: its settings, project types, project templates, task types and task templates"),
    ("delivery.workflow.read", "delivery", "View workflows and where each project is in them"),
    ("delivery.workflow.manage", "delivery", "Design workflows and publish their versions"),
    ("delivery.workflow.operate", "delivery", "Start workflows and move them between stages"),
    ("delivery.workflow.approve", "delivery", "Approve or reject workflow steps that need approval"),
    ("control.approval.read", "control", "View approval requests and policies, decide the requests waiting for you and delegate your own approvals (own records only: just the requests you raised or are asked to decide)"),
    ("control.approval.write", "control", "Raise approval requests and cancel the ones you raised"),
    ("control.approval.manage", "control", "Set up approval policies and cancel anyone's approval request"),
    ("control.sla.read", "control", "View SLA policies, clocks and escalations"),
    ("control.sla.write", "control", "Request SLA exceptions and acknowledge escalations"),
    ("control.sla.manage", "control", "Set up SLA policies"),
    ("document.read", "documents", "Read documents"),
    ("document.upload", "documents", "Upload documents and attach them to records"),
    ("document.share", "documents", "Share documents with people outside FBOS"),
    ("document.category.manage", "documents", "Set up the organization's document categories"),
]

ADMIN_ROLE_CODE = "admin"
MEMBER_ROLE_CODE = "member"


# Reads the `member` preset leaves out: other people's security data (sign-in places, IP
# addresses), and approval requests, which show deals, discounts and costs across the
# company (grant that one per person, "own records only" for people who just decide).
SENSITIVE_READ_CODES = {"identity.session.read", "identity.audit_log.read", "control.approval.read"}


# Beyond reading, what every member may do: ask another team for work (delivery routes it).
MEMBER_ACTION_CODES = {"delivery.task.request"}


def member_permission_codes(catalog_codes: list[str]) -> list[str]:
    """The `member` preset is read access (minus other people's security data), plus sending requests."""
    return [
        code for code in catalog_codes
        if (code.endswith(".read") and code not in SENSITIVE_READ_CODES) or code in MEMBER_ACTION_CODES
    ]


async def ensure_permission_catalog(session: AsyncSession) -> list[str]:
    """
    Insert missing catalog entries, keep descriptions as worded here, and keep every org's
    `admin` preset at the full catalog.

    Codes added by this call are also granted (organization-wide) to users who hold the
    `admin` preset, so existing org admins keep full access when the catalog grows; the
    added member codes (reads, sending requests) likewise join every `member` preset (see
    `_top_up_member_presets`).
    Codes that already existed are never re-granted, so individual revocations stick.
    Returns the newly added codes.
    """
    existing = {p.code: p for p in (await session.execute(select(Permission))).scalars().all()}
    added = [code for code, _, _ in PERMISSION_CATALOG if code not in existing]
    for code, service, description in PERMISSION_CATALOG:
        if code in added:
            session.add(Permission(code=code, service=service, description=description))
        elif existing[code].description != description:
            existing[code].description = description
    await session.flush()

    catalog_codes = set(existing) | set(added)
    admin_roles = (
        await session.execute(select(Role).where(Role.code == ADMIN_ROLE_CODE, Role.is_system.is_(True)))
    ).scalars().all()
    for role in admin_roles:
        held = {rp.permission_code for rp in role.role_permissions}
        for code in sorted(catalog_codes - held):
            session.add(RolePermission(role_id=role.id, permission_code=code))
    await session.flush()

    if added and admin_roles:
        admin_holders = (
            await session.execute(
                select(RoleAssignment.user_id, RoleAssignment.organization_id).where(
                    RoleAssignment.role_id.in_([r.id for r in admin_roles]),
                    RoleAssignment.scope_unit_id.is_(None),
                )
            )
        ).all()
        for user_id, organization_id in set(admin_holders):
            for code in added:
                session.add(UserPermission(
                    organization_id=organization_id, user_id=user_id, permission_code=code,
                    source_role_id=None, self_only=False,
                ))
        await session.flush()

    await _top_up_member_presets(session, member_permission_codes(added))
    return added


async def _top_up_member_presets(session: AsyncSession, new_member_codes: list[str]) -> None:
    """
    New member codes (`member_permission_codes`) join every org's `member` preset and reach
    the users holding it, in the scope (and with the self-only limit and expiry) each was
    given it. Organizations get their `member` preset when they are created, so without this
    a service whose permissions arrive later would stay closed to every existing member.
    """
    if not new_member_codes:
        return
    member_role_ids = (
        await session.execute(select(Role.id).where(Role.code == MEMBER_ROLE_CODE))
    ).scalars().all()
    if not member_role_ids:
        return

    for role_id in member_role_ids:
        for code in new_member_codes:
            session.add(RolePermission(role_id=role_id, permission_code=code))

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like the column
    current_assignments = (
        await session.execute(
            select(
                RoleAssignment.organization_id,
                RoleAssignment.user_id,
                RoleAssignment.role_id,
                RoleAssignment.scope_unit_id,
                RoleAssignment.self_only,
                RoleAssignment.valid_to,
            ).where(
                RoleAssignment.role_id.in_(member_role_ids),
                RoleAssignment.valid_to.is_(None) | (RoleAssignment.valid_to > now),
            )
        )
    ).all()

    # A user may already hold one of these codes in the same scope: from the admin top-up
    # above, or from the `member` preset applied twice. Grants are unique per scope.
    granted = set(
        (
            await session.execute(
                select(UserPermission.user_id, UserPermission.permission_code, UserPermission.scope_unit_id).where(
                    UserPermission.permission_code.in_(new_member_codes)
                )
            )
        ).all()
    )
    for assignment in current_assignments:
        for code in new_member_codes:
            grant_key = (assignment.user_id, code, assignment.scope_unit_id)
            if grant_key in granted:
                continue
            granted.add(grant_key)
            session.add(UserPermission(
                organization_id=assignment.organization_id,
                user_id=assignment.user_id,
                permission_code=code,
                scope_unit_id=assignment.scope_unit_id,
                self_only=assignment.self_only,
                source_role_id=assignment.role_id,
                valid_to=assignment.valid_to,
            ))
    await session.flush()
