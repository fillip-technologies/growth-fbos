"""goal check-ins

Owners' forward-looking check-ins on a goal or an initiative: confidence 0.00-1.00, their own
colour and the narrative behind it. Append-only.

Revision ID: 7a3c5e9f1b42
Revises: 5d1e7a9c3b20
Create Date: 2026-11-02 12:30:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = '7a3c5e9f1b42'
down_revision: Union[str, None] = '5d1e7a9c3b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'goal_check_ins' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('goal_check_ins',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('goal_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('initiative_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('period_id', database.types.UUIDType(length=36), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=3, scale=2), nullable=False),
    sa.Column('rag', sa.String(length=10), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('author_user_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['strategic_goals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['initiative_id'], ['initiatives.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['period_id'], ['planning_periods.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_goal_check_ins_author_user_id'), 'goal_check_ins', ['author_user_id'], unique=False)
    op.create_index(op.f('ix_goal_check_ins_goal_id'), 'goal_check_ins', ['goal_id'], unique=False)
    op.create_index(op.f('ix_goal_check_ins_initiative_id'), 'goal_check_ins', ['initiative_id'], unique=False)
    op.create_index(op.f('ix_goal_check_ins_organization_id'), 'goal_check_ins', ['organization_id'], unique=False)
    op.create_index(op.f('ix_goal_check_ins_period_id'), 'goal_check_ins', ['period_id'], unique=False)


def downgrade() -> None:
    op.drop_table('goal_check_ins')
