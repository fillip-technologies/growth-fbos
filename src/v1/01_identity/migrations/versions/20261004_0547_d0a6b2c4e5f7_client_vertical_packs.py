"""client_vertical_packs

Verticals and vertical packs become the client's own design instead of a global list:

- `verticals` gain `client_id`; codes are unique per client, not globally.
- `vertical_packs` is rebuilt as a client-level pack (code, name, description). Its content
  moves to `vertical_pack_versions` (draft -> published), and each organization's installed
  version is recorded in `vertical_pack_installations`.
- `field_definitions` remember which pack (and version) installed them, so installing a
  pack again updates its own definitions instead of creating duplicates.

The old tables had no create API besides a stub, so they must be empty; the upgrade stops
rather than guess an owning client for existing rows.

Revision ID: d0a6b2c4e5f7
Revises: c9f5a1b3e4d6
Create Date: 2026-10-04 05:47:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types


revision: str = 'd0a6b2c4e5f7'
down_revision: Union[str, None] = 'c9f5a1b3e4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, database.types.UUIDType(length=36), nullable=nullable)


def _require_empty(conn, table: str) -> None:
    rows = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
    if rows:
        raise RuntimeError(
            f"{table} has {rows} row(s) with no owning client. Delete them (or assign them by hand) "
            "before upgrading: verticals and packs are now per client."
        )


def upgrade() -> None:
    conn = op.get_bind()
    vertical_columns = {c['name'] for c in sa.inspect(conn).get_columns('verticals')}
    if 'client_id' in vertical_columns:
        return
    _require_empty(conn, 'verticals')
    _require_empty(conn, 'vertical_packs')

    # Verticals: owned by a client, code unique within it.
    op.drop_index('ix_verticals_code', table_name='verticals')
    op.add_column('verticals', _uuid('client_id'))
    op.add_column('verticals', sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_foreign_key('fk_verticals_client_id', 'verticals', 'clients', ['client_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_verticals_client_id', 'verticals', ['client_id'], unique=False)
    op.create_index('ix_verticals_code', 'verticals', ['code'], unique=False)
    op.create_unique_constraint('uq_verticals_client_code', 'verticals', ['client_id', 'code'])

    # Packs: rebuilt as client-level definitions with versions and per-organization installs.
    op.drop_table('vertical_packs')
    op.create_table(
        'vertical_packs',
        _uuid('id'),
        _uuid('client_id'),
        _uuid('vertical_id'),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id', 'code', name='uq_vertical_packs_client_code'),
    )
    op.create_index('ix_vertical_packs_client_id', 'vertical_packs', ['client_id'], unique=False)
    op.create_index('ix_vertical_packs_vertical_id', 'vertical_packs', ['vertical_id'], unique=False)

    op.create_table(
        'vertical_pack_versions',
        _uuid('id'),
        _uuid('pack_id'),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['pack_id'], ['vertical_packs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pack_id', 'version_no', name='uq_vertical_pack_versions_pack_version'),
    )
    op.create_index('ix_vertical_pack_versions_pack_id', 'vertical_pack_versions', ['pack_id'], unique=False)

    op.create_table(
        'vertical_pack_installations',
        _uuid('id'),
        _uuid('pack_id'),
        _uuid('organization_id'),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('results', sa.JSON(), nullable=True),
        sa.Column('installed_at', sa.DateTime(), nullable=False),
        _uuid('installed_by', nullable=True),
        sa.ForeignKeyConstraint(['pack_id'], ['vertical_packs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pack_id', 'organization_id', name='uq_vertical_pack_installations_pack_org'),
    )
    op.create_index('ix_vertical_pack_installations_pack_id', 'vertical_pack_installations', ['pack_id'], unique=False)
    op.create_index(
        'ix_vertical_pack_installations_organization_id', 'vertical_pack_installations', ['organization_id'],
        unique=False,
    )

    # Field definitions: remember the pack (and version) that installed them.
    op.add_column('field_definitions', _uuid('source_pack_id', nullable=True))
    op.add_column('field_definitions', sa.Column('source_pack_version', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_field_definitions_source_pack_id', 'field_definitions', 'vertical_packs',
        ['source_pack_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_field_definitions_source_pack_id', 'field_definitions', ['source_pack_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_field_definitions_source_pack_id', table_name='field_definitions')
    op.drop_constraint('fk_field_definitions_source_pack_id', 'field_definitions', type_='foreignkey')
    op.drop_column('field_definitions', 'source_pack_version')
    op.drop_column('field_definitions', 'source_pack_id')

    op.drop_table('vertical_pack_installations')
    op.drop_table('vertical_pack_versions')
    op.drop_table('vertical_packs')
    op.create_table(
        'vertical_packs',
        _uuid('id'),
        _uuid('vertical_id'),
        _uuid('organization_id'),
        sa.Column('pack_code', sa.String(length=100), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('manifest', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('import_results', sa.JSON(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vertical_id'], ['verticals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vertical_packs_organization_id', 'vertical_packs', ['organization_id'], unique=False)
    op.create_index('ix_vertical_packs_vertical_id', 'vertical_packs', ['vertical_id'], unique=False)

    op.drop_constraint('uq_verticals_client_code', 'verticals', type_='unique')
    op.drop_index('ix_verticals_code', table_name='verticals')
    op.drop_index('ix_verticals_client_id', table_name='verticals')
    op.drop_constraint('fk_verticals_client_id', 'verticals', type_='foreignkey')
    op.drop_column('verticals', 'created_at')
    op.drop_column('verticals', 'client_id')
    op.create_index('ix_verticals_code', 'verticals', ['code'], unique=True)
