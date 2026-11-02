"""users people managed at

Since when People keeps a user's job. Their roles then come from their posts, and access given by hand in
Users is extra access with an end date. Users who already hold a role People granted are marked now; the
others are marked the next time People declares their employment.

Revision ID: a5c7e9f1b3d4
Revises: f4b6d8e0a2c3
Create Date: 2026-11-05 09:00:00.000000+00:00

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c7e9f1b3d4'
down_revision: Union[str, None] = 'f4b6d8e0a2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}
    if 'people_managed_at' not in columns:
        op.add_column('users', sa.Column('people_managed_at', sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET people_managed_at = :now WHERE people_managed_at IS NULL AND id IN "
            "(SELECT user_id FROM role_assignments WHERE source = 'people')"
        ).bindparams(now=datetime.now(timezone.utc).replace(tzinfo=None))
    )


def downgrade() -> None:
    op.drop_column('users', 'people_managed_at')
