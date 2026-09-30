"""upload_session_object_key

Revision ID: a3c5e7f91b24
Revises: 8d41f07a2c96
Create Date: 2026-09-29 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c5e7f91b24'
down_revision: Union[str, None] = '8d41f07a2c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('upload_sessions', sa.Column('object_key', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('upload_sessions', 'object_key')
