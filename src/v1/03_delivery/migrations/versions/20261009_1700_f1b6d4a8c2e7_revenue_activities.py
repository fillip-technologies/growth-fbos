"""finished sales tasks on revenue's timelines: the setting, and where outbox rows go

Revision ID: f1b6d4a8c2e7
Revises: e7c2a5d8f3b1
Create Date: 2026-10-09 17:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1b6d4a8c2e7'
down_revision: Union[str, None] = 'e7c2a5d8f3b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # A database a development build ran create_all on already has these, made from the same models.
    if 'revenue_activities' not in _columns('delivery_settings'):
        # Existing rows keep today's behaviour: off.
        op.add_column(
            'delivery_settings',
            sa.Column('revenue_activities', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if 'destination' not in _columns('outbox_events'):
        # Every row so far is a notification.
        op.add_column(
            'outbox_events',
            sa.Column('destination', sa.String(length=20), nullable=False, server_default='communication'),
        )


def downgrade() -> None:
    if 'destination' in _columns('outbox_events'):
        with op.batch_alter_table('outbox_events') as batch:
            batch.drop_column('destination')
    if 'revenue_activities' in _columns('delivery_settings'):
        with op.batch_alter_table('delivery_settings') as batch:
            batch.drop_column('revenue_activities')
