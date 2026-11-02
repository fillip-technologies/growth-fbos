"""role change approval steps, standing approvers and delegations

Revision ID: e5a7c9d1f3b5
Revises: d4f6b8c0e2a4
Create Date: 2026-11-02 14:00:00.000000+00:00

Role changes still waiting for approval are given one open "Approval" step, so they carry on as before.
"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'e5a7c9d1f3b5'
down_revision: Union[str, None] = 'd4f6b8c0e2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    steps = op.create_table('role_change_steps',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('role_change_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('unit_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('approver_user_ids', sa.JSON(), nullable=False),
    sa.Column('open_to_pool', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', database.types.UUIDType(length=36), nullable=True),
    sa.Column('acted_for', database.types.UUIDType(length=36), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['role_change_id'], ['role_changes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    for column in ('organization_id', 'role_change_id', 'status'):
        op.create_index(op.f(f'ix_role_change_steps_{column}'), 'role_change_steps', [column], unique=False)

    op.create_table('role_change_approvers',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('role_key', sa.String(length=20), nullable=False),
    sa.Column('user_id', database.types.UUIDType(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'role_key', 'user_id', name='uq_role_change_approvers')
    )
    op.create_index(op.f('ix_role_change_approvers_organization_id'), 'role_change_approvers', ['organization_id'], unique=False)

    op.create_table('role_change_delegations',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('from_user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('to_user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=False),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    for column in ('organization_id', 'from_user_id', 'to_user_id'):
        op.create_index(op.f(f'ix_role_change_delegations_{column}'), 'role_change_delegations', [column], unique=False)

    _give_pending_changes_an_open_step(steps)


def _give_pending_changes_an_open_step(steps: sa.Table) -> None:
    """A change waiting today keeps its single approval: one open step, active now."""
    bind = op.get_bind()
    changes = sa.table('role_changes', sa.column('id'), sa.column('organization_id'), sa.column('status'))
    rows = [
        {
            'id': str(uuid.uuid4()), 'organization_id': str(change.organization_id), 'role_change_id': str(change.id),
            'seq': 1, 'name': 'Approval', 'kind': 'approval', 'approver_user_ids': [], 'open_to_pool': True,
            'status': 'active', 'activated_at': datetime.now(timezone.utc),
        }
        for change in bind.execute(sa.select(changes).where(changes.c.status == 'pending'))
    ]
    if rows:
        op.bulk_insert(steps, rows)


def downgrade() -> None:
    op.drop_table('role_change_delegations')
    op.drop_table('role_change_approvers')
    op.drop_table('role_change_steps')
