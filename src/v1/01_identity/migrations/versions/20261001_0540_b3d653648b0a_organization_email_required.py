"""organization_email_required

Revision ID: b3d653648b0a
Revises: 548f2fb670fc
Create Date: 2026-10-01 05:40:18.148661+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d653648b0a'
down_revision: Union[str, None] = '548f2fb670fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first, backfill existing orgs from their client's contact email
    # (NOT NULL since the previous migration), then enforce NOT NULL.
    op.add_column('organizations', sa.Column('email', sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE organizations o JOIN clients c ON c.id = o.client_id "
        "SET o.email = c.contact_email WHERE o.email IS NULL"
    )
    op.alter_column('organizations', 'email', existing_type=sa.String(length=255), nullable=False)


def downgrade() -> None:
    op.drop_column('organizations', 'email')
