"""team visibility setting

Revision ID: 9c4f2e7a1b63
Revises: 7b1e5c9d2a40
Create Date: 2026-10-08 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9c4f2e7a1b63'
down_revision: Union[str, None] = '7b1e5c9d2a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('delivery_settings')}


def upgrade() -> None:
    # A database a development build ran create_all on already has it, made from the same model.
    if 'team_visibility' in _columns():
        return
    # Existing rows keep today's behaviour: off.
    op.add_column(
        'delivery_settings',
        sa.Column('team_visibility', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if 'team_visibility' in _columns():
        with op.batch_alter_table('delivery_settings') as batch:
            batch.drop_column('team_visibility')
