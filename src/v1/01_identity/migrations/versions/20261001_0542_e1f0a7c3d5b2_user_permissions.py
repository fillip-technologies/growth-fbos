"""user_permissions

Switches access control from role-based to user-based: permissions are granted to
each user directly (roles become presets). Existing role assignments are copied into
per-user permissions so nobody loses access.

Revision ID: e1f0a7c3d5b2
Revises: c7a41e9d2b10
Create Date: 2026-10-01 05:42:00.000000+00:00

"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'e1f0a7c3d5b2'
down_revision: Union[str, None] = 'c7a41e9d2b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_from_role_assignments() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT ra.organization_id, ra.user_id, ra.role_id, ra.scope_unit_id, ra.self_only, "
        "ra.valid_to, ra.granted_by_id, rp.permission_code "
        "FROM role_assignments ra JOIN role_permissions rp ON rp.role_id = ra.role_id"
    )).fetchall()

    seen: set[tuple] = set()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        key = (row.user_id, row.permission_code, row.scope_unit_id)
        if key in seen:
            continue
        seen.add(key)
        bind.execute(
            sa.text(
                "INSERT INTO user_permissions (id, organization_id, user_id, permission_code, scope_unit_id, "
                "self_only, source_role_id, granted_by_id, granted_at, valid_to) VALUES "
                "(:id, :org, :user, :perm, :unit, :self_only, :role, :by, :at, :valid_to)"
            ),
            {
                "id": str(uuid.uuid4()), "org": row.organization_id, "user": row.user_id,
                "perm": row.permission_code, "unit": row.scope_unit_id, "self_only": row.self_only,
                "role": row.role_id, "by": row.granted_by_id, "at": now, "valid_to": row.valid_to,
            },
        )


def upgrade() -> None:
    if 'user_permissions' in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table('user_permissions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('permission_code', sa.String(length=200), nullable=False),
        sa.Column('scope_unit_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('self_only', sa.Boolean(), nullable=False),
        sa.Column('source_role_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('granted_by_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('valid_to', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_code'], ['permissions.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scope_unit_id'], ['org_units.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_role_id'], ['roles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'permission_code', 'scope_unit_id', name='uq_user_permission_scope'),
    )
    op.create_index(op.f('ix_user_permissions_organization_id'), 'user_permissions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_user_permissions_user_id'), 'user_permissions', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_permissions_permission_code'), 'user_permissions', ['permission_code'], unique=False)
    op.create_index(op.f('ix_user_permissions_scope_unit_id'), 'user_permissions', ['scope_unit_id'], unique=False)

    _backfill_from_role_assignments()


def downgrade() -> None:
    op.drop_table('user_permissions')
