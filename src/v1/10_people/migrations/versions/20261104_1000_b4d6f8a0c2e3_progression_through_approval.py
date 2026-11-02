"""progression through approval

Salary revisions and promotions are now role changes, approved before they apply: a role change records the
revision's kind and the promotion's job profile and level. A bonus records who awarded it, so someone else
approves it.

Revision ID: b4d6f8a0c2e3
Revises: a3c5e7f9b1d2
Create Date: 2026-11-04 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'b4d6f8a0c2e3'
down_revision: Union[str, None] = 'a3c5e7f9b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = (
    ('role_changes', sa.Column('revision_type', sa.String(length=32), nullable=True)),
    ('role_changes', sa.Column('new_job_profile_id', database.types.UUIDType(length=36), nullable=True)),
    ('role_changes', sa.Column('new_level', sa.String(length=32), nullable=True)),
    ('bonus_disbursements', sa.Column('requested_by', database.types.UUIDType(length=36), nullable=True)),
)


def upgrade() -> None:
    # Startup's create_all may already have added them.
    inspector = sa.inspect(op.get_bind())
    for table, column in NEW_COLUMNS:
        if column.name not in {c['name'] for c in inspector.get_columns(table)}:
            op.add_column(table, column)


def downgrade() -> None:
    for table, column in reversed(NEW_COLUMNS):
        op.drop_column(table, column.name)
