"""calendar_working_days

Extra working days on a working calendar: a date worked on with its own hours, usually one the
week leaves off (a working Saturday, a Sunday before a release). One row per date per calendar.

Revision ID: e1b7c3d5f6a8
Revises: d0a6b2c4e5f7
Create Date: 2026-10-12 05:48:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'e1b7c3d5f6a8'
down_revision: Union[str, None] = 'd0a6b2c4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'calendar_working_days' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('calendar_working_days',
    sa.Column('id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('calendar_id', database.types.UUIDType(length=36), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('hours', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['calendar_id'], ['calendars.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('calendar_id', 'work_date', name='uq_calendar_working_days_date')
    )
    op.create_index(op.f('ix_calendar_working_days_calendar_id'), 'calendar_working_days', ['calendar_id'], unique=False)


def downgrade() -> None:
    op.drop_table('calendar_working_days')
