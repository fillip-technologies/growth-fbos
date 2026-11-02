"""drop access role mappings

Access now follows the Identity roles a post lists (worker_posts.role_codes), not a job-to-role table.
Before the table goes, what it granted is copied onto the posts that matched it, so the next sync keeps
that access: Identity already holds those roles as People's, and a post that listed nothing would lose them.

Revision ID: e1a3c5b7d9f2
Revises: c9e1a3b5d7f9
Create Date: 2026-11-03 10:00:00.000000+00:00

"""
import json
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

import database.types

revision: str = 'e1a3c5b7d9f2'
down_revision: Union[str, None] = 'c9e1a3b5d7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def roles_for_post(title: str, job_profile_id: Optional[str], mappings: list[dict]) -> list[dict]:
    """What the old rule gave a post: its job profile's mappings, else those of its title (or of each name in "A / B")."""
    matched = [m for m in mappings if job_profile_id and m['match_type'] == 'job_profile' and m['match_value'] == job_profile_id]
    if not matched:
        titles = {title.strip().lower(), *(part.strip().lower() for part in title.split(' / '))}
        matched = [m for m in mappings if m['match_type'] == 'designation' and m['match_value'] in titles]
    roles: dict[tuple[str, str], dict] = {}
    for mapping in matched:
        scope = 'department' if mapping['scope'] == 'department' else 'organization'
        roles.setdefault((mapping['role_code'].lower(), scope), {'role_code': mapping['role_code'], 'scope': scope})
    return list(roles.values())


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('access_role_mappings'):
        return
    mappings = [dict(row._mapping) for row in bind.execute(sa.text(
        'SELECT organization_id, match_type, match_value, role_code, scope FROM access_role_mappings'))]
    by_organization: dict[str, list[dict]] = {}
    for mapping in mappings:
        by_organization.setdefault(str(mapping['organization_id']), []).append(mapping)

    if by_organization:
        posts = bind.execute(sa.text(
            "SELECT p.id, p.organization_id, p.title, p.role_codes, s.job_profile_id FROM worker_posts p "
            "LEFT JOIN positions s ON s.id = p.position_id WHERE p.status = 'active'"))
        for post in list(posts):
            organization_mappings = by_organization.get(str(post.organization_id))
            if not organization_mappings:
                continue
            given = roles_for_post(post.title, str(post.job_profile_id) if post.job_profile_id else None, organization_mappings)
            existing = json.loads(post.role_codes) if isinstance(post.role_codes, str) else (post.role_codes or [])
            if given and not existing:
                bind.execute(sa.text('UPDATE worker_posts SET role_codes = :roles WHERE id = :id'),
                             {'roles': json.dumps(given), 'id': str(post.id)})
    op.drop_table('access_role_mappings')


def downgrade() -> None:
    op.create_table('access_role_mappings',
        sa.Column('id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('organization_id', database.types.UUIDType(length=36), nullable=False),
        sa.Column('match_type', sa.String(length=20), nullable=False),
        sa.Column('match_value', sa.String(length=255), nullable=False),
        sa.Column('role_code', sa.String(length=100), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('created_by', database.types.UUIDType(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'match_type', 'match_value', 'role_code', name='uq_access_role_mappings'),
    )
    op.create_index(op.f('ix_access_role_mappings_organization_id'), 'access_role_mappings', ['organization_id'], unique=False)
