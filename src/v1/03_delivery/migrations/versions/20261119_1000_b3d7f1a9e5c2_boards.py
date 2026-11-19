"""boards: kanban boards for a project or a customer, their columns and where cards sit

Revision ID: b3d7f1a9e5c2
Revises: a8c4e2d6f0b3
Create Date: 2026-11-19 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'b3d7f1a9e5c2'
down_revision: Union[str, None] = 'a8c4e2d6f0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = database.types.UUIDType(length=36)


def upgrade() -> None:
    # A database a development build ran create_all on already has the tables, made from the same models.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('boards'):
        # No rows: a project's or customer's board is made from the template the first time it's opened.
        op.create_table(
            'boards',
            sa.Column('id', UUID, nullable=False),
            sa.Column('organization_id', UUID, nullable=False),
            sa.Column('work_unit_id', UUID, nullable=True),
            sa.Column('client_id', UUID, nullable=True),
            sa.Column('owning_unit_id', UUID, nullable=True),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('is_default', sa.Boolean(), nullable=False),
            sa.Column('created_by', UUID, nullable=True),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_boards_organization_id', 'boards', ['organization_id'])
        op.create_index('ix_boards_org_work_unit', 'boards', ['organization_id', 'work_unit_id'])
        op.create_index('ix_boards_org_client', 'boards', ['organization_id', 'client_id'])
    if not inspector.has_table('board_columns'):
        op.create_table(
            'board_columns',
            sa.Column('id', UUID, nullable=False),
            sa.Column('board_id', UUID, nullable=False),
            sa.Column('seq', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('color', sa.String(length=20), nullable=True),
            sa.Column('statuses', sa.JSON(), nullable=False),
            sa.Column('wip_limit', sa.Integer(), nullable=True),
            sa.Column('is_default_for_status', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_board_columns_board_id', 'board_columns', ['board_id'])
    if not inspector.has_table('board_items'):
        op.create_table(
            'board_items',
            sa.Column('board_id', UUID, nullable=False),
            sa.Column('task_id', UUID, nullable=False),
            sa.Column('column_id', UUID, nullable=False),
            sa.Column('rank', sa.String(length=255), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['column_id'], ['board_columns.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('board_id', 'task_id'),
        )
        op.create_index('ix_board_items_task_id', 'board_items', ['task_id'])
        op.create_index('ix_board_items_column_id', 'board_items', ['column_id'])


def downgrade() -> None:
    op.drop_table('board_items')
    op.drop_table('board_columns')
    op.drop_table('boards')
