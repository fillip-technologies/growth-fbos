"""workflows task types follow: stage status categories, governing instances, the type links

Revision ID: e7c2a5d8f3b1
Revises: d4b9f2a7c6e1
Create Date: 2026-10-09 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'e7c2a5d8f3b1'
down_revision: Union[str, None] = 'd4b9f2a7c6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # A database a development build ran create_all on already has these, made from the same models.
    if 'status_category' not in _columns('stages'):
        op.add_column('stages', sa.Column('status_category', sa.String(length=20), nullable=True))
    if 'governs_status' not in _columns('workflow_instances'):
        # Existing instances were started by hand: they leave their task's status alone.
        op.add_column(
            'workflow_instances',
            sa.Column('governs_status', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not sa.inspect(op.get_bind()).has_table('task_type_workflows'):
        op.create_table(
            'task_type_workflows',
            sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
            sa.Column('task_type_id', database.types.UUIDType(length=36), nullable=False),
            sa.Column('definition_id', database.types.UUIDType(length=36), nullable=False),
            sa.Column('updated_by', database.types.UUIDType(length=36), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['task_type_id'], ['task_types.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['definition_id'], ['workflow_definitions.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('organization_id', 'task_type_id'),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table('task_type_workflows'):
        op.drop_table('task_type_workflows')
    if 'governs_status' in _columns('workflow_instances'):
        with op.batch_alter_table('workflow_instances') as batch:
            batch.drop_column('governs_status')
    if 'status_category' in _columns('stages'):
        with op.batch_alter_table('stages') as batch:
            batch.drop_column('status_category')
