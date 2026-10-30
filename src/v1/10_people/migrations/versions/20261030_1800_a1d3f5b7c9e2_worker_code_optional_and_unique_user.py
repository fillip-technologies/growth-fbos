"""worker_code_optional_and_unique_user

Revision ID: a1d3f5b7c9e2
Revises: c76e9bff058f
Create Date: 2026-10-30 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1d3f5b7c9e2'
down_revision: Union[str, None] = 'c76e9bff058f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The employee code can be filled in after a worker is created.
    with op.batch_alter_table('workers') as batch:
        batch.alter_column('worker_code', existing_type=sa.String(length=50), nullable=True)
    # One worker per identity user (workers without a login have user_id NULL and are not constrained).
    op.create_index('uq_workers_org_user', 'workers', ['organization_id', 'user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_workers_org_user', table_name='workers')
    with op.batch_alter_table('workers') as batch:
        batch.alter_column('worker_code', existing_type=sa.String(length=50), nullable=False)
