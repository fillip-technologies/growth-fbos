"""client unlimited plan

A client with no organization quota, no per-organization user quota or no subscription end date is
unlimited on that axis. This lets the operator company that runs FBOS use it without a service window
or seat limits. Existing clients keep their values.

Revision ID: b6d8f0a2c4e5
Revises: a5c7e9f1b3d4
Create Date: 2026-11-06 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b6d8f0a2c4e5'
down_revision: Union[str, None] = 'a5c7e9f1b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('clients') as batch:
        batch.alter_column('max_organizations', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('max_users_per_org', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('subscription_end', existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    # Unlimited clients get the platform defaults back (2 orgs, 50 users) and a window ending
    # one year after it started, so the NOT NULL constraints can be restored.
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE clients SET max_organizations = 2 WHERE max_organizations IS NULL"))
    bind.execute(sa.text("UPDATE clients SET max_users_per_org = 50 WHERE max_users_per_org IS NULL"))
    rows = bind.execute(sa.text("SELECT id, subscription_start FROM clients WHERE subscription_end IS NULL")).fetchall()
    for row in rows:
        start = row.subscription_start
        if isinstance(start, str):
            from datetime import date
            start = date.fromisoformat(start)
        try:
            end = start.replace(year=start.year + 1)
        except ValueError:  # 29 Feb
            end = start.replace(year=start.year + 1, day=28)
        bind.execute(sa.text("UPDATE clients SET subscription_end = :e WHERE id = :id"), {"e": end, "id": row.id})

    with op.batch_alter_table('clients') as batch:
        batch.alter_column('max_organizations', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('max_users_per_org', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('subscription_end', existing_type=sa.Date(), nullable=False)
