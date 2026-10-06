"""approved impact on change requests

Revision ID: 5bd0d56d0500
Revises: c5eb7b9939ba
Create Date: 2026-10-06 09:11:45.201993+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '5bd0d56d0500'
down_revision: Union[str, None] = 'c5eb7b9939ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('change_requests', sa.Column('approved_schedule_impact_days', sa.Integer(), nullable=True))
    op.add_column('change_requests', sa.Column('approved_cost_impact', sa.Numeric(precision=15, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('change_requests', 'approved_cost_impact')
    op.drop_column('change_requests', 'approved_schedule_impact_days')
