"""task type profiles

Revision ID: fb22b8e536ff
Revises: 5bd0d56d0500
Create Date: 2026-10-07 12:07:41.238042+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'fb22b8e536ff'
down_revision: Union[str, None] = '5bd0d56d0500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database a development build ran create_all on already has the table, made from the same model.
    if sa.inspect(op.get_bind()).has_table('task_type_profiles'):
        return
    op.create_table(
        'task_type_profiles',
        sa.Column('task_type_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('discipline', sa.String(length=50), nullable=False),
        sa.Column('estimation_unit', sa.String(length=20), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=True),
        sa.Column('outcomes', sa.JSON(), nullable=True),
        sa.Column('response_sla_minutes', sa.JSON(), nullable=True),
        sa.Column('resolution_sla_minutes', sa.JSON(), nullable=True),
        sa.Column('review_rounds_included', sa.Integer(), nullable=True),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['task_type_id'], ['task_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('task_type_id'),
    )
    op.create_index(op.f('ix_task_type_profiles_discipline'), 'task_type_profiles', ['discipline'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_type_profiles_discipline'), table_name='task_type_profiles')
    op.drop_table('task_type_profiles')
