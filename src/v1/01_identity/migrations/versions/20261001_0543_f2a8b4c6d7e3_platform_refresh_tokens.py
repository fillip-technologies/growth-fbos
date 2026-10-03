"""platform_refresh_tokens

Rotating refresh tokens for the platform super-admin, so its console stays signed in
past the 15-minute access token (same rotation / reuse-detection rules as users).

Revision ID: f2a8b4c6d7e3
Revises: e1f0a7c3d5b2
Create Date: 2026-10-01 05:43:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'f2a8b4c6d7e3'
down_revision: Union[str, None] = 'e1f0a7c3d5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'platform_refresh_tokens' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('platform_refresh_tokens',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('admin_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('family_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['platform_admins.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_platform_refresh_tokens_admin_id'), 'platform_refresh_tokens', ['admin_id'], unique=False)
    op.create_index(op.f('ix_platform_refresh_tokens_family_id'), 'platform_refresh_tokens', ['family_id'], unique=False)


def downgrade() -> None:
    op.drop_table('platform_refresh_tokens')
