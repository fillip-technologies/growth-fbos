"""designation checked at

For an employee with a login the designation is their role in Identity; this records when People last compared it.

Revision ID: b8d0f2a4c6e8
Revises: a7c9e1f3b5d7
Create Date: 2026-11-02 17:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d0f2a4c6e8'
down_revision: Union[str, None] = 'a7c9e1f3b5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'designation_checked_at' not in {c['name'] for c in inspector.get_columns('workers')}:
        op.add_column('workers', sa.Column('designation_checked_at', sa.DateTime(timezone=True), nullable=True))
    if 'ix_workers_designation_checked_at' not in {i['name'] for i in inspector.get_indexes('workers')}:
        op.create_index(op.f('ix_workers_designation_checked_at'), 'workers', ['designation_checked_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workers_designation_checked_at'), table_name='workers')
    op.drop_column('workers', 'designation_checked_at')
