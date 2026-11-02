"""credential lockout columns

When the latest failed sign-in came (so failures within the window lock the account) and the last MFA code
accepted (so it cannot be replayed). Both were read by the sign-in code but never stored, which left the
lockout and the replay check without effect.

Revision ID: e3a5c7d9f1b2
Revises: d0f2b4c6e8a1
Create Date: 2026-11-04 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3a5c7d9f1b2'
down_revision: Union[str, None] = 'd0f2b4c6e8a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('user_credentials')}
    if 'last_failed_at' not in columns:
        op.add_column('user_credentials', sa.Column('last_failed_at', sa.DateTime(), nullable=True))
    if 'last_totp_code' not in columns:
        op.add_column('user_credentials', sa.Column('last_totp_code', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('user_credentials', 'last_totp_code')
    op.drop_column('user_credentials', 'last_failed_at')
