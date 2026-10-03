"""drop_company_units

The organization is the company, so org units now start at branches and the old
`company` unit type is gone. For every `company` unit this keeps what sits under it
and removes the unit itself:

- its calendar becomes the organization's calendar (when the organization has none);
- its branches move to the top (no parent) and every path below loses the company segment;
- access scoped to the company becomes organization-wide (it covered the whole tree);
- people whose home unit was the company are no longer placed in a unit;
- its head, memberships and verticals go with it.

Refuses to run when a company has a direct child that isn't a branch: that unit has no
valid place in the new structure, so move it under a branch first.

One-way: downgrade does not recreate the removed company units.

Revision ID: b8e4f0a2d3c5
Revises: a7d3e9f1c2b4
Create Date: 2026-10-03 05:45:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


revision: str = 'b8e4f0a2d3c5'
down_revision: Union[str, None] = 'a7d3e9f1c2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _run(conn: Connection, sql: str, **params):
    return conn.execute(sa.text(sql), params)


def _rebase(path: str, company_path: str) -> str:
    """'/<company>/a/b/' -> '/a/b/'"""
    return '/' + path[len(company_path):]


def _refuse_non_branch_children(conn: Connection, company_id: str) -> None:
    misplaced = _run(
        conn,
        "SELECT name, unit_type FROM org_units"
        " WHERE parent_id = :cid AND (unit_type IS NULL OR unit_type <> 'branch')",
        cid=company_id,
    ).all()
    if not misplaced:
        return
    names = ', '.join(f"{name} ({unit_type})" for name, unit_type in misplaced)
    raise RuntimeError(
        f"Company unit {company_id} has direct children that are not branches: {names}. "
        "Move them under a branch, then run the migration again."
    )


def _move_branches_to_top(conn: Connection, company_id: str, company_path: str) -> None:
    _run(conn, "UPDATE org_units SET parent_id = NULL WHERE parent_id = :cid", cid=company_id)
    units_below = _run(
        conn, "SELECT id, path FROM org_units WHERE path LIKE :p AND id <> :cid",
        p=company_path + '%', cid=company_id,
    ).all()
    for unit_id, path in units_below:
        _run(conn, "UPDATE org_units SET path = :path, version = version + 1 WHERE id = :id",
             path=_rebase(path, company_path), id=unit_id)


def _widen_role_assignments(conn: Connection, company_id: str, company_path: str) -> None:
    """Presets applied at the company covered the whole organization; paths below lose the company."""
    _run(conn, "UPDATE role_assignments SET scope_unit_id = NULL, scope_path = NULL WHERE scope_unit_id = :cid",
         cid=company_id)
    assignments_below = _run(
        conn, "SELECT id, scope_path FROM role_assignments WHERE scope_path LIKE :p", p=company_path + '%',
    ).all()
    for assignment_id, scope_path in assignments_below:
        _run(conn, "UPDATE role_assignments SET scope_path = :sp WHERE id = :id",
             sp=_rebase(scope_path, company_path), id=assignment_id)


def _widen_user_permissions(conn: Connection, company_id: str) -> None:
    """
    Permissions granted at the company become organization-wide. An existing org-wide grant
    of the same permission absorbs them (the unique key can't catch that duplicate because
    NULL scopes never compare equal).
    """
    company_grants = _run(
        conn, "SELECT id, user_id, permission_code, self_only FROM user_permissions WHERE scope_unit_id = :cid",
        cid=company_id,
    ).all()
    for grant_id, user_id, permission_code, self_only in company_grants:
        org_wide_grant = _run(
            conn,
            "SELECT id, self_only FROM user_permissions"
            " WHERE user_id = :u AND permission_code = :c AND scope_unit_id IS NULL",
            u=user_id, c=permission_code,
        ).first()
        if org_wide_grant is None:
            _run(conn, "UPDATE user_permissions SET scope_unit_id = NULL WHERE id = :id", id=grant_id)
            continue
        if org_wide_grant.self_only and not self_only:
            _run(conn, "UPDATE user_permissions SET self_only = :f WHERE id = :id", f=False, id=org_wide_grant.id)
        _run(conn, "DELETE FROM user_permissions WHERE id = :id", id=grant_id)


def _delete_company_unit(conn: Connection, company_id: str) -> None:
    _run(conn, "UPDATE users SET home_unit_id = NULL WHERE home_unit_id = :cid", cid=company_id)
    _run(conn, "UPDATE legal_entities SET mg_unit_id = NULL WHERE mg_unit_id = :cid", cid=company_id)
    _run(conn, "UPDATE tax_registrations SET branch_unit_id = NULL WHERE branch_unit_id = :cid", cid=company_id)
    _run(conn, "DELETE FROM unit_memberships WHERE unit_id = :cid", cid=company_id)
    _run(conn, "DELETE FROM org_unit_verticals WHERE org_unit_id = :cid", cid=company_id)
    _run(conn, "DELETE FROM org_units WHERE id = :cid", cid=company_id)


def upgrade() -> None:
    conn = op.get_bind()
    companies = _run(
        conn, "SELECT id, organization_id, calendar_id, path FROM org_units WHERE unit_type = 'company'"
    ).mappings().all()

    # Check every company before changing any of them.
    for company in companies:
        _refuse_non_branch_children(conn, company['id'])

    for company in companies:
        company_id, company_path = company['id'], company['path']
        if company['calendar_id'] is not None:
            _run(conn, "UPDATE organizations SET calendar_id = :cal WHERE id = :org AND calendar_id IS NULL",
                 cal=company['calendar_id'], org=company['organization_id'])
        _move_branches_to_top(conn, company_id, company_path)
        _widen_role_assignments(conn, company_id, company_path)
        _widen_user_permissions(conn, company_id)
        _delete_company_unit(conn, company_id)


def downgrade() -> None:
    # One-way: the removed company units are not recreated.
    pass
