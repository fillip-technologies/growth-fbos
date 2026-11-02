"""hash recovery codes

MFA recovery codes were stored as written ("ABCD-EF12,..."). They now sign a user in, so they are kept only as
argon2 hashes, one a line. Codes users already printed keep working.

Revision ID: f4b6d8e0a2c3
Revises: e3a5c7d9f1b2
Create Date: 2026-11-04 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from utils.security import hash_recovery_codes


revision: str = 'f4b6d8e0a2c3'
down_revision: Union[str, None] = 'e3a5c7d9f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT user_id, recovery_codes FROM user_credentials WHERE recovery_codes IS NOT NULL")
    ).all()
    for user_id, stored in rows:
        if stored.startswith("$argon2"):
            continue  # already hashed
        codes = [code.strip() for code in stored.split(",") if code.strip()]
        bind.execute(
            sa.text("UPDATE user_credentials SET recovery_codes = :codes WHERE user_id = :user_id"),
            {"codes": hash_recovery_codes(codes) if codes else None, "user_id": user_id},
        )


def downgrade() -> None:
    # Hashes cannot be turned back into codes: users who need them are given new ones by turning MFA on again.
    pass
