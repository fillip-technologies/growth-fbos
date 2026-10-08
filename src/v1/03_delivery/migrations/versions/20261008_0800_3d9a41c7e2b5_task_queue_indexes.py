"""task queue indexes

Revision ID: 3d9a41c7e2b5
Revises: fb22b8e536ff
Create Date: 2026-10-08 08:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3d9a41c7e2b5'
down_revision: Union[str, None] = 'fb22b8e536ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The list, board and queue: someone's own tasks, a team's queue, and work by due date.
INDEXES = {
    'ix_tasks_org_assignee_status': ['organization_id', 'assignee_user_id', 'status'],
    'ix_tasks_org_unit_status': ['organization_id', 'owning_unit_id', 'status'],
    'ix_tasks_org_status_due': ['organization_id', 'status', 'due_at'],
}


def _existing_indexes() -> set[str]:
    return {index['name'] for index in sa.inspect(op.get_bind()).get_indexes('tasks')}


def upgrade() -> None:
    # A database a development build ran create_all on already has them, made from the same model.
    existing = _existing_indexes()
    for name, columns in INDEXES.items():
        if name not in existing:
            op.create_index(name, 'tasks', columns, unique=False)


def downgrade() -> None:
    existing = _existing_indexes()
    for name in INDEXES:
        if name in existing:
            op.drop_index(name, table_name='tasks')
