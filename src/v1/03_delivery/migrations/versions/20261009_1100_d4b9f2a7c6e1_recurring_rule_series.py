"""recurring rules: where each series starts, and when it last ran

Revision ID: d4b9f2a7c6e1
Revises: c3a8e6f1b2d7
Create Date: 2026-10-09 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4b9f2a7c6e1'
down_revision: Union[str, None] = 'c3a8e6f1b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = ('series_start', 'last_run_at')


def _columns() -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('recurring_task_rules')}


def upgrade() -> None:
    # A database a development build ran create_all on already has them, made from the same model.
    present = _columns()
    # Existing rules have neither: their series starts from their next_run_at.
    for name in NEW_COLUMNS:
        if name not in present:
            op.add_column('recurring_task_rules', sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    present = _columns()
    with op.batch_alter_table('recurring_task_rules') as batch:
        for name in NEW_COLUMNS:
            if name in present:
                batch.drop_column(name)
