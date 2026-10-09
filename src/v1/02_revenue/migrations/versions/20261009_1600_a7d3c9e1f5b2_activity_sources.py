"""activity sources: the record another service logged an activity from

Revision ID: a7d3c9e1f5b2
Revises: d965483ea424
Create Date: 2026-10-09 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'a7d3c9e1f5b2'
down_revision: Union[str, None] = 'd965483ea424'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns('activities')}


def upgrade() -> None:
    # A database a development build ran create_all on already has them, made from the same model.
    if 'source_type' in _columns():
        return
    # Activities typed in have no source; several may (NULLs never clash in the unique key).
    with op.batch_alter_table('activities') as batch:
        batch.add_column(sa.Column('source_type', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('source_id', database.types.UUIDType(length=36), nullable=True))
        batch.create_unique_constraint('uq_activities_source', ['organization_id', 'source_type', 'source_id'])


def downgrade() -> None:
    if 'source_type' not in _columns():
        return
    with op.batch_alter_table('activities') as batch:
        batch.drop_constraint('uq_activities_source', type_='unique')
        batch.drop_column('source_id')
        batch.drop_column('source_type')
