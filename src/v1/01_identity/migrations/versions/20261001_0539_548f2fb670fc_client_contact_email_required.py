"""client_contact_email_required

Revision ID: 548f2fb670fc
Revises: adc8f3f20b07
Create Date: 2026-10-01 05:39:00.487900+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '548f2fb670fc'
down_revision: Union[str, None] = 'adc8f3f20b07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing clients without a contact email get a non-deliverable placeholder
    # (.invalid is a reserved TLD); a super-admin must replace it with the real one.
    op.execute(
        "UPDATE clients SET contact_email = CONCAT(LOWER(code), '@pending-contact.invalid') "
        "WHERE contact_email IS NULL OR contact_email = ''"
    )
    op.alter_column('clients', 'contact_email', existing_type=sa.String(length=255), nullable=False)


def downgrade() -> None:
    op.alter_column('clients', 'contact_email', existing_type=sa.String(length=255), nullable=True)
