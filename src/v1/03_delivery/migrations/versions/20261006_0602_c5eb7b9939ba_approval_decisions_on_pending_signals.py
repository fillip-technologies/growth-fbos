"""approval decisions on pending signals

Revision ID: c5eb7b9939ba
Revises: b829e820f6e8
Create Date: 2026-10-06 06:02:35.070661+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'c5eb7b9939ba'
down_revision: Union[str, None] = 'b829e820f6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pending_signals', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column('pending_signals', sa.Column('resolved_by', database.types.UUIDType(length=36), nullable=True))
    op.add_column('pending_signals', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('pending_signals', sa.Column('resolution_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('pending_signals', 'resolution_note')
    op.drop_column('pending_signals', 'resolved_at')
    op.drop_column('pending_signals', 'resolved_by')
    op.drop_column('pending_signals', 'created_at')
