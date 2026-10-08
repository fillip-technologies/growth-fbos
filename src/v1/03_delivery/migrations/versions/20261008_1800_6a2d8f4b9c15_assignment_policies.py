"""assignment policies

Revision ID: 6a2d8f4b9c15
Revises: 4e8b1d6f3c27
Create Date: 2026-10-08 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '6a2d8f4b9c15'
down_revision: Union[str, None] = '4e8b1d6f3c27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database a development build ran create_all on already has the table, made from the same model.
    if sa.inspect(op.get_bind()).has_table('assignment_policies'):
        return
    # No rows: every team leaves new work in its queue, as before.
    op.create_table(
        'assignment_policies',
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('policy', sa.String(length=20), nullable=False),
        sa.Column('last_assigned_user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('organization_id', 'unit_id'),
    )


def downgrade() -> None:
    op.drop_table('assignment_policies')
