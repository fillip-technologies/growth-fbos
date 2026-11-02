"""role changes per post

Revision ID: d4f6b8c0e2a4
Revises: c3e5a7b9d1f3
Create Date: 2026-11-02 13:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'd4f6b8c0e2a4'
down_revision: Union[str, None] = 'c3e5a7b9d1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('role_changes', sa.Column('post_ref', database.types.UUIDType(length=36), nullable=True))
    op.add_column('role_changes', sa.Column('post_type', sa.String(length=20), nullable=True))
    op.add_column('role_changes', sa.Column('new_time_share', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('role_changes', sa.Column('new_monthly_allowance', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('role_changes', sa.Column('end_date', sa.Date(), nullable=True))
    op.create_index(op.f('ix_role_changes_post_ref'), 'role_changes', ['post_ref'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_role_changes_post_ref'), table_name='role_changes')
    for column in ('end_date', 'new_monthly_allowance', 'new_time_share', 'post_type', 'post_ref'):
        op.drop_column('role_changes', column)
