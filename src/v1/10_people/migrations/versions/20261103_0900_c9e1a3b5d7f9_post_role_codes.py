"""post role codes

The Identity role(s) a post gives, and the role(s) a role change moves a post to. Access follows the
post, so an approved promotion changes what the person can do.

Revision ID: c9e1a3b5d7f9
Revises: b8d0f2a4c6e8
Create Date: 2026-11-03 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e1a3b5d7f9'
down_revision: Union[str, None] = 'b8d0f2a4c6e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if 'role_codes' not in _columns('worker_posts'):
        op.add_column('worker_posts', sa.Column('role_codes', sa.JSON(), nullable=False, server_default='[]'))
    changes = _columns('role_changes')
    if 'new_role_codes' not in changes:
        op.add_column('role_changes', sa.Column('new_role_codes', sa.JSON(), nullable=True))
    if 'previous_role_codes' not in changes:
        op.add_column('role_changes', sa.Column('previous_role_codes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('role_changes', 'previous_role_codes')
    op.drop_column('role_changes', 'new_role_codes')
    op.drop_column('worker_posts', 'role_codes')
