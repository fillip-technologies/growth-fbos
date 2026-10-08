"""outbox

Revision ID: 8d3f1a6c2e94
Revises: 6a2d8f4b9c15
Create Date: 2026-10-08 20:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '8d3f1a6c2e94'
down_revision: Union[str, None] = '6a2d8f4b9c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database a development build ran create_all on already has the table, made from the same model.
    if sa.inspect(op.get_bind()).has_table('outbox_events'):
        return
    op.create_table(
        'outbox_events',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_outbox_events_status_next', 'outbox_events', ['status', 'next_attempt_at'])


def downgrade() -> None:
    op.drop_index('ix_outbox_events_status_next', table_name='outbox_events')
    op.drop_table('outbox_events')
