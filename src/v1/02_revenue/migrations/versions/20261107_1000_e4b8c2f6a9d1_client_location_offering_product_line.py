"""client location and offering product line

Customers get `country` (ISO-2) and `state_code` (GST state code) columns, copies of the billing
address kept in step on every save, so dashboards can group customers without parsing it. Existing
customers are filled from their address; a missing state falls back to the GSTIN's first two digits.
Offerings get `product_line` (hardware, software, services, amc, training, other), left empty.

Revision ID: e4b8c2f6a9d1
Revises: d2a8f6c3e1b7
Create Date: 2026-11-07 10:00:00.000000+00:00

"""
import json
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4b8c2f6a9d1'
down_revision: Union[str, None] = 'd2a8f6c3e1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOME_COUNTRY = 'IN'


def _location(billing_address: Optional[str], gstin: Optional[str]) -> tuple[str, Optional[str]]:
    try:
        address = json.loads(billing_address) if billing_address else {}
    except (TypeError, ValueError):
        address = {}
    if not isinstance(address, dict):
        address = {}
    country = str(address.get('country') or HOME_COUNTRY).strip().upper()[:2] or HOME_COUNTRY
    state = str(address.get('state_code') or '').strip()[:2]
    if not state and gstin and gstin[:2].isdigit():
        state = gstin[:2]
    return country, state or None


def upgrade() -> None:
    bind = op.get_bind()
    client_columns = {c['name'] for c in sa.inspect(bind).get_columns('clients')}
    if 'country' not in client_columns:
        op.add_column('clients', sa.Column('country', sa.String(length=2), nullable=False, server_default=HOME_COUNTRY))
    if 'state_code' not in client_columns:
        op.add_column('clients', sa.Column('state_code', sa.String(length=2), nullable=True))
        op.create_index('ix_clients_state_code', 'clients', ['state_code'])
    offering_columns = {c['name'] for c in sa.inspect(bind).get_columns('offerings')}
    if 'product_line' not in offering_columns:
        op.add_column('offerings', sa.Column('product_line', sa.String(length=30), nullable=True))
        op.create_index('ix_offerings_product_line', 'offerings', ['product_line'])

    rows = bind.execute(sa.text('SELECT id, billing_address, gstin FROM clients')).fetchall()
    for row in rows:
        country, state = _location(row.billing_address, row.gstin)
        bind.execute(
            sa.text('UPDATE clients SET country = :country, state_code = :state WHERE id = :id'),
            {'country': country, 'state': state, 'id': row.id},
        )


def downgrade() -> None:
    op.drop_index('ix_offerings_product_line', table_name='offerings')
    op.drop_column('offerings', 'product_line')
    op.drop_index('ix_clients_state_code', table_name='clients')
    op.drop_column('clients', 'state_code')
    op.drop_column('clients', 'country')
