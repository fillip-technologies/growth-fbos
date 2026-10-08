"""routing rules

Revision ID: 4e8b1d6f3c27
Revises: 9c4f2e7a1b63
Create Date: 2026-10-08 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '4e8b1d6f3c27'
down_revision: Union[str, None] = '9c4f2e7a1b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database a development build ran create_all on already has the table, made from the same model.
    if sa.inspect(op.get_bind()).has_table('routing_rules'):
        return
    # No rows: nothing is routed until an organization adds a rule.
    op.create_table(
        'routing_rules',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('task_type_code', sa.String(length=100), nullable=True),
        sa.Column('discipline', sa.String(length=50), nullable=True),
        sa.Column('vertical_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('unit_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('accepts_requests', sa.Boolean(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_routing_rules_org_active', 'routing_rules', ['organization_id', 'active'])


def downgrade() -> None:
    op.drop_index('ix_routing_rules_org_active', table_name='routing_rules')
    op.drop_table('routing_rules')
