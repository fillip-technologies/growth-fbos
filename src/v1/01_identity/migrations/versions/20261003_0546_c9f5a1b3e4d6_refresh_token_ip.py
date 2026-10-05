"""refresh_token_ip

Remember the IP address a session token was issued to, so a user's session list can
show where each sign-in is used from.

Revision ID: c9f5a1b3e4d6
Revises: b8e4f0a2d3c5
Create Date: 2026-10-03 05:46:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9f5a1b3e4d6'
down_revision: Union[str, None] = 'b8e4f0a2d3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('refresh_tokens')}
    if 'ip_address' in columns:
        return
    op.add_column('refresh_tokens', sa.Column('ip_address', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('refresh_tokens', 'ip_address')
