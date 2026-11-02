"""role assignment source

Marks a role assignment as managed by another service (People grants access from a person's job),
so that service can add and remove its own assignments and never touch the ones granted by hand.

Revision ID: f2c8d4e6a7b9
Revises: e1b7c3d5f6a8
Create Date: 2026-11-02 05:49:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2c8d4e6a7b9'
down_revision: Union[str, None] = 'e1b7c3d5f6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('role_assignments')}
    if 'source' not in columns:
        op.add_column('role_assignments', sa.Column('source', sa.String(length=50), nullable=True))
        op.create_index(op.f('ix_role_assignments_source'), 'role_assignments', ['source'], unique=False)
    if 'source_ref' not in columns:
        op.add_column('role_assignments', sa.Column('source_ref', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('role_assignments', 'source_ref')
    op.drop_index(op.f('ix_role_assignments_source'), table_name='role_assignments')
    op.drop_column('role_assignments', 'source')
