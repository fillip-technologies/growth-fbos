"""client_org_user_limits

Revision ID: adc8f3f20b07
Revises: 6d8a0623fa9e
Create Date: 2026-10-01 05:38:58.630366+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'adc8f3f20b07'
down_revision: Union[str, None] = '6d8a0623fa9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Some dev databases were patched by hand before this migration existed.
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('clients')}
    if 'max_organizations' not in columns:
        op.add_column('clients', sa.Column('max_organizations', sa.Integer(), server_default='2', nullable=False))
    if 'max_users_per_org' not in columns:
        op.add_column('clients', sa.Column('max_users_per_org', sa.Integer(), server_default='50', nullable=False))


def downgrade() -> None:
    op.drop_column('clients', 'max_users_per_org')
    op.drop_column('clients', 'max_organizations')
