"""client_subscription_window

Adds the platform-admin controlled service window to clients and switches
organizations.fiscal_year_start from MM-DD to DD-MM.

Revision ID: c7a41e9d2b10
Revises: b3d653648b0a
Create Date: 2026-10-01 05:41:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7a41e9d2b10'
down_revision: Union[str, None] = 'b3d653648b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_fiscal_year_parts() -> None:
    # "MM-DD" <-> "DD-MM": the swap is its own inverse.
    op.execute(
        "UPDATE organizations "
        "SET fiscal_year_start = substr(fiscal_year_start, 4, 2) || '-' || substr(fiscal_year_start, 1, 2)"
    )


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('clients')}
    if 'subscription_start' not in columns:
        op.add_column('clients', sa.Column('subscription_start', sa.Date(), nullable=True))
    if 'subscription_end' not in columns:
        op.add_column('clients', sa.Column('subscription_end', sa.Date(), nullable=True))

    # Existing clients get a one-year window from their creation date.
    # Dates are computed in Python so this works on every backend.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, created_at FROM clients WHERE subscription_start IS NULL")).fetchall()
    for row in rows:
        created = row.created_at
        if isinstance(created, str):
            from datetime import datetime
            created = datetime.fromisoformat(created)
        start = created.date()
        try:
            end = start.replace(year=start.year + 1)
        except ValueError:  # 29 Feb
            end = start.replace(year=start.year + 1, day=28)
        bind.execute(
            sa.text("UPDATE clients SET subscription_start = :s, subscription_end = :e WHERE id = :id"),
            {"s": start, "e": end, "id": row.id},
        )

    with op.batch_alter_table('clients') as batch:
        batch.alter_column('subscription_start', existing_type=sa.Date(), nullable=False)
        batch.alter_column('subscription_end', existing_type=sa.Date(), nullable=False)

    _swap_fiscal_year_parts()


def downgrade() -> None:
    _swap_fiscal_year_parts()
    op.drop_column('clients', 'subscription_end')
    op.drop_column('clients', 'subscription_start')
