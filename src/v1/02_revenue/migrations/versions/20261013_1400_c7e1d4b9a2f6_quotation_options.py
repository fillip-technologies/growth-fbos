"""quotation options: a name per option, and the main one per opportunity

Before this, an opportunity had one live quotation at a time (the others superseded or
rejected), so the newest one that isn't superseded becomes its main quotation.

Revision ID: c7e1d4b9a2f6
Revises: b4c8e2f1a9d3
Create Date: 2026-10-13 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'c7e1d4b9a2f6'
down_revision: Union[str, None] = 'b4c8e2f1a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

quotations = sa.table(
    'quotations',
    sa.column('id', database.types.UUIDType(length=36)),
    sa.column('opportunity_id', database.types.UUIDType(length=36)),
    sa.column('status', sa.String(50)),
    sa.column('revision_no', sa.Integer()),
    sa.column('created_at', sa.DateTime()),
    sa.column('is_main', sa.Boolean()),
)


def upgrade() -> None:
    with op.batch_alter_table('quotations') as batch:
        batch.add_column(sa.Column('name', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('is_main', sa.Boolean(), server_default=sa.false(), nullable=False))

    bind = op.get_bind()
    rows = bind.execute(
        sa.select(quotations.c.id, quotations.c.opportunity_id)
        .where(quotations.c.opportunity_id.is_not(None), quotations.c.status != 'superseded')
        .order_by(quotations.c.created_at.desc(), quotations.c.revision_no.desc())
    ).all()
    main: dict = {}
    for quote_id, opportunity_id in rows:
        main.setdefault(opportunity_id, quote_id)
    for quote_id in main.values():
        bind.execute(quotations.update().where(quotations.c.id == quote_id).values(is_main=True))


def downgrade() -> None:
    with op.batch_alter_table('quotations') as batch:
        batch.drop_column('is_main')
        batch.drop_column('name')
