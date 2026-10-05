"""organization_calendar

The organization is the company, and it has its own working calendar: one of the
organization's calendars. New top-level units (branches) start on it, and units that
follow it switch when it changes.

Revision ID: a7d3e9f1c2b4
Revises: f2a8b4c6d7e3
Create Date: 2026-10-03 05:44:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'a7d3e9f1c2b4'
down_revision: Union[str, None] = 'f2a8b4c6d7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('organizations')}
    if 'calendar_id' in columns:
        return
    op.add_column('organizations', sa.Column('calendar_id', database.types.UUIDType(length=36), nullable=True))
    op.create_foreign_key(
        'fk_organizations_calendar_id', 'organizations', 'calendars',
        ['calendar_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_organizations_calendar_id', 'organizations', type_='foreignkey')
    op.drop_column('organizations', 'calendar_id')
