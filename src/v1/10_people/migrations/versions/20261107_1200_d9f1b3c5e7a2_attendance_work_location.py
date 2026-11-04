"""attendance work location

Where a day was worked: office, field (a customer's site) or remote. Existing days are left empty.

Revision ID: d9f1b3c5e7a2
Revises: b4d6f8a0c2e3
Create Date: 2026-11-07 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f1b3c5e7a2'
down_revision: Union[str, None] = 'b4d6f8a0c2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('daily_attendance')}
    if 'work_location' not in columns:
        op.add_column('daily_attendance', sa.Column('work_location', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('daily_attendance', 'work_location')
