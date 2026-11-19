"""board modules: a project's board holds its own cards (modules), not tasks

The first boards (`b3d7f1a9e5c2`) placed tasks in columns tied to task statuses. Boards now hold
modules in free columns, with tasks linked to them. Those first tables held nothing people made
by hand beyond default boards (made again the first time a board is opened), so they are
replaced rather than converted.

Revision ID: c5e9a2d4f7b1
Revises: b3d7f1a9e5c2
Create Date: 2026-11-19 15:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types  # the UUIDType columns


revision: str = 'c5e9a2d4f7b1'
down_revision: Union[str, None] = 'b3d7f1a9e5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = database.types.UUIDType(length=36)


def _create_new_tables() -> None:
    op.create_table(
        'boards',
        sa.Column('id', UUID, nullable=False),
        sa.Column('organization_id', UUID, nullable=False),
        sa.Column('work_unit_id', UUID, nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('created_by', UUID, nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['work_unit_id'], ['work_units.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_boards_organization_id', 'boards', ['organization_id'])
    op.create_index('ix_boards_org_work_unit', 'boards', ['organization_id', 'work_unit_id'])
    op.create_table(
        'board_columns',
        sa.Column('id', UUID, nullable=False),
        sa.Column('board_id', UUID, nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('wip_limit', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_board_columns_board_id', 'board_columns', ['board_id'])
    op.create_table(
        'board_modules',
        sa.Column('id', UUID, nullable=False),
        sa.Column('organization_id', UUID, nullable=False),
        sa.Column('board_id', UUID, nullable=False),
        sa.Column('column_id', UUID, nullable=False),
        sa.Column('rank', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_user_id', UUID, nullable=True),
        sa.Column('estimate_minutes', sa.Integer(), nullable=True),
        sa.Column('due_on', sa.Date(), nullable=True),
        sa.Column('priority', sa.String(length=10), nullable=False),
        sa.Column('labels', sa.JSON(), nullable=False),
        sa.Column('created_by', UUID, nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['column_id'], ['board_columns.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_board_modules_organization_id', 'board_modules', ['organization_id'])
    op.create_index('ix_board_modules_board_id', 'board_modules', ['board_id'])
    op.create_index('ix_board_modules_owner_user_id', 'board_modules', ['owner_user_id'])
    op.create_index('ix_board_modules_column_rank', 'board_modules', ['column_id', 'rank'])
    op.create_table(
        'board_module_tasks',
        sa.Column('task_id', UUID, nullable=False),
        sa.Column('module_id', UUID, nullable=False),
        sa.Column('linked_by', UUID, nullable=True),
        sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['module_id'], ['board_modules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('task_id'),
    )
    op.create_index('ix_board_module_tasks_module_id', 'board_module_tasks', ['module_id'])


def _create_first_tables() -> None:
    """The tables as `b3d7f1a9e5c2` made them, for downgrading."""
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


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # A database a development build ran create_all on already has the new tables.
    if inspector.has_table('board_modules'):
        return
    for table in ('board_items', 'board_columns', 'boards'):
        if inspector.has_table(table):
            op.drop_table(table)
    _create_new_tables()


def downgrade() -> None:
    for table in ('board_module_tasks', 'board_modules', 'board_columns', 'boards'):
        op.drop_table(table)
    _create_first_tables()
