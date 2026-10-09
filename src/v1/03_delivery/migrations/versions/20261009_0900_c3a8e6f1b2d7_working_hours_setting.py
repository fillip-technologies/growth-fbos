"""working hours setting

Revision ID: c3a8e6f1b2d7
Revises: b5e7c3a9d1f2
Create Date: 2026-10-09 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3a8e6f1b2d7'
down_revision: Union[str, None] = 'b5e7c3a9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('delivery_settings')}


def upgrade() -> None:
    # A database a development build ran create_all on already has it, made from the same model.
    if 'working_hours' in _columns():
        return
    # Existing rows keep today's behaviour: time limits run around the clock.
    op.add_column(
        'delivery_settings',
        sa.Column('working_hours', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if 'working_hours' in _columns():
        with op.batch_alter_table('delivery_settings') as batch:
            batch.drop_column('working_hours')
