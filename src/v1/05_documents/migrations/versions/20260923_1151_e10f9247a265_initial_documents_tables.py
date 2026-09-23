"""initial_documents_tables

Revision ID: e10f9247a265
Revises: 
Create Date: 2026-09-23 11:51:51.428878+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import database.types


revision: str = 'e10f9247a265'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    try:
        inspector = sa.inspect(conn)
        if inspector is not None and 'document_categories' in inspector.get_table_names():
            return
    except (sa.exc.NoInspectionAvailable, sa.exc.OperationalError, sa.exc.ProgrammingError):
        pass

    # 1. retention_policies
    op.create_table(
        'retention_policies',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('retain_days', sa.Integer(), nullable=False),
        sa.Column('trigger', sa.String(length=50), nullable=False),
        sa.Column('final_action', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_retention_policies_code'), 'retention_policies', ['code'], unique=True)
    op.create_index(op.f('ix_retention_policies_organization_id'), 'retention_policies', ['organization_id'], unique=False)

    # 2. document_categories
    op.create_table(
        'document_categories',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('default_classification', sa.String(length=50), nullable=False),
        sa.Column('retention_policy_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('allowed_mime_types', sa.String(length=500), nullable=True),
        sa.Column('max_file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['retention_policy_id'], ['retention_policies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_categories_code'), 'document_categories', ['code'], unique=True)
    op.create_index(op.f('ix_document_categories_organization_id'), 'document_categories', ['organization_id'], unique=False)
    op.create_index(op.f('ix_document_categories_retention_policy_id'), 'document_categories', ['retention_policy_id'], unique=False)

    # 3. documents
    op.create_table(
        'documents',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('category_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('classification', sa.String(length=50), nullable=False),
        sa.Column('owner_user_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('owner_user_name', sa.String(length=255), nullable=False),
        sa.Column('owner_avatar_url', sa.String(length=500), nullable=True),
        sa.Column('current_version_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('legal_hold', sa.Boolean(), nullable=False),
        sa.Column('retain_until', sa.Date(), nullable=True),
        sa.Column('scope_path', sa.String(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['document_categories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_category_id'), 'documents', ['category_id'], unique=False)
    op.create_index(op.f('ix_documents_code'), 'documents', ['code'], unique=True)
    op.create_index(op.f('ix_documents_current_version_id'), 'documents', ['current_version_id'], unique=False)
    op.create_index(op.f('ix_documents_organization_id'), 'documents', ['organization_id'], unique=False)
    op.create_index(op.f('ix_documents_owner_user_id'), 'documents', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_documents_scope_path'), 'documents', ['scope_path'], unique=False)
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)

    # 4. storage_objects
    op.create_table(
        'storage_objects',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.String(length=500), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('scan_status', sa.String(length=50), nullable=False),
        sa.Column('encryption', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_storage_objects_object_key'), 'storage_objects', ['object_key'], unique=True)

    # 5. document_versions
    op.create_table(
        'document_versions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('storage_object_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('change_note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('uploaded_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('uploaded_by_name', sa.String(length=255), nullable=False),
        sa.Column('uploaded_by_avatar_url', sa.String(length=500), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['storage_object_id'], ['storage_objects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_versions_document_id'), 'document_versions', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_versions_storage_object_id'), 'document_versions', ['storage_object_id'], unique=False)

    # 6. document_links
    op.create_table(
        'document_links',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('subject_type', sa.String(length=100), nullable=False),
        sa.Column('subject_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('label', sa.String(length=500), nullable=True),
        sa.Column('link_role', sa.String(length=50), nullable=False),
        sa.Column('linked_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_links_document_id'), 'document_links', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_links_subject_id'), 'document_links', ['subject_id'], unique=False)
    op.create_index(op.f('ix_document_links_subject_type'), 'document_links', ['subject_type'], unique=False)

    # 7. document_grants
    op.create_table(
        'document_grants',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('principal_type', sa.String(length=50), nullable=False),
        sa.Column('principal_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('level', sa.String(length=50), nullable=False),
        sa.Column('granted_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_grants_document_id'), 'document_grants', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_grants_principal_id'), 'document_grants', ['principal_id'], unique=False)

    # 8. document_shares
    op.create_table(
        'document_shares',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('version_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('raw_token_preview', sa.String(length=64), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_downloads', sa.Integer(), nullable=True),
        sa.Column('download_count', sa.Integer(), nullable=False),
        sa.Column('created_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_shares_document_id'), 'document_shares', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_shares_token_hash'), 'document_shares', ['token_hash'], unique=True)
    op.create_index(op.f('ix_document_shares_version_id'), 'document_shares', ['version_id'], unique=False)

    # 9. document_access_logs
    op.create_table(
        'document_access_logs',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('version_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('actor_user_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('share_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['share_id'], ['document_shares.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_access_logs_actor_user_id'), 'document_access_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_document_access_logs_document_id'), 'document_access_logs', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_access_logs_share_id'), 'document_access_logs', ['share_id'], unique=False)
    op.create_index(op.f('ix_document_access_logs_version_id'), 'document_access_logs', ['version_id'], unique=False)

    # 10. upload_sessions
    op.create_table(
        'upload_sessions',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('document_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('category_code', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('link_subject_type', sa.String(length=100), nullable=True),
        sa.Column('link_subject_id', database.types.UUIDType(length=36), nullable=True),
        sa.Column('link_role', sa.String(length=50), nullable=True),
        sa.Column('upload_url', sa.String(length=1024), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_by', database.types.UUIDType(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_upload_sessions_document_id'), 'upload_sessions', ['document_id'], unique=False)
    op.create_index(op.f('ix_upload_sessions_organization_id'), 'upload_sessions', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_table('upload_sessions')
    op.drop_table('document_access_logs')
    op.drop_table('document_shares')
    op.drop_table('document_grants')
    op.drop_table('document_links')
    op.drop_table('document_versions')
    op.drop_table('storage_objects')
    op.drop_table('documents')
    op.drop_table('document_categories')
    op.drop_table('retention_policies')
