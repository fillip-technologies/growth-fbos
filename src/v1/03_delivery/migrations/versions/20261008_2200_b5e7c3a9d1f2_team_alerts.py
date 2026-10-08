"""team alerts: the setting, and the time-limit alerts already told

Revision ID: b5e7c3a9d1f2
Revises: 8d3f1a6c2e94
Create Date: 2026-10-08 22:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'b5e7c3a9d1f2'
down_revision: Union[str, None] = '8d3f1a6c2e94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _settings_columns() -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('delivery_settings')}


def upgrade() -> None:
    # A database a development build ran create_all on already has these, made from the same models.
    if 'team_alerts' not in _settings_columns():
        # Existing rows keep today's behaviour: off.
        op.add_column(
            'delivery_settings',
            sa.Column('team_alerts', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not sa.inspect(op.get_bind()).has_table('sla_alerts'):
        op.create_table(
            'sla_alerts',
            sa.Column('task_id', database.types.UUIDType(length=36), nullable=False),
            sa.Column('kind', sa.String(length=20), nullable=False),
            sa.Column('level', sa.String(length=20), nullable=False),
            sa.Column('notified', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('task_id', 'kind', 'level'),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table('sla_alerts'):
        op.drop_table('sla_alerts')
    if 'team_alerts' in _settings_columns():
        with op.batch_alter_table('delivery_settings') as batch:
            batch.drop_column('team_alerts')
