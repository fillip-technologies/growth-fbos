"""delivery settings

Revision ID: 7b1e5c9d2a40
Revises: 3d9a41c7e2b5
Create Date: 2026-10-08 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '7b1e5c9d2a40'
down_revision: Union[str, None] = '3d9a41c7e2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database a development build ran create_all on already has the table, made from the same model.
    if sa.inspect(op.get_bind()).has_table('delivery_settings'):
        return
    op.create_table(
        'delivery_settings',
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('team_assignment_only', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('organization_id'),
    )


def downgrade() -> None:
    op.drop_table('delivery_settings')
