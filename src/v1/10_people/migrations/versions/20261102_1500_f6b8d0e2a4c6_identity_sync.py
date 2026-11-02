"""identity sync

Revision ID: f6b8d0e2a4c6
Revises: e5a7c9d1f3b5
Create Date: 2026-11-02 15:00:00.000000+00:00

Retry columns on the outbox, the per-employee sync state and the job -> access role mappings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'f6b8d0e2a4c6'
down_revision: Union[str, None] = 'e5a7c9d1f3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _exists(table: str, column: str = None) -> bool:
    """
    Whether the table (or the column) is already there. People creates missing tables when it starts
    (`create_all`), so a table this migration would create may exist already; a column cannot be.
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column is None or column in {c['name'] for c in inspector.get_columns(table)}



def upgrade() -> None:
    outbox = {
        'attempts': sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        'last_error': sa.Column('last_error', sa.Text(), nullable=True),
        'next_attempt_at': sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in outbox.items():
        if not _exists('outbox', name):
            op.add_column('outbox', column)

    if not _exists('worker_identity_sync'):
        op.create_table('worker_identity_sync',
        sa.Column('worker_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('drift', sa.JSON(), nullable=True),
        sa.Column('drift_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('worker_id')
        )
        op.create_index(op.f('ix_worker_identity_sync_organization_id'), 'worker_identity_sync', ['organization_id'], unique=False)
        op.create_index(op.f('ix_worker_identity_sync_drift_checked_at'), 'worker_identity_sync', ['drift_checked_at'], unique=False)

    if not _exists('access_role_mappings'):
        op.create_table('access_role_mappings',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('match_type', sa.String(length=20), nullable=False),
        sa.Column('match_value', sa.String(length=255), nullable=False),
        sa.Column('role_code', sa.String(length=100), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('created_by', database.types.UUIDType(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'match_type', 'match_value', 'role_code', name='uq_access_role_mappings')
        )
        op.create_index(op.f('ix_access_role_mappings_organization_id'), 'access_role_mappings', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_table('access_role_mappings')
    op.drop_table('worker_identity_sync')
    op.drop_column('outbox', 'next_attempt_at')
    op.drop_column('outbox', 'last_error')
    op.drop_column('outbox', 'attempts')
