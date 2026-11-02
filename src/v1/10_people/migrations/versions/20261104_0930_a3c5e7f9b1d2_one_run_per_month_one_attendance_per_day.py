"""one payroll run per month, one attendance day per worker

Concurrent requests could create two payroll runs for the same month, or two attendance rows for the same
worker and day; every later lookup of that month or day then failed. The database now refuses the second.

Rows that already collide are not deleted (they are pay and attendance records a person must review): the
constraint is skipped for that table with a warning. After the cleanup, `alembic downgrade f2b4d6e8a0c1` then
`alembic upgrade head` adds it.

Revision ID: a3c5e7f9b1d2
Revises: f2b4d6e8a0c1
Create Date: 2026-11-04 09:30:00.000000+00:00

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c5e7f9b1d2'
down_revision: Union[str, None] = 'f2b4d6e8a0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.people")

CONSTRAINTS = (
    ('payroll_runs', 'uq_payroll_runs_org_period', ['organization_id', 'year', 'month']),
    ('daily_attendance', 'uq_daily_attendance_worker_day', ['organization_id', 'worker_id', 'work_date']),
)


def _has_duplicates(bind, table: str, columns: list[str]) -> bool:
    cols = ", ".join(columns)
    found = bind.execute(sa.text(f"SELECT {cols} FROM {table} GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 1")).first()
    return found is not None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name, columns in CONSTRAINTS:
        existing = {c['name'] for c in inspector.get_unique_constraints(table)} | {
            i['name'] for i in inspector.get_indexes(table) if i.get('unique')
        }
        if name in existing:
            continue
        if _has_duplicates(bind, table, columns):
            logger.warning(
                "%s has rows sharing (%s): %s was not added. Review and merge them, then downgrade to f2b4d6e8a0c1 and upgrade again.",
                table, ", ".join(columns), name,
            )
            continue
        op.create_unique_constraint(name, table, columns)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, name, _ in CONSTRAINTS:
        if name in {c['name'] for c in inspector.get_unique_constraints(table)}:
            op.drop_constraint(name, table, type_='unique')
